import base64
import contextlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import shutil
import time

from .common import CATEGORIES, CODE, HEALTH_WINDOW, HISTORY, MAX_NOTE, MAX_RECONCILE, RETENTION, VERSION, Refusal, atomic, connect, digest, encode, event, immutable, opaque, private_dir, runtime_version, transaction, valid_id
from .export import Publisher
from .snapshot import freeze, safe_name

GC_INTERVAL = 3600
# A claimed job the worker has stopped reporting is released after this long.
LEASE = 600
# An idle worker's claim waits up to this long for a job instead of asking again every tick.
CLAIM_WAIT = 25
CLAIM_POLL = 0.5
# Contact is recorded at most this often; the channel goes OFFLINE only after minutes of silence.
CONTACT_EVERY = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request TEXT UNIQUE NOT NULL, spec_digest TEXT NOT NULL, workspace TEXT NOT NULL, command TEXT NOT NULL, cwd TEXT NOT NULL, timeout INTEGER NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('QUEUED','CLAIMED','RESULT_STORED')), claim TEXT UNIQUE, cancel INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, completed REAL, result_digest TEXT, ack INTEGER NOT NULL DEFAULT 0, artifact_ack INTEGER NOT NULL DEFAULT 0, claimed REAL, label TEXT);
CREATE TABLE IF NOT EXISTS claims(request TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id));
CREATE TABLE IF NOT EXISTS workspaces(source TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS events(job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE, sequence INTEGER, value TEXT NOT NULL, PRIMARY KEY(job_id,sequence));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS summaries(job_id TEXT PRIMARY KEY, created REAL NOT NULL, fingerprint TEXT NOT NULL, timeout INTEGER NOT NULL, channel TEXT NOT NULL, claimed REAL, completed REAL, outcome TEXT, exit_code INTEGER, reason TEXT, log_truncated INTEGER, artifacts INTEGER, start_s REAL, run_s REAL, cancelled INTEGER NOT NULL DEFAULT 0, status_calls INTEGER NOT NULL DEFAULT 0, wait_calls INTEGER NOT NULL DEFAULT 0, trace_calls INTEGER NOT NULL DEFAULT 0, wait_timeouts INTEGER NOT NULL DEFAULT 0, read REAL, fetched REAL);
CREATE TABLE IF NOT EXISTS health(batch TEXT NOT NULL, at REAL NOT NULL, reason TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(batch,reason));
CREATE TABLE IF NOT EXISTS cli_errors(at REAL NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, at REAL NOT NULL, job_id TEXT, category TEXT NOT NULL, note TEXT NOT NULL);
"""
# Default `rexec status` lists active jobs, unread results from the last day, and this many recent others.
RECENT = 5
UNREAD_WINDOW = 86400
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/ -]{0,63}")
# Per-job usage counters that a CLI call can bump; read and fetched record the first time.
USAGE = {"status": "status_calls", "wait": "wait_calls", "trace": "trace_calls", "wait_timeout": "wait_timeouts"}


class Server:
    def __init__(self, root):
        self.root = private_dir(root)
        self.db = connect(root, SCHEMA)
        self.publisher = Publisher((str(Path.home()), str(root)))
        private_dir(self.root / "blobs")
        self.migrate()

    def migrate(self):
        for column, kind in (("claimed", "REAL"), ("label", "TEXT")):
            if column not in {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}:
                with transaction(self.db):
                    if column not in {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}:
                        self.db.execute("ALTER TABLE jobs ADD COLUMN " + column + " " + kind)
        if not self.db.execute("SELECT 1 FROM settings WHERE key='summaries_backfilled'").fetchone():
            # Jobs from before summaries existed keep their outcome; claim times were not recorded.
            with transaction(self.db):
                for row in self.db.execute("SELECT * FROM jobs WHERE id NOT IN (SELECT job_id FROM summaries)").fetchall():
                    self.summarize(row, "UNRECORDED")
                    if row["result_digest"]:
                        with contextlib.suppress(Exception):
                            self.summarize_result(row["id"], self.bundle(row), row["completed"])
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('summaries_backfilled','1')")
        if self.db.execute("SELECT 1 FROM jobs WHERE state='CLAIMED' AND result_digest IS NOT NULL LIMIT 1").fetchone():
            # Earlier versions kept unknown outcomes CLAIMED, which blocked their workspace forever.
            with transaction(self.db):
                self.db.execute("UPDATE jobs SET state='RESULT_STORED' WHERE state='CLAIMED' AND result_digest IS NOT NULL")

    def fingerprint(self, command):
        """Group repeats of one command without exporting it; the key never leaves the server."""
        path = self.root / "fingerprint.key"
        if not path.exists():
            with contextlib.suppress(Refusal):
                immutable(path, secrets.token_hex(32).encode())
        return hmac.new(path.read_bytes(), command.encode(), "sha256").hexdigest()[:12]

    def summarize(self, row, channel):
        self.db.execute("INSERT OR IGNORE INTO summaries(job_id,created,fingerprint,timeout,channel,cancelled) VALUES(?,?,?,?,?,?)", (row["id"], row["created"], self.fingerprint(row["command"]), row["timeout"], channel, row["cancel"]))

    def summarize_result(self, job, bundle, completed):
        timing = bundle.get("timing") or {}
        self.db.execute("UPDATE summaries SET completed=?,outcome=?,exit_code=?,reason=?,log_truncated=?,artifacts=?,start_s=?,run_s=? WHERE job_id=?", (completed, bundle["outcome"], bundle["exit_code"], bundle["reason"], int(bundle["log_truncated"]), len(bundle["artifacts"]), timing.get("start_s"), timing.get("run_s"), job))

    def note(self, job, kind):
        """Count CLI usage per job. Observation never changes the command's result."""
        with contextlib.suppress(Exception):
            with transaction(self.db):
                if kind in USAGE:
                    self.db.execute("UPDATE summaries SET " + USAGE[kind] + "=" + USAGE[kind] + "+1 WHERE job_id=?", (job,))
                elif kind in {"read", "fetched"}:
                    self.db.execute("UPDATE summaries SET " + kind + "=COALESCE(" + kind + ",?) WHERE job_id=?", (time.time(), job))

    def record_error(self, action, reason):
        with contextlib.suppress(Exception):
            if CODE.fullmatch(reason) and re.fullmatch(r"[a-z_]{1,16}", action):
                with transaction(self.db):
                    self.db.execute("INSERT INTO cli_errors VALUES(?,?,?)", (time.time(), action, reason))

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

    def submit(self, command, source, cwd, timeout, request, with_git=False, label=None, ignored=False):
        valid_id(request)
        if not isinstance(command, str) or not command or len(command.encode()) > 65536 or not 1 <= timeout <= 86400:
            raise Refusal()
        if label is not None and (not isinstance(label, str) or not LABEL.fullmatch(label) or self.publisher.sanitize(label) != label):
            raise Refusal("LABEL_INVALID")
        if cwd != ".":
            try:
                safe_name(cwd)
            except Refusal:
                raise Refusal("CWD_INVALID")
            # Checked here so a typo fails now instead of after the transfer to the Mac.
            if source is None or not (Path(source) / cwd).is_dir():
                raise Refusal("CWD_NOT_FOUND")
        workspace_source = str(Path(source).resolve()) if source is not None else "no-sync"
        # Older specs omit the flag, so retries of their requests keep matching.
        spec = digest(encode([command, workspace_source, cwd, timeout, bool(with_git)] + ([True] if ignored else [])))
        old = self.db.execute("SELECT * FROM jobs WHERE request=?", (request,)).fetchone()
        if old:
            if old["spec_digest"] != spec:
                raise Refusal("REQUEST_CONFLICT")
            return self.status(old["id"])
        report = {}
        blob = freeze(source, with_git, ignored, report, cwd) if source is not None else freeze_empty()
        snapshot = digest(blob)
        channel = self.channel()["state"]
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
            self.db.execute("INSERT INTO jobs(id,request,spec_digest,workspace,command,cwd,timeout,snapshot,state,created,label) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (job, request, spec, workspace[0], command, cwd, timeout, snapshot, "QUEUED", time.time(), label))
            event(self.db, job, "QUEUED", "ACCEPTED")
            self.summarize(self.job(job), channel)
        result = self.status(job)
        if report:
            result["snapshot"] = report
        return result

    def feedback(self, job, category, note):
        """Store an agent's note; it is reported in aggregate and never joins the trace."""
        if job is not None:
            self.job(job)
        if category not in CATEGORIES:
            raise Refusal("FEEDBACK_CATEGORY")
        note = self.publisher.sanitize(note or "").strip()
        if len(note) > MAX_NOTE:
            raise Refusal("FEEDBACK_TOO_LONG")
        with transaction(self.db):
            cursor = self.db.execute("INSERT INTO feedback(at,job_id,category,note) VALUES(?,?,?,?)", (time.time(), job, category, note))
        return {"feedback_id": cursor.lastrowid, "job_id": job, "category": category, "recorded": True}

    def overview(self, since):
        """Aggregate the history for iteration: what failed, where time went, how agents used the CLI."""
        now = time.time()
        start = now - since
        rows = self.db.execute("SELECT * FROM summaries WHERE created>=? ORDER BY created", (start,)).fetchall()
        outcomes = {}
        phases = {"queued_s": [], "start_s": [], "run_s": [], "report_s": []}
        for row in rows:
            key = (row["outcome"] or "pending") + ":" + (row["reason"] or "PENDING")
            outcomes[key] = outcomes.get(key, 0) + 1
            if row["claimed"] is not None:
                phases["queued_s"].append(row["claimed"] - row["created"])
            for name in ("start_s", "run_s"):
                if row[name] is not None:
                    phases[name].append(row[name])
            if None not in (row["claimed"], row["completed"], row["start_s"], row["run_s"]):
                phases["report_s"].append(row["completed"] - row["claimed"] - row["start_s"] - row["run_s"])
        failed = [row for row in rows if row["outcome"] is not None and (row["outcome"] != "completed" or row["exit_code"] != 0)]
        failed_ids = {row["job_id"] for row in failed}
        groups = {}
        for row in rows:
            group = groups.setdefault(row["fingerprint"], {"fingerprint": row["fingerprint"], "runs": 0, "failures": 0, "last_reason": None})
            group["runs"] += 1
            if row["job_id"] in failed_ids:
                group["failures"] += 1
                group["last_reason"] = row["reason"]
        settled = [row for row in rows if row["completed"] is not None and row["completed"] < now - 86400]
        feedback = self.db.execute("SELECT * FROM feedback WHERE at>=? ORDER BY at DESC", (start,)).fetchall()
        categories = {}
        for row in feedback:
            categories[row["category"]] = categories.get(row["category"], 0) + 1
        return {
            "window": {"since_seconds": since, "jobs": len(rows), "failed": len(failed)},
            "outcomes": dict(sorted(outcomes.items())),
            "timing": {name: percentiles(values) for name, values in phases.items()},
            "health": {row[0]: row[1] for row in self.db.execute("SELECT reason,SUM(count) FROM health WHERE at>=? GROUP BY reason ORDER BY reason", (start,))},
            "usage": {
                "submitted_not_ready": sum(row["channel"] not in {"READY", "UNRECORDED"} for row in rows),
                "unread_results": sum(row["read"] is None for row in settled),
                "unfetched_artifacts": sum(bool(row["artifacts"]) and row["fetched"] is None for row in settled),
                "wait_timeouts": sum(row["wait_timeouts"] for row in rows),
                "calls": {name: {"total": sum(row[column] for row in rows), "max_per_job": max((row[column] for row in rows), default=0)} for name, column in (("status", "status_calls"), ("wait", "wait_calls"), ("trace", "trace_calls"))},
                "cli_errors": {row[0] + ":" + row[1]: row[2] for row in self.db.execute("SELECT action,reason,COUNT(*) FROM cli_errors WHERE at>=? GROUP BY action,reason ORDER BY COUNT(*) DESC, action, reason", (start,))},
            },
            "failing_commands": sorted((group for group in groups.values() if group["failures"]), key=lambda group: (-group["failures"], group["fingerprint"]))[:10],
            "feedback": {"categories": dict(sorted(categories.items())), "recent": [{"age_seconds": round(now - row["at"]), "job_id": row["job_id"], "category": row["category"], "note": row["note"]} for row in feedback[:20]]},
        }

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
        since = time.time() - HEALTH_WINDOW
        failures = {row[0]: row[1] for row in self.db.execute("SELECT reason,SUM(count) FROM health WHERE at>=? GROUP BY reason ORDER BY reason", (since,))}
        last = self.db.execute("SELECT reason,at FROM health ORDER BY at DESC LIMIT 1").fetchone()
        worker_state = self.db.execute("SELECT value FROM settings WHERE key='worker_state'").fetchone()
        timing = self.db.execute("SELECT value FROM settings WHERE key='worker_timing'").fetchone()
        state = "AUTHORIZATION_REQUIRED" if not (self.root / "worker.token").exists() else "OFFLINE" if age is None or age > 180 else "LOW_SPACE" if worker_state and worker_state[0] == "LOW_SPACE" else "READY"
        result = {"state": state, "last_contact_age_seconds": age, "reserved": reserved, "worker_timing": json.loads(timing[0]) if timing else None,
                  "recent_failures": failures, "last_failure": {"reason": last[0], "age_seconds": round(max(0, time.time() - last[1]), 3)} if last else None}
        worker = self.db.execute("SELECT value FROM settings WHERE key='worker_runtime'").fetchone()
        if worker and worker[0] != runtime_version():
            # The Mac runs a different release than this server; rerun the Mac update line.
            result["runtime_skew"] = {"server": runtime_version(), "worker": worker[0]}
        return result

    def find(self, request):
        row = self.db.execute("SELECT id FROM jobs WHERE request=?", (request,)).fetchone()
        return row[0] if row else None

    def queue(self, everything=False):
        """One line per job, newest first. Full output stays behind `status JOB`.

        By default only jobs that need attention are listed: queued or running jobs,
        results nobody has read, and the few most recent others."""
        now = time.time()
        rows = self.db.execute("SELECT jobs.id,jobs.label,jobs.state,jobs.created,jobs.ack,jobs.cancel,summaries.outcome,summaries.exit_code,summaries.reason FROM jobs LEFT JOIN summaries ON summaries.job_id=jobs.id ORDER BY jobs.created DESC LIMIT 100").fetchall()
        listed = []
        recent = 0
        for row in rows:
            pending = row["state"] != "RESULT_STORED"
            unread = not pending and not row["ack"]
            if not (everything or pending or (unread and now - row["created"] < UNREAD_WINDOW)):
                recent += 1
                if recent > RECENT:
                    continue
            item = {"job_id": row["id"], "state": row["state"], "age_s": round(max(0.0, now - row["created"]), 1)}
            if row["label"]:
                item["label"] = row["label"]
            if row["cancel"]:
                item["cancel_requested"] = True
            if not pending:
                item.update({"outcome": row["outcome"], "exit_code": row["exit_code"], "reason": row["reason"], "unread": unread})
            listed.append(item)
        return {"jobs": listed, "hidden": len(rows) - len(listed)}

    def trace(self, job, after=0):
        self.job(job)
        return self.publisher.events([json.loads(row[0]) for row in self.db.execute("SELECT value FROM events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT 1000", (job, after))])

    def claim(self, request, wait=0, held=()):
        """Claim the oldest runnable job. An idle worker may wait up to `wait` seconds for one.

        `cancel` tells the worker that a job in `held` (its jobs not yet told to cancel) was
        cancelled, so it reconciles at once; that also ends a wait."""
        valid_id(request)
        deadline = time.monotonic() + wait
        checked = False
        while True:
            final = time.monotonic() >= deadline
            # Polling stays read-only until there is something to take.
            if not checked or final or self.db.execute("SELECT 1 FROM jobs WHERE state='QUEUED' AND cancel=0 LIMIT 1").fetchone():
                row, decided = self.take(request, final)
                if decided:
                    break
            checked = True
            if self.unheard(held):
                row = None
                break
            time.sleep(max(0, min(CLAIM_POLL, deadline - time.monotonic())))
        cancel = self.unheard(held)
        if not row:
            return {"job": None, "cancel": cancel}
        data = (self.root / "blobs" / row["snapshot"]).read_bytes()
        return {"job": {key: row[key] for key in ("id", "workspace", "command", "cwd", "timeout", "claim", "cancel")}, "snapshot": base64.b64encode(data).decode(), "snapshot_digest": row["snapshot"], "cancel": cancel}

    def take(self, request, final):
        """Return (job row or None, whether this request is settled)."""
        with transaction(self.db):
            previous = self.db.execute("SELECT job_id FROM claims WHERE request=?", (request,)).fetchone()
            if previous:
                # A retried claim gets its job back only while that claim still holds it.
                row = self.db.execute("SELECT * FROM jobs WHERE id=? AND state='CLAIMED' AND result_digest IS NULL", (previous[0],)).fetchone() if previous[0] else None
                return row, True
            row = self.db.execute("SELECT * FROM jobs AS candidate WHERE state='QUEUED' AND cancel=0 AND NOT EXISTS(SELECT 1 FROM jobs AS active WHERE active.workspace=candidate.workspace AND active.state='CLAIMED') ORDER BY created LIMIT 1").fetchone()
            if row:
                claim = opaque()
                now = time.time()
                self.db.execute("UPDATE jobs SET state='CLAIMED',claim=?,claimed=? WHERE id=?", (claim, now, row["id"]))
                self.db.execute("UPDATE summaries SET claimed=? WHERE job_id=?", (now, row["id"]))
                event(self.db, row["id"], "CLAIMED", "CLAIMED")
                row = self.job(row["id"])
            elif not final:
                return None, False
            self.db.execute("DELETE FROM claims WHERE job_id IS NULL")
            self.db.execute("INSERT INTO claims VALUES(?,?)", (request, row["id"] if row else None))
            return row, True

    def unheard(self, held):
        return any(row[0] in held for row in self.db.execute("SELECT id FROM jobs WHERE state='CLAIMED' AND cancel=1"))

    def cancel(self, job):
        with transaction(self.db):
            row = self.job(job)
            if row["state"] == "RESULT_STORED":
                return self.status(job)
            if not row["cancel"]:
                self.db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job,))
                self.db.execute("UPDATE summaries SET cancelled=1 WHERE job_id=?", (job,))
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
        # An unknown outcome is terminal too. Its process group is gone (the gate kills it when
        # its supervisor dies) and every job extracts into its own directory, so holding the
        # workspace would protect nothing; the command is still never replayed.
        completed = time.time()
        self.db.execute("UPDATE jobs SET state='RESULT_STORED',result_digest=?,completed=? WHERE id=?", (value, completed, row["id"]))
        self.summarize_result(row["id"], bundle, completed)
        event(self.db, row["id"], "RESULT_STORED", bundle["reason"] if bundle["outcome"] == "unknown" else "RESULT_STORED", bundle["outcome"])
        return {"job_id": row["id"], "digest": value}

    def report(self, bundle, expected):
        if digest(encode(bundle)) != expected:
            raise Refusal("RESULT_INVALID")
        with transaction(self.db):
            return self._store(bundle)

    def settle(self, job, outcome, code, reason):
        """Store a server-decided result for a claimed job the worker cannot finish."""
        row = self.job(job)
        if row["state"] != "CLAIMED" or row["result_digest"]:
            return
        self._store(self.publisher.bundle(job, row["claim"], outcome, code, reason))

    def expire(self, active):
        """Release claims missing from the worker's complete list of its own jobs.

        A job claimed in the last LEASE seconds may still be in flight to the worker.
        Anything older that the worker no longer holds (state lost, claim never
        delivered) would otherwise block its workspace forever."""
        rows = self.db.execute("SELECT id FROM jobs WHERE state='CLAIMED' AND result_digest IS NULL AND claimed<?", (time.time() - LEASE,)).fetchall()
        for row in rows:
            if row[0] not in active:
                self.settle(row[0], "unknown", 70, "CLAIM_LOST")

    def reconcile_one(self, item):
        row = self.job(item["job_id"])
        if row["claim"] != valid_id(item.get("claim_id")):
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
        result = {"job_id": row["id"], "cancel": bool(row["cancel"])}
        report = item.get("report")
        if report is not None:
            # A finished job's result rides along, saving the worker a second round trip. Its
            # failure is separate, so the events above still land.
            if not isinstance(report, dict) or set(report) != {"bundle", "digest"}:
                raise Refusal()
            self.db.execute("SAVEPOINT report")
            try:
                if digest(encode(report["bundle"])) != report["digest"]:
                    raise Refusal("RESULT_INVALID")
                result["ack"] = self._store(report["bundle"])
                self.db.execute("RELEASE report")
            except Refusal as error:
                self.db.execute("ROLLBACK TO report")
                self.db.execute("RELEASE report")
                result["report_error"] = error.reason
        return result

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
                # History outlives job records so trends survive the seven-day cleanup.
                for table, column in (("summaries", "created"), ("health", "at"), ("cli_errors", "at"), ("feedback", "at")):
                    self.db.execute("DELETE FROM " + table + " WHERE " + column + "<?", (time.time() - HISTORY,))
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
        contact = self.db.execute("SELECT value FROM settings WHERE key='last_contact'").fetchone()
        if not contact or time.time() - float(contact[0]) >= CONTACT_EVERY:
            with transaction(self.db):
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('last_contact',?)", (str(time.time()),))
        action = request.get("action")
        if action == "heartbeat":
            state = request.get("state")
            if state not in {"READY", "LOW_SPACE"}:
                raise Refusal()
            timing = request.get("timing")
            if timing is not None and (not isinstance(timing, dict) or set(timing) != {"tick", "rpc"} or any(type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 86400 for v in timing.values())):
                raise Refusal()
            health = request.get("health") or []
            if not isinstance(health, list) or len(health) > 16:
                raise Refusal()
            runtime = request.get("runtime")
            if runtime is not None and (not isinstance(runtime, str) or not VERSION.fullmatch(runtime)):
                raise Refusal()
            # Workers send their full job list only when it fits; without it nothing expires.
            active = request.get("active")
            if active is not None:
                if not isinstance(active, list) or len(active) > MAX_RECONCILE:
                    raise Refusal()
                active = {valid_id(item) for item in active}
            for batch in health:
                if not isinstance(batch, dict) or set(batch) != {"id", "counts"} or not isinstance(batch["counts"], dict) or len(batch["counts"]) > 32:
                    raise Refusal()
                valid_id(batch["id"])
                if any(not isinstance(k, str) or not CODE.fullmatch(k) or type(v) is not int or not 1 <= v <= 1000000 for k, v in batch["counts"].items()):
                    raise Refusal()
            with transaction(self.db):
                for batch in health:
                    for reason, count in sorted(batch["counts"].items()):
                        self.db.execute("INSERT OR IGNORE INTO health VALUES(?,?,?,?)", (batch["id"], time.time(), reason, count))
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('worker_state',?)", (state,))
                if timing is not None:
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES('worker_timing',?)", (json.dumps(timing),))
                if runtime is not None:
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES('worker_runtime',?)", (runtime,))
                if active is not None:
                    self.expire(active)
                last_gc = self.db.execute("SELECT value FROM settings WHERE key='last_gc'").fetchone()
                due = not last_gc or time.time() - float(last_gc[0]) >= GC_INTERVAL
                if due:
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES('last_gc',?)", (str(time.time()),))
            if due:
                self.gc(True)
            return {"connected": True}
        if action == "claim":
            wait = request.get("wait", 0)
            held = request.get("held", [])
            if type(wait) not in {int, float} or not 0 <= wait <= CLAIM_WAIT or not isinstance(held, list) or len(held) > MAX_RECONCILE:
                raise Refusal()
            return self.claim(request.get("request_id"), wait, {valid_id(item) for item in held})
        if action == "reconcile":
            jobs = request.get("jobs")
            if not isinstance(jobs, list) or len(jobs) > MAX_RECONCILE:
                raise Refusal()
            for item in jobs:
                if not isinstance(item, dict):
                    raise Refusal()
                valid_id(item.get("job_id"))
            response = []
            with transaction(self.db):
                # Each job settles on its own, so one bad job cannot stall the rest of the batch.
                for item in jobs:
                    self.db.execute("SAVEPOINT item")
                    try:
                        response.append(self.reconcile_one(item))
                        self.db.execute("RELEASE item")
                    except Refusal as error:
                        self.db.execute("ROLLBACK TO item")
                        self.db.execute("RELEASE item")
                        response.append({"job_id": item["job_id"], "error": error.reason})
            return {"jobs": response}
        if action == "reject":
            # The worker could not take a claimed job it never started; record that it failed.
            row = self.job(request.get("job_id"))
            if row["claim"] != valid_id(request.get("claim_id")):
                raise Refusal("CLAIM_MISMATCH")
            with transaction(self.db):
                self.settle(row["id"], "failed", 126, "CLAIM_REJECTED")
            return self.status(row["id"])
        if action == "report":
            return self.report(request.get("bundle"), request.get("digest"))
        raise Refusal()


def percentiles(values):
    values = sorted(max(0.0, value) for value in values)
    pick = lambda share: round(values[min(len(values) - 1, math.ceil(share * len(values)) - 1)], 3) if values else None
    return {"count": len(values), "p50": pick(0.5), "p95": pick(0.95)}


def freeze_empty():
    import io
    import tarfile
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w"):
        pass
    return out.getvalue()
