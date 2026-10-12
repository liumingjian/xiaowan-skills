import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time

from .common import MAX_LOG, Refusal, atomic, connect, encode, private_dir, runtime_version

LABEL = "dev.xiaowan.rexec.worker"
# launchd unloads a service asynchronously and may refuse to load it again until done.
SETTLE = 15
# A fresh worker heartbeats on its first tick; launchd retries a failed start every 10 s.
VERIFY = 60


def plist(root):
    package = Path(__file__).resolve().parent.parent
    return {"Label": LABEL, "ProgramArguments": [sys.executable, "-m", "rexec_runtime", "worker"], "EnvironmentVariables": {"PYTHONPATH": str(package), "REXEC_STATE_DIR": str(root), "PATH": os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin")}, "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10, "StandardOutPath": str(root / "worker.stdout"), "StandardErrorPath": str(root / "worker.stderr"), "ProcessType": "Background", "ExitTimeOut": 5, "AbandonProcessGroup": True}


def setup(root):
    root = private_dir(root)
    from .local import ssh_exchange
    response = ssh_exchange(root, "rexec-provision", b"")
    try:
        value = response.decode("ascii").strip()
    except UnicodeError:
        raise Refusal("PROVISION_FAILED")
    if not 32 <= len(value) <= 128 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value):
        raise Refusal("PROVISION_FAILED")
    atomic(root / "worker.token", value.encode())
    return {"configured": True}


def service(root, action):
    root = private_dir(root)
    target = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    domain = "gui/" + str(os.getuid())
    if action == "install":
        if not (root / "worker.token").exists():
            raise Refusal("SETUP_REQUIRED")
        for name in ("worker.stdout", "worker.stderr"):
            fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.close(fd)
            os.chmod(root / name, 0o600)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink() or target.is_symlink():
            raise Refusal("PRIVATE_STORAGE_REQUIRED")
        descriptor, temporary = tempfile.mkstemp(prefix=".rexec-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(plistlib.dumps(plist(root)))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            from .common import fsync_dir
            fsync_dir(target.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"installed": True, "started": False}
    commands = {
        "start": ["launchctl", "bootstrap", domain, str(target)],
        "stop": ["launchctl", "bootout", domain + "/" + LABEL],
        "status": ["launchctl", "print", domain + "/" + LABEL],
    }
    if action not in commands:
        raise Refusal()
    def loaded():
        return subprocess.run(commands["status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0
    try:
        if action == "stop":
            if not loaded():
                return {"running": False}
            result = subprocess.run(commands["stop"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            deadline = time.monotonic() + SETTLE
            while loaded():
                if time.monotonic() >= deadline:
                    atomic(root / "service.stderr", result.stderr[:MAX_LOG])
                    raise Refusal("SERVICE_ACTION_FAILED")
                time.sleep(0.5)
            return {"running": False}
        if action == "start":
            if loaded():
                return {"running": True}
            deadline = time.monotonic() + SETTLE
            while True:
                result = subprocess.run(commands["start"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
                if result.returncode == 0 or loaded() or time.monotonic() >= deadline:
                    break
                time.sleep(1)
            atomic(root / "service.stderr", result.stderr[:MAX_LOG])
            if not loaded():
                raise Refusal("SERVICE_ACTION_FAILED", 70, {"log": str(root / "service.stderr")})
            return {"running": True}
        result = subprocess.run(commands[action], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal("SERVICE_UNAVAILABLE")
    atomic(root / "service.stderr", result.stderr[:MAX_LOG])
    return {"installed": target.is_file(), "running": result.returncode == 0}


def verify(root, since):
    """Wait until a worker started at or after `since` (epoch seconds) has heartbeated to the VPS."""
    root = private_dir(root)
    from .local import SCHEMA
    db = connect(root, SCHEMA)
    crash = root / "worker.failure"
    deadline = time.monotonic() + float(os.environ.get("REXEC_VERIFY_SECONDS", VERIFY))
    while True:
        contact = db.execute("SELECT value FROM settings WHERE key='contact'").fetchone()
        if contact and float(contact[0]) >= since:
            return {"running": True, "connected": True, "runtime": runtime_version()}
        if crash.exists() and crash.stat().st_mtime >= since:
            raise Refusal("WORKER_CRASHED", 70, {"log": str(crash)})
        if time.monotonic() >= deadline:
            health = db.execute("SELECT value FROM settings WHERE key='health'").fetchone()
            counts = {}
            for batch in json.loads(health[0]) if health else []:
                counts.update(batch["counts"])
            raise Refusal("WORKER_NOT_CONNECTED", 70, {"launchd_loaded": service(root, "status")["running"], "failures": sorted(counts), "log": str(root / "transport.stderr")})
        time.sleep(1)
