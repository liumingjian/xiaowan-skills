import base64
import hmac
import json
from pathlib import Path
import secrets
import shutil
import time

from .common import MAX_RECONCILE, RETENTION, Refusal, atomic, connect, digest, encode, event, immutable, opaque, private_dir, transaction, valid_id
from .export import Publisher
from .snapshot import freeze, safe_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request TEXT UNIQUE NOT NULL, spec_digest TEXT NOT NULL, workspace TEXT NOT NULL, command TEXT NOT NULL, cwd TEXT NOT NULL, timeout INTEGER NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('QUEUED','CLAIMED','RESULT_STORED')), claim TEXT UNIQUE, cancel INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, completed REAL, result_digest TEXT, ack INTEGER NOT NULL DEFAULT 0, artifact_ack INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS claims(request TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id));
CREATE TABLE IF NOT EXISTS workspaces(source TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS events(job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE, sequence INTEGER, value TEXT NOT NULL, PRIMARY KEY(job_id,sequence));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Server:
    def __init__(self, root):
        self.root = private_dir(root)
        self.db = connect(root, SCHEMA)
        self.publisher = Publisher((str(Path.home()), str(root)))
        private_dir(self.root / "blobs")

    def provision(self):
        path = self.root / "worker.token"
        with transaction(self.db):
            if not path.exists():
                atomic(path, secrets.token_urlsafe(48).encode())
        return path.read_text()

    def authenticate(self, token):
        path = self.root / "worker.token"
        if not isinstance(token, str) or not path.exists() or not hmac.compare_digest(token, path.read_text()):
            raise Refusal("AUTHORIZATION_REQUIRED", 77)

    def submit(self, command, source, cwd, timeout, request, with_git=False):
        valid_id(request)
        if not isinstance(command, str) or not command or len(command.encode()) > 65536 or not 1 <= timeout <= 86400:
            raise Refusal()
        if cwd != ".":
            safe_name(cwd)
        workspace_source = str(Path(source).resolve()) if source is not None else "no-sync"
        spec = digest(encode([command, workspace_source, cwd, timeout, bool(with_git)]))
        old = self.db.execute("SELECT * FROM jobs WHERE request=?", (request,)).fetchone()
        if old:
            if old["spec_digest"] != spec:
                raise Refusal("REQUEST_CONFLICT")
            return self.status(old["id"])
        blob = freeze(source, with_git) if source is not None else freeze_empty()
        snapshot = digest(blob)
        with transaction(self.db):
            old = self.db.execute("SELECT * FROM jobs WHERE request=?", (request,)).fetchone()
            if old:
                if old["spec_digest"] != spec:
                    raise Refusal("REQUEST_CONFLICT")
                return self.status(old["id"])
            immutable(self.root / "blobs" / snapshot, blob)
            workspace = self.db.execute("SELECT id FROM workspaces WHERE source=?", (workspace_source,)).fetchone()
            if not workspace:
                workspace = (opaque(),)
                self.db.execute("INSERT INTO workspaces VALUES(?,?)", (workspace_source, workspace[0]))
            job = opaque()
            self.db.execute("INSERT INTO jobs(id,request,spec_digest,workspace,command,cwd,timeout,snapshot,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)", (job, request, spec, workspace[0], command, cwd, timeout, snapshot, "QUEUED", time.time()))
            event(self.db, job, "QUEUED", "ACCEPTED")
        return self.status(job)

    def job(self, job):
        valid_id(job)
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        if not row:
            raise Refusal("JOB_NOT_FOUND", 66)
        return row

    def bundle(self, row):
        path = self.root / "blobs" / row["result_digest"]
        data = path.read_bytes()
        if digest(data) != row["result_digest"]:
            raise Refusal("RESULT_INVALID")
        return self.publisher.validate_bundle(json.loads(data))

    def status(self, job):
        row = self.job(job)
        return self.publisher.receipt(row, self.bundle(row) if row["result_digest"] else None)

    def channel(self):
        contact = self.db.execute("SELECT value FROM settings WHERE key='last_contact'").fetchone()
        age = round(max(0, time.time() - float(contact[0])), 3) if contact else None
        reserved = self.db.execute("SELECT COUNT(*) FROM jobs WHERE state='CLAIMED'").fetchone()[0]
        unknown = self.db.execute("SELECT COUNT(*) FROM jobs WHERE state='CLAIMED' AND result_digest IS NOT NULL").fetchone()[0]
        worker_state = self.db.execute("SELECT value FROM settings WHERE key='worker_state'").fetchone()
        state = "AUTHORIZATION_REQUIRED" if not (self.root / "worker.token").exists() else "OFFLINE" if age is None or age > 180 else "LOW_SPACE" if worker_state and worker_state[0] == "LOW_SPACE" else "UNCERTAIN" if unknown else "READY"
        return {"state": state, "last_contact_age_seconds": age, "reserved": reserved}

    def queue(self):
        return [self.status(row[0]) for row in self.db.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT 100")]

    def trace(self, job, after=0):
        self.job(job)
        return self.publisher.events([json.loads(row[0]) for row in self.db.execute("SELECT value FROM events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT 1000", (job, after))])

    def claim(self, request):
        valid_id(request)
        with transaction(self.db):
            previous = self.db.execute("SELECT job_id FROM claims WHERE request=?", (request,)).fetchone()
            if previous:
                row = self.job(previous[0]) if previous[0] else None
            else:
                row = self.db.execute("SELECT * FROM jobs AS candidate WHERE state='QUEUED' AND cancel=0 AND NOT EXISTS(SELECT 1 FROM jobs AS active WHERE active.workspace=candidate.workspace AND active.state='CLAIMED') ORDER BY created LIMIT 1").fetchone()
                if row:
                    claim = opaque()
                    self.db.execute("UPDATE jobs SET state='CLAIMED',claim=? WHERE id=?", (claim, row["id"]))
                    event(self.db, row["id"], "CLAIMED", "CLAIMED")
                    row = self.job(row["id"])
                self.db.execute("DELETE FROM claims WHERE job_id IS NULL")
                self.db.execute("INSERT INTO claims VALUES(?,?)", (request, row["id"] if row else None))
        if not row:
            return {"job": None}
        data = (self.root / "blobs" / row["snapshot"]).read_bytes()
        return {"job": {key: row[key] for key in ("id", "workspace", "command", "cwd", "timeout", "claim", "cancel")}, "snapshot": base64.b64encode(data).decode(), "snapshot_digest": row["snapshot"]}

    def cancel(self, job):
        with transaction(self.db):
            row = self.job(job)
            if row["state"] == "RESULT_STORED":
                return self.status(job)
            if not row["cancel"]:
                self.db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job,))
                event(self.db, job, "CANCEL_REQUESTED", "CANCELLED")
            if row["state"] == "QUEUED":
                claim = opaque()
                self.db.execute("UPDATE jobs SET claim=? WHERE id=?", (claim, job))
                bundle = self.publisher.bundle(job, claim, "cancelled", 125, "CANCELLED")
                self._store(bundle)
        return self.status(job)

    def _store(self, bundle):
        self.publisher.validate_bundle(bundle)
        row = self.job(bundle["job_id"])
        data = encode(bundle)
        value = digest(data)
        if row["claim"] != bundle["claim_id"]:
            raise Refusal("CLAIM_MISMATCH")
        if row["result_digest"]:
            if row["result_digest"] != value:
                raise Refusal("RESULT_CONFLICT")
            return {"job_id": row["id"], "digest": value}
        if row["state"] not in {"CLAIMED", "QUEUED"}:
            raise Refusal("RESULT_CONFLICT")
        immutable(self.root / "blobs" / value, data)
        # Unknown outcomes retain the workspace reservation until explicitly resolved.
        state = "CLAIMED" if bundle["outcome"] == "unknown" else "RESULT_STORED"
        self.db.execute("UPDATE jobs SET state=?,result_digest=?,completed=? WHERE id=?", (state, value, time.time(), row["id"]))
        event(self.db, row["id"], "RESULT_STORED", "EXECUTION_UNKNOWN" if state == "CLAIMED" else "RESULT_STORED", bundle["outcome"])
        return {"job_id": row["id"], "digest": value}

    def report(self, bundle, expected):
        if digest(encode(bundle)) != expected:
            raise Refusal("RESULT_INVALID")
        with transaction(self.db):
            return self._store(bundle)

    def ack(self, job, value, artifacts=False):
        with transaction(self.db):
            row = self.job(job)
            if row["result_digest"] != value:
                raise Refusal("ACK_MISMATCH")
            self.db.execute("UPDATE jobs SET " + ("artifact_ack" if artifacts else "ack") + "=1 WHERE id=?", (job,))
        return {"job_id": job, "acknowledged": True}

    def gc(self, apply=False):
        rows = self.db.execute("SELECT id FROM jobs WHERE state='RESULT_STORED' AND ack=1 AND artifact_ack=1 AND completed<?", (time.time() - RETENTION,)).fetchall()
        if apply:
            with transaction(self.db):
                for row in rows:
                    self.db.execute("DELETE FROM settings WHERE key LIKE ?", ("event:" + row[0] + ":%",))
                    self.db.execute("DELETE FROM claims WHERE job_id=?", (row[0],))
                    self.db.execute("DELETE FROM jobs WHERE id=?", (row[0],))
            with transaction(self.db):
                referenced = {row[0] for row in self.db.execute("SELECT snapshot FROM jobs UNION SELECT result_digest FROM jobs WHERE result_digest IS NOT NULL")}
                for path in (self.root / "blobs").iterdir():
                    if path.name not in referenced:
                        path.unlink()
        return {"eligible_jobs": len(rows), "applied": bool(apply)}

    def rpc(self, request):
        self.authenticate(request.get("token"))
        with transaction(self.db):
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('last_contact',?)", (str(time.time()),))
        action = request.get("action")
        if action == "heartbeat":
            state = request.get("state")
            if state not in {"READY", "LOW_SPACE"}:
                raise Refusal()
            with transaction(self.db):
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('worker_state',?)", (state,))
            return {"connected": True}
        if action == "claim":
            return self.claim(request.get("request_id"))
        if action == "reconcile":
            jobs = request.get("jobs")
            if not isinstance(jobs, list) or len(jobs) > MAX_RECONCILE:
                raise Refusal()
            response = []
            with transaction(self.db):
                for item in jobs:
                    row = self.job(item["job_id"])
                    if row["claim"] != valid_id(item["claim_id"]):
                        raise Refusal("CLAIM_MISMATCH")
                    for value in self.publisher.events(item.get("events", [])):
                        if value["job_id"] != row["id"]:
                            raise Refusal()
                        # Mac events have a separate origin sequence to deduplicate retries.
                        key = "event:" + row["id"] + ":" + str(value["sequence"])
                        prior = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                        if not prior:
                            rebased = event(self.db, row["id"], value["phase"], value["reason"], value["outcome"], value["attempt"])
                            rebased["duration"] = value["duration"]
                            self.db.execute("UPDATE events SET value=? WHERE job_id=? AND sequence=?", (encode(rebased).decode(), row["id"], rebased["sequence"]))
                            self.db.execute("INSERT INTO settings VALUES(?,?)", (key, digest(encode(value))))
                        elif prior[0] != digest(encode(value)):
                            raise Refusal("EVENT_CONFLICT")
                    response.append({"job_id": row["id"], "cancel": bool(row["cancel"])})
            return {"jobs": response}
        if action == "report":
            return self.report(request.get("bundle"), request.get("digest"))
        raise Refusal()


def freeze_empty():
    import io
    import tarfile
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w"):
        pass
    return out.getvalue()
