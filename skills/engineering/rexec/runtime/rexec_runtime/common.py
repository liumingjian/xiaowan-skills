import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time

MAX_SNAPSHOT = 64 * 1024 * 1024
MAX_FILES = 20000
MAX_LOG = 1024 * 1024
MAX_OUTPUT = 16384
MAX_ARTIFACT = 2 * 1024 * 1024
MAX_ARTIFACTS = 16
MAX_RPC = 96 * 1024 * 1024
MAX_RECONCILE = 102
RETENTION = 7 * 86400
HISTORY = 90 * 86400
HEALTH_WINDOW = 3600
MAX_NOTE = 280
CATEGORIES = {"confusing_output", "unexpected_failure", "slow", "missing_capability", "docs_unclear", "other"}
MIN_FREE = 256 * 1024 * 1024
ID = re.compile(r"^[a-f0-9]{32}$")
# Failure and error reasons are fixed identifiers, never free text.
CODE = re.compile(r"^[A-Z][A-Z_]{0,39}$")
STATES = {"RECEIVED", "PREPARING", "READY", "START_RESERVED", "RUNNING", "TERMINAL"}
REASONS = {"ACCEPTED", "CLAIMED", "PREPARING", "STARTED", "COMPLETED", "CANCELLED", "DEADLINE", "EXECUTION_UNKNOWN", "SNAPSHOT_REJECTED", "OUTPUT_BLOCKED", "LOW_SPACE", "LAUNCH_FAILED", "CONNECTIVITY", "ARTIFACT_BLOCKED", "RESULT_STORED"}


class Refusal(Exception):
    def __init__(self, reason="INVALID_REQUEST", code=2):
        self.reason = reason
        self.code = code
        super().__init__(reason)


def finite(value, upper=1000000000):
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= upper


def opaque():
    return secrets.token_hex(16)


def valid_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Refusal()
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise Refusal("PRIVATE_STORAGE_REQUIRED")
    os.chmod(path, 0o700)
    return path


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data):
    path = Path(path)
    private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def immutable(path, data):
    path = Path(path)
    private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".seal-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, path)
            fsync_dir(path.parent)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise Refusal("BLOB_CONFLICT")
    finally:
        os.unlink(temporary)


def connect(root, schema):
    private_dir(root)
    db = sqlite3.connect(Path(root) / "state.sqlite", timeout=30, isolation_level=None)
    os.chmod(Path(root) / "state.sqlite", 0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(schema)
    return db


@contextlib.contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def read_json(stream):
    data = stream.read(MAX_RPC + 1)
    if len(data) > MAX_RPC:
        raise Refusal("REQUEST_TOO_LARGE")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise Refusal()
    if not isinstance(value, dict):
        raise Refusal()
    return value


def event(db, job, phase, reason, outcome="pending", attempt=1):
    if reason not in REASONS:
        raise Refusal()
    sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE job_id=?", (job,)).fetchone()[0]
    created = db.execute("SELECT created FROM jobs WHERE id=?", (job,)).fetchone()[0]
    value = {"job_id": job, "sequence": sequence, "phase": phase, "duration": round(max(0, time.time() - created), 3), "attempt": attempt, "outcome": outcome, "reason": reason}
    db.execute("INSERT INTO events VALUES(?,?,?)", (job, sequence, encode(value).decode()))
    return value


def root_path(kind):
    return Path(os.environ.get("REXEC_STATE_DIR", "/var/lib/rexec" if kind == "server" else str(Path.home() / ".local/share/rexec")))


def reject_legacy():
    if "REXEC_HOST" in os.environ or "REXEC_MAC" in os.environ:
        raise Refusal("REMOVED_CONTROL")


def walk_regular(root, byte_limit, count_limit, prune=None, include_directories=False):
    """Walk descriptor-relative entries so directory swaps cannot follow links."""
    import stat
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    count = total = 0
    def visit(parent_fd, prefix, depth):
        nonlocal count, total
        if depth > 32:
            raise Refusal("TREE_LIMIT")
        names = []
        with os.scandir(parent_fd) as iterator:
            for entry in iterator:
                names.append(entry.name)
                if len(names) > count_limit:
                    raise Refusal("TREE_LIMIT")
        for name in sorted(names):
            relative = prefix + name
            if prune and prune(relative):
                continue
            count += 1
            if count > count_limit:
                raise Refusal("TREE_LIMIT")
            mode = os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if stat.S_ISDIR(mode):
                if include_directories:
                    yield relative, None, mode
                child = os.open(name, flags | os.O_DIRECTORY, dir_fd=parent_fd)
                try:
                    yield from visit(child, relative + "/", depth + 1)
                finally:
                    os.close(child)
            elif stat.S_ISREG(mode):
                child = os.open(name, flags, dir_fd=parent_fd)
                try:
                    info = os.fstat(child)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > byte_limit - total:
                        raise Refusal("TREE_LIMIT")
                    with os.fdopen(child, "rb", closefd=False) as stream:
                        data = stream.read(byte_limit - total + 1)
                    total += len(data)
                    if total > byte_limit:
                        raise Refusal("TREE_LIMIT")
                    yield relative, data, info.st_mode
                finally:
                    os.close(child)
            else:
                raise Refusal("UNSAFE_FILE")
    try:
        yield from visit(root_fd, "", 0)
    finally:
        os.close(root_fd)
