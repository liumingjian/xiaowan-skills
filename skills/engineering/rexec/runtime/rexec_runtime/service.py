import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

from .common import MAX_LOG, Refusal, atomic, encode, private_dir

LABEL = "dev.xiaowan.rexec.worker"


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
    try:
        if action in {"start", "stop"}:
            present = subprocess.run(commands["status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0
            if (action == "start" and present) or (action == "stop" and not present):
                return {"running": present}
        result = subprocess.run(commands[action], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal("SERVICE_UNAVAILABLE")
    atomic(root / "service.stderr", result.stderr[:MAX_LOG])
    if action == "status":
        return {"installed": target.is_file(), "running": result.returncode == 0}
    if result.returncode:
        raise Refusal("SERVICE_ACTION_FAILED")
    return {"running": action == "start"}
