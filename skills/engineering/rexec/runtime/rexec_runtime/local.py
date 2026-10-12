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

from .common import CODE, ID, MAX_LOG, MAX_RECONCILE, MAX_RPC, MIN_FREE, RETENTION, Refusal, atomic, connect, digest, encode, event, immutable, opaque, private_dir, read_json, runtime_version, transaction, valid_id
from .export import Publisher
from .snapshot import extract

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, claim TEXT UNIQUE NOT NULL, workspace TEXT NOT NULL, spec TEXT NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('RECEIVED','PREPARING','READY','START_RESERVED','RUNNING','TERMINAL')), cancel INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, nonce TEXT, socket TEXT, reserved REAL, started REAL, child_pid INTEGER, result_digest TEXT, acknowledged INTEGER NOT NULL DEFAULT 0, completed REAL);
CREATE TABLE IF NOT EXISTS events(job_id TEXT REFERENCES jobs(id), sequence INTEGER, value TEXT NOT NULL, PRIMARY KEY(job_id,sequence));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

SUPERVISOR_START_GRACE = 2
CLAIMS_PER_TICK = 8
HEARTBEAT_INTERVAL = 30
# An idle worker long-polls its claim this long (the server caps it) instead of asking every tick.
CLAIM_WAIT = 20
# Running jobs are reconciled when their events change, a cancel is waiting, or this often.
RECONCILE_INTERVAL = 15
# Finished results ride along with a reconcile up to this many bytes; larger ones go alone.
INLINE_REPORTS = 8 * 1024 * 1024
# A claimed job that fails to arrive this many times is handed back instead of retried forever.
CLAIM_ATTEMPTS = 3
# Server answers meaning the server no longer tracks this job or claim; retrying cannot succeed.
ORPHANED = {"JOB_NOT_FOUND", "CLAIM_MISMATCH", "RESULT_CONFLICT"}
# Transport failures back off the whole tick; any other refusal concerns one job only.
TRANSPORT = {"SSH_FAILED", "RPC_TIMEOUT", "RPC_INVALID", "RPC_REFUSED", "AUTHORIZATION_REQUIRED", "INTERNAL_FAILURE"}
LOG_HEAD = MAX_LOG // 2
LOG_TAIL = MAX_LOG - LOG_HEAD - 64


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
                raise Refusal("RPC_TIMEOUT", 75)
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
                            raise Refusal("RPC_INVALID", 75)
                    else:
                        kept = chunk[:max(0, MAX_LOG - error_size)]
                        os.write(error_fd, kept)
                        error_size += len(kept)
        try:
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise Refusal("RPC_TIMEOUT", 75)
        # A refusing server exits nonzero after printing its fixed error code; only an
        # empty reply is a transport failure.
        if process.returncode and not response:
            raise Refusal("SSH_FAILED", 75)
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
        self.slowest = 0.0

    def call(self, action, **parameters):
        token = (self.root / "worker.token").read_text()
        request = encode({"token": token, "action": action, **parameters})
        started = time.monotonic()
        response = ssh_exchange(self.root, "rexec-worker", request, self.maintenance)
        if not parameters.get("wait"):
            # A long-polled claim lasts as long as it waits; it says nothing about SSH speed.
            self.slowest = max(self.slowest, time.monotonic() - started)
        try:
            value = json.loads(response)
            if not isinstance(value, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise Refusal("RPC_INVALID", 75)
        if "error" in value:
            # Server errors are fixed codes; keep them so worker health names the refusal.
            error = value["error"]
            raise Refusal(error if isinstance(error, str) and CODE.fullmatch(error) else "RPC_REFUSED", 75)
        return value


class Local:
    def __init__(self, root, transport=None):
        self.root = private_dir(root)
        self.db = connect(root, SCHEMA)
        self.transport = transport or Transport(self.root)
        self.stopping = lambda: False
        self.heartbeat = (None, 0.0)
        # Only the worker loop long-polls; a single tick (tests, tools) never blocks on it.
        self.idle_wait = 0
        self.waiting = False
        self.urgent = False
        self.reconciled = (None, 0.0)
        self.waited = 0.0
        self.tick_seconds = 0.0
        self.sweeper = None
        for name in ("snapshots", "outbox", "jobs", "trash"):
            private_dir(self.root / name)
        literals = [str(Path.home()), str(self.root)]
        if (self.root / "worker.token").exists():
            literals.append((self.root / "worker.token").read_text())
        if (self.root / "private-literals.json").exists():
            configured = json.loads((self.root / "private-literals.json").read_text())
            if not isinstance(configured, list) or any(not isinstance(item, str) or not item for item in configured):
                raise Refusal("OUTPUT_BLOCKED")
            literals.extend(configured)
        self.publisher = Publisher(literals, self.root / "jobs")
        if isinstance(self.transport, Transport):
            self.transport.maintenance = self.maintain

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
            self.db.execute("DELETE FROM settings WHERE key IN ('claim_request','claim_failures')")

    def quiet(self):
        """Nothing here waits on the tick: no job to prepare or launch, no result to report."""
        return not self.db.execute("SELECT 1 FROM jobs WHERE state IN ('RECEIVED','PREPARING','READY','START_RESERVED') OR (state='TERMINAL' AND acknowledged=0) LIMIT 1").fetchone()

    def maintain(self):
        """Runs every half second while an RPC is in flight."""
        self.recover()
        if self.waiting and (self.stopping() or not self.quiet()):
            # A result to report or a stop beats waiting for new work. The server keeps any job
            # it claimed meanwhile for this claim request, so the retry gets it.
            raise Refusal("INTERRUPTED", 75)

    def claim(self):
        """Claim at most one job; return whether one arrived."""
        with transaction(self.db):
            row = self.db.execute("SELECT value FROM settings WHERE key='claim_request'").fetchone()
            request = row[0] if row else opaque()
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('claim_request',?)", (request,))
        held = [row[0] for row in self.db.execute("SELECT id FROM jobs WHERE cancel=0 AND state!='TERMINAL' LIMIT ?", (MAX_RECONCILE,))]
        wait = self.idle_wait if self.idle_wait and self.quiet() else 0
        response = None
        try:
            self.waiting = bool(wait)
            began = time.monotonic()
            try:
                response = self.transport.call("claim", request_id=request, wait=wait, held=held)
            finally:
                self.waiting = False
                if wait:
                    self.waited += time.monotonic() - began
            if response.get("cancel"):
                self.urgent = True
            if response.get("job"):
                self.receive(response)
                return True
        except Refusal as error:
            if error.reason == "INTERRUPTED":
                return False
            # Connectivity failures retry the same claim indefinitely; a job that keeps
            # arriving unusable (oversized or rejected) is given up after a few tries.
            if response is not None or error.reason == "RPC_INVALID":
                self.give_up(response)
            raise
        with transaction(self.db):
            self.db.execute("DELETE FROM settings WHERE key IN ('claim_request','claim_failures')")
        return False

    def give_up(self, response):
        with transaction(self.db):
            row = self.db.execute("SELECT value FROM settings WHERE key='claim_failures'").fetchone()
            failures = (int(row[0]) if row else 0) + 1
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('claim_failures',?)", (str(failures),))
        if failures < CLAIM_ATTEMPTS:
            return
        spec = response.get("job") if isinstance(response, dict) else None
        if isinstance(spec, dict) and isinstance(spec.get("id"), str) and not self.db.execute("SELECT 1 FROM jobs WHERE id=?", (spec["id"],)).fetchone():
            # The command never started here, so the server can record a plain failure.
            # Without that answer the server's claim lease releases the job later instead.
            with contextlib.suppress(Exception):
                self.transport.call("reject", job_id=spec["id"], claim_id=spec.get("claim"))
        with transaction(self.db):
            self.db.execute("DELETE FROM settings WHERE key IN ('claim_request','claim_failures')")

    def discard(self, path):
        """Move a directory into trash; renaming is instant even for a huge tree."""
        os.rename(path, self.root / "trash" / opaque())

    def sweep(self):
        # Deleting dependency trees can take minutes, so it never runs inside a tick.
        if self.sweeper is not None and self.sweeper.poll() is None:
            return
        entries = [str(path) for path in (self.root / "trash").iterdir()]
        if entries:
            self.sweeper = subprocess.Popen(["rm", "-rf", "--", *entries], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)

    def scrub(self, job):
        """Drop a finished job's bulky files; the sealed outbox keeps its result."""
        folder = self.root / "jobs" / job
        for name in ("workspace", "tmp", "artifacts"):
            path = folder / name
            if path.is_dir() and not path.is_symlink():
                self.discard(path)

    def terminal(self, job, outcome, code, reason, stdout=b"", stderr=b"", truncated=False, expect=None):
        """Seal a result. With expect, seal only if the job is still in that state."""
        row = self.row(job)
        if row["state"] == "TERMINAL":
            return
        # Filtering output and artifacts can be slow, so it runs before the write lock.
        artifacts = refused = []
        try:
            artifacts, refused = self.publisher.collect(self.root / "jobs" / job / "artifacts")
        except Exception:
            reason = "ARTIFACT_BLOCKED"
        now = time.time()
        started = row["started"]
        timing = {"start_s": round(max(0.0, started - row["created"]), 3) if started else None, "run_s": round(max(0.0, now - started), 3) if started else None}
        bundle = self.publisher.bundle(job, row["claim"], outcome, code, reason, stdout, stderr, artifacts, truncated, timing, refused)
        try:
            self.publisher.validate_bundle(bundle)
        except Exception:
            bundle = self.publisher.bundle(job, row["claim"], outcome, code, "OUTPUT_BLOCKED", truncated=truncated, timing=timing)
            self.publisher.validate_bundle(bundle)
        data = encode(bundle)
        with transaction(self.db):
            state = self.row(job)["state"]
            if state == "TERMINAL" or (expect is not None and state != expect):
                return
            immutable(self.root / "outbox" / job, data)
            self.db.execute("UPDATE jobs SET state='TERMINAL',result_digest=?,completed=? WHERE id=?", (digest(data), now, job))
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
            self.discard(workspace)
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

    def supervised(self, job):
        """Whether a live supervisor holds this job's lock; the kernel drops it when that process dies."""
        path = self.root / "jobs" / job / "supervisor.lock"
        if not path.parent.is_dir():
            return False
        with open(path, "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock, fcntl.LOCK_UN)
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
                if self.supervised(row["id"]):
                    continue
                if row["state"] == "START_RESERVED":
                    # The gate runs nothing until RUNNING commits, and sealing here makes that commit
                    # fail, so this command never ran: a plain launch failure, safe to resubmit.
                    self.terminal(row["id"], "failed", 126, "LAUNCH_FAILED", expect="START_RESERVED")
                else:
                    # The gate killed the command's group when its supervisor died, so nothing still
                    # runs, but how far it got is unknown.
                    folder = self.root / "jobs" / row["id"]
                    logs = [(folder / name).read_bytes()[:MAX_LOG] if (folder / name).is_file() else b"" for name in ("stdout", "stderr")]
                    self.terminal(row["id"], "unknown", 70, "SUPERVISOR_LOST", *logs, expect="RUNNING")

    def reconcile(self, force=True):
        mark = self.db.execute("SELECT MAX(rowid) FROM events").fetchone()[0]
        if not (force or self.urgent or mark != self.reconciled[0] or time.monotonic() - self.reconciled[1] >= RECONCILE_INTERVAL
                or self.db.execute("SELECT 1 FROM jobs WHERE state='TERMINAL' AND acknowledged=0 LIMIT 1").fetchone()):
            # Nothing changed for running jobs; skip an RPC every tick while they run.
            return
        rows = self.db.execute("SELECT * FROM jobs WHERE acknowledged=0 OR state!='TERMINAL' ORDER BY created LIMIT ?", (MAX_RECONCILE,)).fetchall()
        self.urgent = False
        self.reconciled = (mark, time.monotonic())
        if not rows:
            return
        jobs = []
        inline = 0
        for row in rows:
            item = {"job_id": row["id"], "claim_id": row["claim"], "events": self.publisher.events([json.loads(e[0]) for e in self.db.execute("SELECT value FROM events WHERE job_id=? ORDER BY sequence", (row["id"],))])}
            if row["state"] == "TERMINAL" and not row["acknowledged"]:
                data = (self.root / "outbox" / row["id"]).read_bytes()
                if inline + len(data) <= INLINE_REPORTS:
                    inline += len(data)
                    item["report"] = {"bundle": json.loads(data), "digest": digest(data)}
            jobs.append(item)
        response = self.transport.call("reconcile", jobs=jobs)
        orphans = set()
        reported = {}
        with transaction(self.db):
            for value in response.get("jobs", []):
                job = valid_id(value["job_id"])
                if "error" in value:
                    if value["error"] in ORPHANED:
                        orphans.add(job)
                    continue
                self.db.execute("UPDATE jobs SET cancel=MAX(cancel,?) WHERE id=?", (int(bool(value["cancel"])), job))
                if "ack" in value or "report_error" in value:
                    reported[job] = value
        for row in rows:
            if self.stopping():
                return
            if row["state"] == "TERMINAL" and not row["acknowledged"] and row["id"] not in orphans:
                data = (self.root / "outbox" / row["id"]).read_bytes()
                value = digest(data)
                if row["id"] in reported:
                    # The server took or refused the result inline; an older server answers
                    # neither, and the result then goes in its own report below.
                    answer = reported[row["id"]]
                    if "report_error" in answer:
                        error = answer["report_error"]
                        if error in ORPHANED:
                            orphans.add(row["id"])
                        else:
                            self.failure(error if isinstance(error, str) and CODE.fullmatch(error) else "RPC_REFUSED")
                        continue
                    if answer["ack"] != {"job_id": row["id"], "digest": value}:
                        raise Refusal("ACK_MISMATCH")
                    with transaction(self.db):
                        self.db.execute("UPDATE jobs SET acknowledged=1 WHERE id=?", (row["id"],))
                    continue
                try:
                    acknowledgement = self.transport.call("report", bundle=json.loads(data), digest=value)
                except Refusal as error:
                    if error.reason in TRANSPORT:
                        raise
                    if error.reason in ORPHANED:
                        orphans.add(row["id"])
                    else:
                        self.failure(error.reason if CODE.fullmatch(error.reason) else "RPC_REFUSED")
                    continue
                if acknowledgement != {"job_id": row["id"], "digest": value}:
                    raise Refusal("ACK_MISMATCH")
                with transaction(self.db):
                    self.db.execute("UPDATE jobs SET acknowledged=1 WHERE id=?", (row["id"],))
        for job in orphans:
            self.orphan(job)

    def orphan(self, job):
        """Stop reporting a job the server no longer tracks (reinstalled, collected, or
        settled without us). Its local trace stays readable with `agent.sh view`."""
        row = self.row(job)
        if row["state"] != "TERMINAL":
            # Still running here: keep it, it is reported again once it seals.
            return
        with transaction(self.db):
            self.db.execute("UPDATE jobs SET acknowledged=1 WHERE id=?", (job,))
        self.failure("ORPHANED_RESULT")

    def tick(self):
        started = time.monotonic()
        self.waited = 0.0
        self.recover()
        if self.stopping():
            return
        state = "READY" if self.space() else "LOW_SPACE"
        health = self.health()
        # Every RPC refreshes last contact, so heartbeat only reports state changes, timing, and failures.
        if health or self.heartbeat[0] != state or time.monotonic() - self.heartbeat[1] >= HEARTBEAT_INTERVAL:
            slowest = getattr(self.transport, "slowest", 0.0)
            extra = {}
            if health:
                # Sent batches are frozen; the server ignores a batch it already stored.
                health = [dict(batch, sent=True) for batch in health][-16:]
                self.store_health(health)
                extra["health"] = [{"id": batch["id"], "counts": batch["counts"]} for batch in health]
            active = [row[0] for row in self.db.execute("SELECT id FROM jobs WHERE acknowledged=0 OR state!='TERMINAL' LIMIT ?", (MAX_RECONCILE + 1,))]
            if len(active) <= MAX_RECONCILE:
                # Complete lists only: the server releases claimed jobs missing from it.
                extra["active"] = active
            self.transport.call("heartbeat", state=state, timing={"tick": round(self.tick_seconds, 3), "rpc": round(slowest, 3)}, runtime=runtime_version(), **extra)
            with transaction(self.db):
                # `agent verify` reads this to confirm a freshly started worker reached the VPS.
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('contact',?)", (str(time.time()),))
            if health:
                with transaction(self.db):
                    self.store_health([batch for batch in self.health() if batch["id"] not in {sent["id"] for sent in health}])
            self.heartbeat = (state, time.monotonic())
            if hasattr(self.transport, "slowest"):
                self.transport.slowest = 0.0
        if self.stopping():
            return
        self.reconcile(force=False)
        # Claim everything available first so newly received jobs launch in this same tick.
        for _ in range(CLAIMS_PER_TICK):
            if self.stopping() or not self.space() or not self.claim():
                break
        for row in self.db.execute("SELECT id,state FROM jobs WHERE state IN ('RECEIVED','PREPARING','READY') ORDER BY created").fetchall():
            if self.stopping():
                return
            if row["state"] != "READY":
                self.prepare(row["id"])
            self.launch(row["id"])
        self.gc()
        # Reported tick time is work only, not an idle claim's wait.
        self.tick_seconds = time.monotonic() - started - self.waited

    def gc(self):
        for row in self.db.execute("SELECT * FROM jobs WHERE state='TERMINAL' AND acknowledged=1 AND completed<?", (time.time() - RETENTION,)).fetchall():
            with transaction(self.db):
                self.db.execute("DELETE FROM events WHERE job_id=?", (row["id"],))
                self.db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        referenced_jobs = {row[0] for row in self.db.execute("SELECT id FROM jobs")}
        for path in (self.root / "jobs").iterdir():
            if ID.fullmatch(path.name) and path.name not in referenced_jobs and not path.is_symlink():
                self.discard(path)
        for path in (self.root / "outbox").iterdir():
            if path.is_symlink():
                continue
            if path.name.startswith((".write-", ".seal-")):
                if path.is_file() and path.stat().st_mtime < time.time() - RETENTION:
                    path.unlink()
            elif ID.fullmatch(path.name) and path.name not in referenced_jobs:
                path.unlink()
        snapshots = {row[0] for row in self.db.execute("SELECT snapshot FROM jobs WHERE state!='TERMINAL'")}
        for path in (self.root / "snapshots").iterdir():
            if path.name not in snapshots:
                path.unlink()
        # Fallback for supervisors that died before scrubbing, and for jobs that never ran.
        for row in self.db.execute("SELECT id FROM jobs WHERE state='TERMINAL'").fetchall():
            folder = self.root / "jobs" / row[0]
            if any((folder / name).exists() for name in ("workspace", "tmp", "artifacts")):
                self.scrub(row[0])
        self.sweep()

    def health(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='health'").fetchone()
        return json.loads(row[0]) if row else []

    def store_health(self, batches):
        if batches:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('health',?)", (json.dumps(batches, sort_keys=True),))
        else:
            self.db.execute("DELETE FROM settings WHERE key='health'")

    def failure(self, reason):
        """Count a failed tick by fixed reason until a heartbeat delivers the counts."""
        with transaction(self.db):
            health = self.health()
            if not health or health[-1]["sent"]:
                health.append({"id": opaque(), "counts": {}, "sent": False})
            counts = health[-1]["counts"]
            counts[reason] = min(1000000, counts.get(reason, 0) + 1)
            self.store_health(health[-16:])

    def crashed(self):
        """Count a worker crash once; its traceback stays in the private worker.failure."""
        path = self.root / "worker.failure"
        if not path.exists():
            return
        seen = self.db.execute("SELECT value FROM settings WHERE key='crash_seen'").fetchone()
        mtime = path.stat().st_mtime
        if seen is None or float(seen[0]) < mtime:
            self.failure("WORKER_CRASH")
            with transaction(self.db):
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('crash_seen',?)", (str(mtime),))

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
    local.crashed()
    local.recover()
    with transaction(local.db):
        # Workspaces are extracted without fsync; after a crash, extract them again.
        local.db.execute("UPDATE jobs SET state='RECEIVED' WHERE state IN ('PREPARING','READY')")
    local.idle_wait = CLAIM_WAIT
    delay = 0.25
    while not stopping:
        try:
            local.tick()
            delay = 0.25
        except Exception as error:
            # Any failure only delays the next tick; the worker itself never stops.
            delay = min(30, delay * 2)
            reason = error.reason if isinstance(error, Refusal) and CODE.fullmatch(error.reason) else "OS_ERROR" if isinstance(error, OSError) else "INTERNAL"
            with contextlib.suppress(Exception):
                local.failure(reason)
                # The latest traceback stays private on the Mac for explicit inspection.
                import traceback
                atomic(local.root / "tick.failure", traceback.format_exc().encode()[:MAX_LOG])
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
            logs[name] = [os.fdopen(fd, "wb"), 0, bytearray(), 0]
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
                log = logs[key.data]
                kept = chunk[:max(0, LOG_HEAD - log[1])]
                log[0].write(kept)
                log[1] += len(kept)
                if len(kept) != len(chunk):
                    # Past the head, keep a rolling tail: summaries and failures print last.
                    log[2] += chunk[len(kept):]
                    if len(log[2]) > LOG_TAIL:
                        log[3] += len(log[2]) - LOG_TAIL
                        del log[2][:-LOG_TAIL]
            if killing:
                if drain_until is None:
                    drain_until = time.monotonic() + 1
                if not any(key.data in {"stdout", "stderr"} for key in selector.get_map().values()) or time.monotonic() >= drain_until:
                    break
        for log, _, tail, dropped in logs.values():
            if dropped:
                truncated = True
                log.write(b"\n... %d bytes omitted ...\n" % dropped)
            log.write(tail)
            log.flush()
            os.fsync(log.fileno())
            log.close()
        code = 125 if outcome == "cancelled" else 124 if outcome == "timeout" else command_code if command_code is not None else 70
        process.wait()
        if code < 0:
            code = min(255, 128 - code)
        local.terminal(job, outcome, code, reason, (folder / "stdout").read_bytes(), (folder / "stderr").read_bytes(), truncated)
        local.scrub(job)
        local.sweep()
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
