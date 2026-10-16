"""Dependency trees kept between jobs from one source workspace.

A job that exits 0 leaves its `node_modules` trees here, and the next job from the same source starts with a
copy-on-write clone of them, so `pnpm install` or `npm install` only reconciles against the lockfile instead of
relinking every package. Each entry is written once under the id of the job that left it, and `current` names the
newest, so a clone never reads a tree that is being replaced. Entries are best effort: any failure means a cold start.
"""
import contextlib
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

from .common import RETENTION, atomic, private_dir

NAMES = {"node_modules"}
# Caches inside a dependency tree that may record the old workspace path; tools rebuild them.
VOLATILE = (".cache", ".vite", ".vitest")
DEPTH = 4
# clonefile(2) flag: clone a link itself rather than what it points to.
CLONE_NOFOLLOW = 1
# A superseded entry may still be under a clone; drop it once no clone can still be reading it.
SUPERSEDED_GRACE = 3600


def trees(root):
    """Relative paths of the outermost dependency trees beneath root."""
    found = []
    def walk(directory, depth):
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name in NAMES:
                found.append(Path(entry.path).relative_to(root))
            elif depth < DEPTH and not entry.name.startswith("."):
                walk(entry.path, depth + 1)
    walk(root, 0)
    return sorted(found)


def current(root, workspace):
    """The newest entry for a source workspace, or None."""
    base = Path(root) / "warm" / workspace
    try:
        name = (base / "current").read_text().strip()
    except OSError:
        return None
    entry = base / name
    return entry if name and entry.is_dir() and not entry.is_symlink() else None


def keep(local, workspace, job, tree):
    """Move a finished job's dependency trees into a new entry and make it current."""
    found = trees(tree)
    if not found:
        return
    base = private_dir(local.root / "warm")
    base = private_dir(base / workspace)
    entry = base / job
    for relative in found:
        target = entry / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.rename(tree / relative, target)
        for name in VOLATILE:
            if (target / name).is_dir() and not (target / name).is_symlink():
                local.discard(target / name)
    atomic(base / "current", job.encode())


def clone(source, target):
    """Copy-on-write copy of a tree. On macOS one clonefile(2) call clones the whole hierarchy in the kernel, about
    twenty times faster than `cp -c` cloning file by file (2 s against 41 s for a 48k-entry node_modules)."""
    if sys.platform == "darwin":
        with contextlib.suppress(OSError, AttributeError):
            if ctypes.CDLL(None, use_errno=True).clonefile(os.fsencode(source), os.fsencode(target), CLONE_NOFOLLOW) == 0:
                return True
    command = ["cp", "-cR", str(source), str(target)] if sys.platform == "darwin" else ["cp", "-a", "--reflink=auto", str(source), str(target)]
    return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def restore(entry, workspace):
    """Clone an entry's trees into a fresh workspace where their parent directory exists."""
    for relative in trees(entry):
        target = Path(workspace) / relative
        if not target.parent.is_dir() or os.path.lexists(target):
            continue
        if not clone(entry / relative, target):
            subprocess.run(["rm", "-rf", "--", str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prune(local):
    """Drop superseded entries after their grace, and a whole source unused for the retention period."""
    root = local.root / "warm"
    if not root.is_dir():
        return
    now = time.time()
    for base in root.iterdir():
        if base.is_symlink() or not base.is_dir():
            continue
        newest = current(local.root, base.name)
        if newest is None or newest.stat().st_mtime < now - RETENTION:
            local.discard(base)
            continue
        for entry in base.iterdir():
            if entry.is_dir() and not entry.is_symlink() and entry != newest and entry.stat().st_mtime < now - SUPERSEDED_GRACE:
                local.discard(entry)
