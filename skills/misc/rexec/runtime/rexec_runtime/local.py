import base64
import contextlib
import fcntl
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from .common import CAPACITY, ID, MAX_LOG, MAX_RPC, MIN_FREE, RETENTION, Refusal, atomic, connect, digest, encode, event, immutable, opaque, private_dir, read_json, transaction, valid_id
from .export import Publisher
from .snapshot import extract

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, claim TEXT UNIQUE NOT NULL, workspace TEXT NOT NULL, spec TEXT NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('RECEIVED','PREPARING','READY','START_RESERVED','RUNNING','TERMINAL')), cancel INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, nonce TEXT, socket TEXT, reserved REAL, started REAL, child_pid INTEGER, result_digest TEXT, acknowledged INTEGER NOT NULL DEFAULT 0, completed REAL);
CREATE TABLE IF NOT EXISTS events(job_id TEXT REFERENCES jobs(id), sequence INTEGER, value TEXT NOT NULL, PRIMARY KEY(job_id,sequence));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

SUPERVISOR_START_GRACE = 2


def ssh_exchange(root, endpoint, request, maintenance=None):
    if endpoint not in {"rexec-worker", "rexec-provision"}:
        raise Refusal()
    error_path = root / "transport.stderr"
    error_fd = os.open(error_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    process = subprocess.Popen(["ssh", "vps-cc", endpoint], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    response = bytearray()
    error_size = 0
    offset = 0
    deadline = time.monotonic() + 120
    next_maintenance = time.monotonic()
    try:
        for stream in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
        if request:
            selector.register(process.stdin, selectors.EVENT_WRITE, "input")
        else:
            process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ, "output")
        selector.register(process.stderr, selectors.EVENT_READ, "error")
        while selector.get_map():
            if maintenance and time.monotonic() >= next_maintenance:
                maintenance()
                next_maintenance = time.monotonic() + 0.5
            if time.monotonic() >= deadline:
                raise Refusal("CONNECTIVITY", 75)
            for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                if key.data == "input":
                    try:
                        offset += os.write(key.fileobj.fileno(), request[offset:offset + 65536])
                    except BrokenPipeError:
                        offset = len(request)
                    if offset == len(request):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    elif key.data == "output":
                        response.extend(chunk)
                        if len(response) > MAX_RPC:
                            raise Refusal("CONNECTIVITY", 75)
                    else:
                        kept = chunk[:max(0, MAX_LOG - error_size)]
                        os.write(error_fd, kept)
                        error_size += len(kept)
        try:
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise Refusal("CONNECTIVITY", 75)
        if process.returncode:
            raise Refusal("CONNECTIVITY", 75)
        return bytes(response)
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        selector.close()
        os.fsync(error_fd)
        os.close(error_fd)
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


class Transport:
    def __init__(self, root):
        self.root = root
        self.maintenance = None

    def call(self, action, **parameters):
        token = (self.root / "worker.token").read_text()
        request = encode({"token": token, "action": action, **parameters})
        response = ssh_exchange(self.root, "rexec-worker", request, self.maintenance)
        try:
            value = json.loads(response)
            if not isinstance(value, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise Refusal("CONNECTIVITY", 75)
        if "error" in value:
            raise Refusal("AUTHORIZATION_REQUIRED" if value["error"] == "AUTHORIZATION_REQUIRED" else "CONNECTIVITY", 75)
        return value


class Local:
    def __init__(self, root, transport=None):
        self.root = private_dir(root)
        self.db = connect(root, SCHEMA)
        self.transport = transport or Transport(self.root)
        self.stopping = lambda: False
        for name in ("snapshots", "outbox", "jobs"):
            private_dir(self.root / name)
        literals = [str(Path.home()), str(self.root)]
        if (self.root / "worker.token").exists():
            literals.append((self.root / "worker.token").read_text())
        if (self.root / "private-literals.json").exists():
            configured = json.loads((self.root / "private-literals.json").read_text())
            if not isinstance(configured, list) or any(not isinstance(item, str) or not item for item in configured):
                raise Refusal("OUTPUT_BLOCKED")
            literals.extend(configured)
        self.publisher = Publisher(literals)
        if isinstance(self.transport, Transport):
            self.transport.maintenance = self.recover

    def row(self, job):
        valid_id(job)
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        if not row:
            raise Refusal("JOB_NOT_FOUND", 66)
        return row

    def space(self):
        return shutil.disk_usage(self.root).free >= MIN_FREE

    def receive(self, response):
        spec = response.get("job")
        if not spec:
            return
        if not isinstance(spec, dict) or set(spec) != {"id", "claim", "workspace", "command", "cwd", "timeout", "cancel"}:
            raise Refusal("SNAPSHOT_REJECTED")
        for key in ("id", "claim", "workspace"):
            valid_id(spec[key])
        if not isinstance(spec["command"], str) or type(spec["timeout"]) is not int or not 1 <= spec["timeout"] <= 86400:
            raise Refusal("SNAPSHOT_REJECTED")
        try:
            snapshot = base64.b64decode(response["snapshot"], validate=True)
        except (ValueError, TypeError):
            raise Refusal("SNAPSHOT_REJECTED")
        value = response.get("snapshot_digest")
        if digest(snapshot) != value:
            raise Refusal("SNAPSHOT_REJECTED")
        immutable(self.root / "snapshots" / value, snapshot)
        with transaction(self.db):
            prior = self.db.execute("SELECT * FROM jobs WHERE id=?", (spec["id"],)).fetchone()
            if prior:
                if prior["claim"] != spec["claim"] or prior["spec"] != encode(spec).decode():
                    raise Refusal("CLAIM_MISMATCH")
            else:
                self.db.execute("INSERT INTO jobs(id,claim,workspace,spec,snapshot,state,cancel,created) VALUES(?,?,?,?,?,'RECEIVED',?,?)", (spec["id"], spec["claim"], spec["workspace"], encode(spec).decode(), value, int(bool(spec["cancel"])), time.time()))
            self.db.execute("DELETE FROM settings WHERE key='claim_request'")

    def claim(self):
        with transaction(self.db):
            row = self.db.execute("SELECT value FROM settings WHERE key='claim_request'").fetchone()
            request = row[0] if row else opaque()
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('claim_request',?)", (request,))
        response = self.transport.call("claim", request_id=request)
        if response.get("job"):
            self.receive(response)
        else:
            with transaction(self.db):
                self.db.execute("DELETE FROM settings WHERE key='claim_request'")

    def terminal(self, job, outcome, code, reason, stdout=b"", stderr=b"", truncated=False):
        with transaction(self.db):
            row = self.row(job)
            if row["state"] == "TERMINAL":
                return
            artifacts = []
            try:
                artifacts = self.publisher.artifacts(self.root / "jobs" / job / "artifacts")
            except Exception:
                reason = "ARTIFACT_BLOCKED"
            bundle = self.publisher.bundle(job, row["claim"], outcome, code, reason, stdout, stderr, artifacts, truncated)
            try:
                self.publisher.validate_bundle(bundle)
            except Exception:
                bundle = self.publisher.bundle(job, row["claim"], outcome, code, "OUTPUT_BLOCKED", truncated=truncated)
                self.publisher.validate_bundle(bundle)
            data = encode(bundle)
            immutable(self.root / "outbox" / job, data)
            self.db.execute("UPDATE jobs SET state='TERMINAL',result_digest=?,completed=? WHERE id=?", (digest(data), time.time(), job))
            event(self.db, job, "TERMINAL", bundle["reason"], outcome)

    def prepare(self, job):
        row = self.row(job)
        if row["cancel"]:
            self.terminal(job, "cancelled", 125, "CANCELLED")
            return
        if not self.space():
            return
        with transaction(self.db):
            self.db.execute("UPDATE jobs SET state='PREPARING' WHERE id=?", (job,))
            event(self.db, job, "PREPARING", "PREPARING")
        folder = private_dir(self.root / "jobs" / job)
        workspace = folder / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        try:
            extract((self.root / "snapshots" / row["snapshot"]).read_bytes(), row["snapshot"], workspace)
            cwd = json.loads(row["spec"])["cwd"]
            from .snapshot import safe_name
            if cwd != ".":
                safe_name(cwd)
            if not (workspace / cwd).is_dir():
                raise Refusal("SNAPSHOT_REJECTED")
            private_dir(folder / "artifacts")
            private_dir(folder / "tmp")
        except (Refusal, OSError, ValueError):
            self.terminal(job, "failed", 126, "SNAPSHOT_REJECTED")
            return
        with transaction(self.db):
            self.db.execute("UPDATE jobs SET state='READY' WHERE id=?", (job,))

    def launch(self, job):
        if not self.space():
            return
        with transaction(self.db):
            row = self.row(job)
            if row["state"] != "READY":
                return
            if row["cancel"]:
                cancelled = True
            else:
                cancelled = False
                nonce = opaque()
                control = private_dir(tempfile.mkdtemp(prefix="rexec-", dir="/tmp")) / "control"
                self.db.execute("UPDATE jobs SET state='START_RESERVED',nonce=?,socket=?,reserved=? WHERE id=?", (nonce, str(control), time.time(), job))
        if cancelled:
            self.terminal(job, "cancelled", 125, "CANCELLED")
            return
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        environment["REXEC_STATE_DIR"] = str(self.root)
        fd = os.open(os.devnull, os.O_WRONLY)
        with os.fdopen(fd, "ab") as errors:
            try:
                subprocess.Popen([sys.executable, "-m", "rexec_runtime", "supervise", job], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, env=environment, start_new_session=True, close_fds=True)
            except OSError:
                self.terminal(job, "failed", 126, "LAUNCH_FAILED")

    def proof(self, row, action="ping"):
        try:
            with socket.socket(socket.AF_UNIX) as control:
                control.settimeout(0.3)
                control.connect(row["socket"])
                control.sendall(encode({"nonce": row["nonce"], "action": action}))
                value = json.loads(control.recv(1024))
                return value == {"nonce": row["nonce"], "owned": True}
        except (OSError, ValueError, TypeError):
            return False

    def recover(self, check_execution=True):
        for row in self.db.execute("SELECT * FROM jobs WHERE state!='TERMINAL'").fetchall():
            sealed = self.root / "outbox" / row["id"]
            if sealed.exists():
                data = sealed.read_bytes()
                bundle = self.publisher.validate_bundle(json.loads(data))
                if bundle["job_id"] != row["id"] or bundle["claim_id"] != row["claim"]:
                    raise Refusal("RESULT_INVALID")
                with transaction(self.db):
                    if self.row(row["id"])["state"] != "TERMINAL":
                        self.db.execute("UPDATE jobs SET state='TERMINAL',result_digest=?,completed=? WHERE id=?", (digest(data), time.time(), row["id"]))
                        event(self.db, row["id"], "TERMINAL", bundle["reason"], bundle["outcome"])
            elif check_execution and row["state"] in {"START_RESERVED", "RUNNING"}:
                if row["state"] == "START_RESERVED" and row["reserved"] is not None and time.time() - row["reserved"] < SUPERVISOR_START_GRACE:
                    continue
                key = "proof_failure:" + row["id"]
                if self.proof(row):
                    self.db.execute("DELETE FROM settings WHERE key=?", (key,))
                else:
                    previous = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                    if previous is None:
                        self.db.execute("INSERT INTO settings VALUES(?,?)", (key, str(time.time())))
                    elif time.time() - float(previous[0]) >= 1:
                        self.terminal(row["id"], "unknown", 70, "EXECUTION_UNKNOWN")

    def reconcile(self):
        rows = self.db.execute("SELECT * FROM jobs WHERE acknowledged=0 OR state!='TERMINAL' ORDER BY created LIMIT 102").fetchall()
        if not rows:
            return
        jobs = [{"job_id": row["id"], "claim_id": row["claim"], "events": self.publisher.events([json.loads(e[0]) for e in self.db.execute("SELECT value FROM events WHERE job_id=? ORDER BY sequence", (row["id"],))])} for row in rows]
        response = self.transport.call("reconcile", jobs=jobs)
        with transaction(self.db):
            for value in response.get("jobs", []):
                self.db.execute("UPDATE jobs SET cancel=MAX(cancel,?) WHERE id=?", (int(bool(value["cancel"])), valid_id(value["job_id"])))
        for row in rows:
            if self.stopping():
                return
            if row["state"] == "TERMINAL" and not row["acknowledged"]:
                data = (self.root / "outbox" / row["id"]).read_bytes()
                value = digest(data)
                acknowledgement = self.transport.call("report", bundle=json.loads(data), digest=value)
                if acknowledgement != {"job_id": row["id"], "digest": value}:
                    raise Refusal("ACK_MISMATCH")
                with transaction(self.db):
                    self.db.execute("UPDATE jobs SET acknowledged=1 WHERE id=?", (row["id"],))

    def tick(self):
        self.recover()
        if self.stopping():
            return
        self.transport.call("heartbeat", state="READY" if self.space() else "LOW_SPACE")
        if self.stopping():
            return
        self.reconcile()
        for row in self.db.execute("SELECT id,state FROM jobs WHERE state IN ('RECEIVED','PREPARING','READY') ORDER BY created").fetchall():
            if self.stopping():
                return
            if row["state"] != "READY":
                self.prepare(row["id"])
            self.launch(row["id"])
        active = self.db.execute("SELECT COUNT(*) FROM jobs WHERE state!='TERMINAL'").fetchone()[0]
        active += sum(json.loads((self.root / "outbox" / row[0]).read_bytes())["outcome"] == "unknown" for row in self.db.execute("SELECT id FROM jobs WHERE state='TERMINAL'"))
        if active < CAPACITY and not self.stopping() and self.space():
            self.claim()
        self.gc()

    def gc(self):
        for row in self.db.execute("SELECT * FROM jobs WHERE state='TERMINAL' AND acknowledged=1 AND completed<?", (time.time() - RETENTION,)).fetchall():
            bundle = json.loads((self.root / "outbox" / row["id"]).read_bytes())
            if bundle["outcome"] == "unknown":
                continue
            with transaction(self.db):
                self.db.execute("DELETE FROM events WHERE job_id=?", (row["id"],))
                self.db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        referenced_jobs = {row[0] for row in self.db.execute("SELECT id FROM jobs")}
        for path in (self.root / "jobs").iterdir():
            if ID.fullmatch(path.name) and path.name not in referenced_jobs and not path.is_symlink():
                shutil.rmtree(path)
        for path in (self.root / "outbox").iterdir():
            if path.is_symlink():
                continue
            if path.name.startswith((".write-", ".seal-")):
                if path.is_file() and path.stat().st_mtime < time.time() - RETENTION:
                    path.unlink()
            elif ID.fullmatch(path.name) and path.name not in referenced_jobs:
                path.unlink()
        snapshots = {row[0] for row in self.db.execute("SELECT snapshot FROM jobs")}
        for path in (self.root / "snapshots").iterdir():
            if path.name not in snapshots:
                path.unlink()

    def view(self, job=None):
        if job:
            self.row(job)
            rows = self.db.execute("SELECT value FROM events WHERE job_id=? ORDER BY sequence LIMIT 1000", (job,))
        else:
            rows = self.db.execute("SELECT value FROM events ORDER BY rowid DESC LIMIT 100")
        return self.publisher.events([json.loads(row[0]) for row in rows])


def await_reserved_supervisors(local):
    for row in local.db.execute("SELECT * FROM jobs WHERE state='START_RESERVED'").fetchall():
        deadline = time.monotonic() + SUPERVISOR_START_GRACE
        while not local.stopping() and time.monotonic() < deadline:
            if local.proof(row):
                break
            time.sleep(0.1)


def worker(root):
    local = Local(root)
    lock = open(local.root / "worker.lock", "a")
    os.chmod(local.root / "worker.lock", 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise Refusal("WORKER_ALREADY_RUNNING", 73)
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    local.stopping = lambda: stopping
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    await_reserved_supervisors(local)
    local.recover()
    delay = 0.25
    while not stopping:
        try:
            local.tick()
            delay = 0.25
        except (Refusal, OSError, ValueError, KeyError):
            delay = min(30, delay * 2)
        deadline = time.monotonic() + delay
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.1, deadline - time.monotonic()))


def supervise(root, job):
    local = Local(root)
    row = local.row(job)
    if row["state"] != "START_RESERVED":
        return
    lock = open(local.root / "jobs" / job / "supervisor.lock", "a")
    os.chmod(local.root / "jobs" / job / "supervisor.lock", 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    control = socket.socket(socket.AF_UNIX)
    control.bind(row["socket"])
    os.chmod(row["socket"], 0o600)
    control.listen(4)
    control.setblocking(False)
    spec = json.loads(row["spec"])
    folder = local.root / "jobs" / job
    environment = {key: value for key, value in os.environ.items() if not key.startswith("REXEC_")}
    environment.update({"REXEC_ARTIFACTS": str(folder / "artifacts"), "TMPDIR": str(folder / "tmp"), "PYTHONPATH": str(Path(__file__).resolve().parent.parent)})
    read_gate, write_gate = os.pipe()
    read_done, write_done = os.pipe()
    process = None
    try:
        # The gate child can exist, but no command executes before RUNNING commits.
        process = subprocess.Popen([sys.executable, "-m", "rexec_runtime", "gate", str(read_gate), str(write_done), str(spec["timeout"]), spec["command"]], cwd=folder / "workspace" / spec["cwd"], env=environment, pass_fds=(read_gate, write_done), start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(read_gate)
        read_gate = -1
        os.close(write_done)
        write_done = -1
        with transaction(local.db):
            current = local.row(job)
            if current["state"] != "START_RESERVED":
                raise Refusal("EXECUTION_UNKNOWN")
            local.db.execute("UPDATE jobs SET state='RUNNING',started=?,child_pid=? WHERE id=?", (time.time(), process.pid, job))
            event(local.db, job, "RUNNING", "STARTED")
        started = time.monotonic()
        deadline = started + spec["timeout"]
        if not current["cancel"]:
            os.write(write_gate, b"G")
        selector = selectors.DefaultSelector()
        selector.register(control, selectors.EVENT_READ, "control")
        os.set_blocking(read_done, False)
        selector.register(read_done, selectors.EVENT_READ, "done")
        command_code = None
        logs = {}
        truncated = False
        for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            logs[name] = [os.fdopen(fd, "wb"), 0]
            selector.register(stream, selectors.EVENT_READ, name)
        reason = "COMPLETED"
        outcome = "completed"
        killing = False
        drain_until = None
        while True:
            cancelled = bool(local.row(job)["cancel"])
            if not killing and (cancelled or time.monotonic() >= deadline):
                reason = "CANCELLED" if cancelled else "DEADLINE"
                outcome = "cancelled" if cancelled else "timeout"
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                killing = True
            for key, _ in selector.select(0.05):
                if key.data == "done":
                    completed = os.read(read_done, 64)
                    if completed:
                        command_code = int(completed)
                        # The gate stays the group leader until this first cleanup signal.
                        if not killing:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(process.pid, signal.SIGKILL)
                            killing = True
                    if not completed and not killing:
                        reason = "EXECUTION_UNKNOWN"
                        outcome = "unknown"
                        command_code = 70
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                        killing = True
                    selector.unregister(read_done)
                    os.close(read_done)
                    read_done = -1
                    continue
                if key.data == "control":
                    connection, _ = control.accept()
                    with connection:
                        connection.settimeout(0.1)
                        try:
                            request = json.loads(connection.recv(512))
                            if request.get("nonce") == row["nonce"] and request.get("action") in {"ping", "cancel"}:
                                if request["action"] == "cancel":
                                    with transaction(local.db):
                                        local.db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job,))
                                connection.sendall(encode({"nonce": row["nonce"], "owned": True}))
                        except (OSError, ValueError):
                            pass
                    continue
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                log, size = logs[key.data]
                kept = chunk[:max(0, MAX_LOG - size)]
                log.write(kept)
                logs[key.data][1] += len(kept)
                if len(kept) != len(chunk):
                    truncated = True
            if killing:
                if drain_until is None:
                    drain_until = time.monotonic() + 1
                if not any(key.data in {"stdout", "stderr"} for key in selector.get_map().values()) or time.monotonic() >= drain_until:
                    break
        for log, _ in logs.values():
            log.flush()
            os.fsync(log.fileno())
            log.close()
        code = 125 if outcome == "cancelled" else 124 if outcome == "timeout" else command_code if command_code is not None else 70
        process.wait()
        if code < 0:
            code = min(255, 128 - code)
        local.terminal(job, outcome, code, reason, (folder / "stdout").read_bytes(), (folder / "stderr").read_bytes(), truncated)
    except BaseException:
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    finally:
        for fd in (read_gate, write_gate, read_done, write_done):
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
        control.close()
        with contextlib.suppress(OSError):
            os.unlink(row["socket"])
            os.rmdir(str(Path(row["socket"]).parent))


def gate(fd, done_fd, timeout, command):
    if os.read(fd, 1) != b"G":
        os._exit(125)
    os.set_blocking(fd, False)
    process = subprocess.Popen(["/bin/sh", "-c", command], close_fds=True)
    deadline = time.monotonic() + timeout
    sent = False
    while True:
        # The gate is the stable group leader until supervisor cleanup. It also
        # terminates the group if its supervisor dies or its own deadline expires.
        try:
            if os.read(fd, 1) == b"":
                os.killpg(os.getpgrp(), signal.SIGKILL)
        except BlockingIOError:
            pass
        if time.monotonic() >= deadline + 0.5:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        code = process.poll()
        if code is not None and not sent:
            os.write(done_fd, str(code).encode())
            os.close(done_fd)
            sent = True
        time.sleep(0.02)
