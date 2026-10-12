import io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile

from .common import MAX_FILES, MAX_SNAPSHOT, Refusal, digest, private_dir

EXCLUDED = {".netrc", ".npmrc", ".pypirc", ".git-credentials", "auth.json", ".codex-out", "node_modules", ".venv", "venv", "__pycache__", ".cache", ".ssh", ".aws", ".npm", ".pnpm-store", ".DS_Store", ".rexec", "codex.jsonl", "codex.stderr"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
# Files named like these hold secrets; `secret_store.py` or `test_credentials.py` are code.
SECRET_STEMS = {"secret", "secrets", "credential", "credentials"}
# Snapshot reports list at most this many skipped paths.
REPORTED = 10


def safe_name(name):
    path = PurePosixPath(name)
    if not name or len(name) > 1024 or path.is_absolute() or "\\" in name or any(p in ("", ".", "..") for p in name.split("/")) or any(ord(c) < 32 for c in name):
        raise Refusal("SNAPSHOT_REJECTED")
    return name


def git_listing(source):
    """Tracked and untracked-but-not-ignored paths, or None outside a Git work tree."""
    try:
        result = subprocess.run(["git", "-C", str(source), "ls-files", "-z", "--cached", "--others", "--exclude-standard"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return {name for name in result.stdout.decode("utf-8", "surrogateescape").split("\0") if name}


def freeze(source, with_git=False, ignored=False, report=None, cwd="."):
    """Archive a source tree deterministically.

    Inside a Git work tree only files Git would keep (tracked, or untracked and not
    ignored) are taken unless `ignored`. Links and special files are skipped. `report`
    receives counts and the first skipped paths so the caller can see what was left out."""
    from .common import walk_regular
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise Refusal("SOURCE_NOT_FOUND")
    listing = None if ignored else git_listing(source)
    # The working directory survives even when Git has nothing in it.
    parents = set(str(PurePosixPath(*PurePosixPath(cwd).parts[:index])) for index in range(1, len(PurePosixPath(cwd).parts) + 1))
    for name in listing or ():
        parts = PurePosixPath(name).parts
        parents.update(str(PurePosixPath(*parts[:index])) for index in range(1, len(parts)))
    report = report if report is not None else {}
    report.update({"files": 0, "bytes": 0, "gitignore": listing is not None, "excluded": 0, "skipped": []})
    def excluded(name):
        parts = PurePosixPath(name).parts
        if ".git" in parts:
            return not with_git or any(part in {"hooks", "logs", "config", "config.worktree", "credentials"} for part in parts[parts.index(".git") + 1:])
        leaf = parts[-1].lower()
        if any(part in EXCLUDED or part.startswith(".env") for part in parts) or leaf.endswith(SECRET_SUFFIXES) or leaf.split(".")[0] in SECRET_STEMS:
            report["excluded"] += 1
            return True
        if listing is not None and name not in parents and not any(str(PurePosixPath(*parts[:index])) in listing for index in range(1, len(parts) + 1)):
            # Ignored by Git; a listed directory (a submodule) keeps everything beneath it.
            report["excluded"] += 1
            return True
        return False
    def skip(name):
        if len(report["skipped"]) < REPORTED:
            report["skipped"].append(name)
        report["skipped_count"] = report.get("skipped_count", 0) + 1
    out = io.BytesIO()
    try:
        with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data, mode in walk_regular(source, MAX_SNAPSHOT, MAX_FILES, excluded, True, skip):
                try:
                    entry = tarfile.TarInfo(safe_name(name))
                except Refusal:
                    raise Refusal("SNAPSHOT_UNSAFE_NAME")
                entry.size = len(data) if data is not None else 0
                if data is None:
                    entry.type = tarfile.DIRTYPE
                else:
                    report["files"] += 1
                    report["bytes"] += len(data)
                entry.mode = 0o700 if mode & 0o111 else 0o600
                entry.mtime = 0
                archive.addfile(entry, io.BytesIO(data) if data is not None else None)
                if out.tell() > MAX_SNAPSHOT:
                    raise Refusal("SNAPSHOT_TOO_LARGE", detail={"at": name})
    except Refusal as error:
        codes = {"TREE_BYTES": "SNAPSHOT_TOO_LARGE", "TREE_LIMIT": "SNAPSHOT_TOO_MANY_FILES"}
        detail = dict(error.detail, limit_bytes=MAX_SNAPSHOT, limit_files=MAX_FILES) if error.reason in codes else error.detail
        raise Refusal(codes.get(error.reason, error.reason if error.reason.startswith("SNAPSHOT_") else "SNAPSHOT_REJECTED"), detail=detail)
    except (OSError, ValueError):
        raise Refusal("SNAPSHOT_UNREADABLE")
    data = out.getvalue()
    if len(data) > MAX_SNAPSHOT:
        raise Refusal("SNAPSHOT_TOO_LARGE", detail={"limit_bytes": MAX_SNAPSHOT})
    return data


def extract(data, expected, destination):
    if len(data) > MAX_SNAPSHOT or digest(data) != expected:
        raise Refusal("SNAPSHOT_REJECTED")
    root = private_dir(destination)
    entries = []
    names = set()
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for entry in archive:
                name = safe_name(entry.name.rstrip("/") if entry.isdir() else entry.name)
                if name in names or not (entry.isfile() or entry.isdir()) or entry.size < 0:
                    raise Refusal("SNAPSHOT_REJECTED")
                names.add(name)
                total += entry.size
                if len(names) > MAX_FILES or total > MAX_SNAPSHOT:
                    raise Refusal("SNAPSHOT_REJECTED")
                stream = archive.extractfile(entry) if entry.isfile() else None
                blob = stream.read(entry.size + 1) if stream is not None else None
                if blob is not None and len(blob) != entry.size:
                    raise Refusal("SNAPSHOT_REJECTED")
                entries.append((name, blob, entry.mode))
        file_names = {name for name, blob, _ in entries if blob is not None}
        for name, _, _ in entries:
            parts = PurePosixPath(name).parts
            if any(str(PurePosixPath(*parts[:i])) in file_names for i in range(1, len(parts))):
                raise Refusal("SNAPSHOT_REJECTED")
    except (tarfile.TarError, OSError, ValueError):
        raise Refusal("SNAPSHOT_REJECTED")
    # A workspace is rebuilt from its snapshot whenever in doubt (the worker re-extracts
    # unlaunched jobs at start), so files skip the per-file fsync that dominated large trees.
    made = {root}
    for name, blob, mode in entries:
        target = root / name
        if blob is None:
            private_dir(target)
            made.add(target)
            continue
        if target.parent not in made:
            private_dir(target.parent)
            made.add(target.parent)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700 if mode & 0o111 else 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(blob)
        os.chmod(target, 0o700 if mode & 0o111 else 0o600)
