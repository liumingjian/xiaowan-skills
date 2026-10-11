import io
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

from .common import MAX_FILES, MAX_SNAPSHOT, Refusal, atomic, digest, private_dir

EXCLUDED = {".netrc", ".npmrc", ".pypirc", ".git-credentials", "auth.json", ".codex-out", "node_modules", ".venv", "venv", "__pycache__", ".cache", ".ssh", ".aws", ".npm", ".pnpm-store", ".DS_Store", ".rexec", "codex.jsonl", "codex.stderr"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def safe_name(name):
    path = PurePosixPath(name)
    if not name or len(name) > 1024 or path.is_absolute() or "\\" in name or any(p in ("", ".", "..") for p in name.split("/")) or any(ord(c) < 32 for c in name):
        raise Refusal("SNAPSHOT_REJECTED")
    return name


def freeze(source, with_git=False):
    from .common import walk_regular
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise Refusal("SNAPSHOT_REJECTED")
    def excluded(name):
        parts = PurePosixPath(name).parts
        if any(part in EXCLUDED or part.startswith(".env") for part in parts):
            return True
        if ".git" in parts:
            if not with_git or any(part in {"hooks", "logs", "config", "config.worktree", "credentials"} for part in parts[parts.index(".git") + 1:]):
                return True
        leaf = parts[-1].lower()
        return leaf.endswith(SECRET_SUFFIXES) or "credential" in leaf or "secret" in leaf
    out = io.BytesIO()
    try:
        with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data, mode in walk_regular(source, MAX_SNAPSHOT, MAX_FILES, excluded, True):
                entry = tarfile.TarInfo(safe_name(name))
                entry.size = len(data) if data is not None else 0
                if data is None:
                    entry.type = tarfile.DIRTYPE
                entry.mode = 0o700 if mode & 0o111 else 0o600
                entry.mtime = 0
                archive.addfile(entry, io.BytesIO(data) if data is not None else None)
                if out.tell() > MAX_SNAPSHOT:
                    raise Refusal("SNAPSHOT_REJECTED")
    except (OSError, Refusal, ValueError):
        raise Refusal("SNAPSHOT_REJECTED")
    data = out.getvalue()
    if len(data) > MAX_SNAPSHOT:
        raise Refusal("SNAPSHOT_REJECTED")
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
    for name, blob, mode in entries:
        target = root / name
        if blob is None:
            private_dir(target)
            continue
        atomic(target, blob)
        os.chmod(target, 0o700 if mode & 0o111 else 0o600)
