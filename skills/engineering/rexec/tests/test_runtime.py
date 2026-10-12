import base64
import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(RUNTIME))
from rexec_runtime.common import MAX_ARTIFACT, MAX_LOG, Refusal, atomic, digest, encode, immutable, opaque, transaction
from rexec_runtime.export import Publisher
from rexec_runtime.local import Local, Transport
from rexec_runtime.server import Server
from rexec_runtime.snapshot import extract, freeze
from rexec_runtime.__main__ import write_artifacts
from rexec_runtime.service import plist, service


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rexec-test-", dir="/tmp")
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote"
        self.mac = self.root / "mac"
        self.source = self.root / "source"
        self.source.mkdir()
        self.server = Server(self.remote)
        token = self.server.provision()
        atomic(self.mac / "worker.token", token.encode())
        self.fake = self.root / "bin"
        self.fake.mkdir()
        script = self.fake / "ssh"
        script.write_text("#!" + sys.executable + "\n" + '''import json,os,pathlib,subprocess,sys,time
if len(sys.argv)!=3 or sys.argv[1]!='vps-cc' or sys.argv[2] not in {'rexec-worker','rexec-provision'}:
    sys.exit(99)
root=pathlib.Path(os.environ['REXEC_TEST_REMOTE'])
request=sys.stdin.buffer.read()
action=json.loads(request).get('action') if request else 'provision'
if (root/('block-'+action)).exists():
    time.sleep(120)
env=dict(os.environ,REXEC_STATE_DIR=str(root))
role='rpc' if sys.argv[2]=='rexec-worker' else 'provision'
result=subprocess.run([sys.executable,'-m','rexec_runtime',role],input=request,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
fault=root/('lose-'+action)
if fault.exists():
    fault.unlink()
    sys.exit(255)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
''')
        script.chmod(0o755)
        self.environment = dict(os.environ, PYTHONPATH=str(RUNTIME), PATH=str(self.fake) + os.pathsep + os.environ["PATH"], REXEC_STATE_DIR=str(self.mac), REXEC_TEST_REMOTE=str(self.remote))
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        local = Local(self.mac)
        for row in local.db.execute("SELECT * FROM jobs WHERE state='RUNNING'"):
            local.proof(row, "cancel")
        time.sleep(0.15)
        local.db.close()
        self.server.db.close()
        # A worker's fake-ssh RPC runs in its own session and can outlive the worker briefly.
        for _ in range(30):
            try:
                self.temporary.cleanup()
                break
            except OSError:
                time.sleep(0.1)
        else:
            self.temporary.cleanup()

    def submit(self, command="printf safe", **kw):
        return self.server.submit(command, self.source, ".", kw.get("timeout", 10), kw.get("request", opaque()), kw.get("with_git", False))["job_id"]

    def spawn(self, role, *args):
        process = subprocess.Popen([sys.executable, "-m", "rexec_runtime", role, *args], env=self.environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.processes.append(process)
        return process

    def until(self, predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.05)
        self.fail("isolated operation did not converge")

    def finished(self, job):
        return self.until(lambda: self.server.status(job) if self.server.job(job)["result_digest"] else None)

    def local_finished(self, job):
        local = Local(self.mac)
        def result():
            row = local.db.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone()
            return json.loads((self.mac / "outbox" / job).read_bytes()) if row and row[0] == "TERMINAL" else None
        return self.until(result)

    def test_request_retry_freezes_source_and_rejects_conflict(self):
        (self.source / "value.txt").write_text("before")
        request = opaque()
        job = self.submit("cat value.txt", request=request)
        (self.source / "value.txt").write_text("after")
        self.assertEqual(job, self.submit("cat value.txt", request=request))
        with self.assertRaises(Refusal):
            self.submit("different", request=request)
        self.spawn("worker")
        self.assertEqual(self.finished(job)["stdout"], "before")

    def test_command_runs_once_after_lost_claim_and_ack(self):
        marker = self.root / "effect"
        job = self.submit("printf x >> " + str(marker))
        (self.remote / "lose-claim").touch()
        (self.remote / "lose-report").touch()
        worker = self.spawn("worker")
        result = self.finished(job)
        self.assertEqual(result["exit_code"], 0)
        self.until(lambda: Local(self.mac).row(job)["acknowledged"])
        worker.kill()
        worker.wait()
        self.spawn("worker")
        time.sleep(0.4)
        self.assertEqual(marker.read_text(), "x")
        terminal = [e for e in self.server.trace(job) if e["phase"] == "RESULT_STORED"]
        self.assertEqual(len(terminal), 1)

    def test_worker_death_and_viewer_closure_leave_supervisor(self):
        marker = self.root / "effect"
        job = self.submit("sleep 0.8; printf x >> " + str(marker))
        worker = self.spawn("worker")
        self.until(lambda: Local(self.mac).db.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone())
        self.until(lambda: Local(self.mac).row(job)["state"] == "RUNNING")
        viewer = self.spawn("agent", "view", job)
        viewer.wait(timeout=3)
        worker.kill()
        worker.wait()
        self.assertEqual(self.local_finished(job)["exit_code"], 0)
        self.spawn("worker")
        self.assertEqual(self.finished(job)["outcome"], "completed")
        self.assertEqual(marker.read_text(), "x")

    def test_deadline_is_independent_of_blocked_transport(self):
        marker = self.root / "effect"
        job = self.submit("sleep 3; printf x >> " + str(marker), timeout=1)
        self.spawn("worker")
        self.until(lambda: Local(self.mac).db.execute("SELECT 1 FROM jobs WHERE id=? AND state='RUNNING'", (job,)).fetchone())
        (self.remote / "block-reconcile").touch()
        started = time.monotonic()
        self.assertEqual(self.local_finished(job)["exit_code"], 124)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertFalse(marker.exists())

    def test_cancel_prevents_effect_and_persists_cancel_result(self):
        marker = self.root / "effect"
        job = self.submit("sleep 3; printf x >> " + str(marker))
        self.spawn("worker")
        self.until(lambda: Local(self.mac).db.execute("SELECT 1 FROM jobs WHERE id=? AND state='RUNNING'", (job,)).fetchone())
        (self.remote / "lose-report").touch()
        self.server.cancel(job)
        result = self.finished(job)
        self.assertEqual(result["exit_code"], 125)
        self.assertFalse(marker.exists())
        self.until(lambda: Local(self.mac).row(job)["acknowledged"])

    def test_parent_exit_cleans_background_group_before_release(self):
        marker = self.root / "effect"
        job = self.submit("(sleep 1; printf x >> " + str(marker) + ") & printf done")
        self.spawn("worker")
        self.assertEqual(self.finished(job)["stdout"], "done")
        time.sleep(1.2)
        self.assertFalse(marker.exists())

    def test_singleton_worker(self):
        first = self.spawn("worker")
        self.until(lambda: (self.mac / "worker.lock").exists())
        time.sleep(0.1)
        second = self.spawn("worker")
        self.assertEqual(second.wait(timeout=3), 73)
        self.assertIsNone(first.poll())

    def test_same_workspace_serial_and_unbounded_capacity(self):
        first = self.submit()
        second = self.submit()
        others = []
        for index in range(4):
            other = self.root / f"other{index}"
            other.mkdir()
            others.append(self.server.submit("true", other, ".", 10, opaque())["job_id"])
        claimed = {self.server.claim(opaque())["job"]["id"] for _ in range(5)}
        self.assertEqual(claimed, {first, *others})
        self.assertIsNone(self.server.claim(opaque())["job"])
        self.assertEqual(self.server.job(second)["state"], "QUEUED")

    def test_cancel_claim_serialization(self):
        job = self.submit()
        barrier = threading.Barrier(2)
        outcomes = []
        def cancel():
            server = Server(self.remote)
            barrier.wait()
            outcomes.append(server.cancel(job))
            server.db.close()
        thread = threading.Thread(target=cancel)
        thread.start()
        barrier.wait()
        response = self.server.claim(opaque())
        thread.join()
        self.assertTrue(self.server.job(job)["cancel"])
        if response["job"]:
            self.assertEqual(self.server.job(job)["state"], "CLAIMED")
        else:
            self.assertEqual(self.server.status(job)["exit_code"], 125)

    def test_unknown_never_replays_and_releases_workspace(self):
        marker = self.root / "effect"
        job = self.submit("printf x >> " + str(marker))
        local = Local(self.mac)
        local.receive(self.server.claim(opaque()))
        local.prepare(job)
        local.db.execute("UPDATE jobs SET state='RUNNING',started=?,nonce=?,socket=? WHERE id=?", (time.time(), opaque(), str(self.root / "missing"), job))
        # A held supervisor lock means the supervisor lives, however slow its socket is.
        with open(self.mac / "jobs" / job / "supervisor.lock", "a") as lock:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
            local.recover()
            self.assertEqual(local.row(job)["state"], "RUNNING")
        local.recover()
        bundle = json.loads((self.mac / "outbox" / job).read_bytes())
        self.assertEqual((bundle["outcome"], bundle["exit_code"], bundle["reason"]), ("unknown", 70, "SUPERVISOR_LOST"))
        self.server.report(bundle, digest(encode(bundle)))
        self.assertEqual(self.server.job(job)["state"], "RESULT_STORED")
        self.assertEqual(self.server.status(job)["reason"], "SUPERVISOR_LOST")
        second = self.submit()
        self.assertEqual(self.server.claim(opaque())["job"]["id"], second)
        self.assertFalse(marker.exists())

    def test_launch_without_supervisor_is_plain_failure(self):
        job = self.submit("printf forbidden")
        local = Local(self.mac)
        local.receive(self.server.claim(opaque()))
        local.prepare(job)
        local.db.execute("UPDATE jobs SET state='START_RESERVED',nonce=?,socket=? WHERE id=?", (opaque(), str(self.root / "missing"), job))
        local.recover()
        bundle = json.loads((self.mac / "outbox" / job).read_bytes())
        self.assertEqual((bundle["outcome"], bundle["exit_code"], bundle["reason"]), ("failed", 126, "LAUNCH_FAILED"))

    def test_legacy_unknown_reservation_is_released_on_upgrade(self):
        job = self.submit()
        claimed = self.server.claim(opaque())["job"]
        bundle = Publisher().bundle(job, claimed["claim"], "unknown", 70, "EXECUTION_UNKNOWN")
        self.server.report(bundle, digest(encode(bundle)))
        self.server.db.execute("UPDATE jobs SET state='CLAIMED' WHERE id=?", (job,))
        Server(self.remote).db.close()
        self.assertEqual(self.server.job(job)["state"], "RESULT_STORED")

    def test_claim_lease_releases_jobs_the_worker_does_not_hold(self):
        held, lost = self.submit(), self.server.submit("true", self.root, ".", 10, opaque())["job_id"]
        request = opaque()
        self.assertEqual(self.server.claim(request)["job"]["id"], held)
        self.server.claim(opaque())
        self.server.db.execute("UPDATE jobs SET claimed=0")
        heartbeat = {"token": self.server.provision(), "action": "heartbeat", "state": "READY"}
        self.server.rpc(heartbeat)
        self.assertEqual(self.server.job(lost)["state"], "CLAIMED")
        self.server.rpc(dict(heartbeat, active=[held]))
        self.assertEqual(self.server.job(held)["state"], "CLAIMED")
        self.assertEqual((self.server.status(lost)["outcome"], self.server.status(lost)["reason"]), ("unknown", "CLAIM_LOST"))
        self.server.rpc(dict(heartbeat, active=[]))
        self.assertEqual(self.server.job(held)["state"], "RESULT_STORED")
        # A retried claim no longer hands back a job that was settled without the worker.
        self.assertIsNone(self.server.claim(request)["job"])

    def test_one_missing_job_does_not_stall_reconcile_or_reports(self):
        first, second = self.submit("printf one"), self.server.submit("printf two", self.root, ".", 10, opaque())["job_id"]
        local = Local(self.mac, self.isolated())
        local.tick()
        self.until(lambda: all(Local(self.mac).row(job)["state"] == "TERMINAL" for job in (first, second)))
        with transaction(self.server.db):
            self.server.db.execute("DELETE FROM claims WHERE job_id=?", (first,))
            self.server.db.execute("DELETE FROM jobs WHERE id=?", (first,))
        local.reconcile()
        self.assertEqual(self.server.status(second)["stdout"], "two")
        self.assertTrue(local.row(first)["acknowledged"])
        self.assertTrue(local.row(second)["acknowledged"])
        self.assertIn("ORPHANED_RESULT", json.dumps(local.health()))

    def test_claim_that_never_arrives_is_rejected_after_retries(self):
        job = self.submit()
        server = self.server
        class Corrupting:
            def call(inner, action, **parameters):
                response = server.rpc({"token": server.provision(), "action": action, **parameters})
                if action == "claim" and response.get("job"):
                    response["snapshot_digest"] = "0" * 64
                return response
        local = Local(self.mac, Corrupting())
        for _ in range(3):
            with self.assertRaises(Refusal):
                local.claim()
        self.assertEqual((self.server.status(job)["outcome"], self.server.status(job)["exit_code"], self.server.status(job)["reason"]), ("failed", 126, "CLAIM_REJECTED"))
        self.assertIsNone(local.db.execute("SELECT 1 FROM settings WHERE key='claim_request'").fetchone())
        self.assertFalse(local.claim())

    def test_report_write_failure_has_no_false_ack(self):
        job = self.submit()
        claimed = self.server.claim(opaque())["job"]
        bundle = Publisher().bundle(job, claimed["claim"], "completed", 0, "COMPLETED")
        with patch("rexec_runtime.server.immutable", side_effect=OSError("isolated failure")):
            with self.assertRaises(OSError):
                self.server.report(bundle, digest(encode(bundle)))
        self.assertIsNone(self.server.job(job)["result_digest"])
        first = self.server.report(bundle, digest(encode(bundle)))
        self.assertEqual(first, self.server.report(bundle, digest(encode(bundle))))
        bundle["stdout"] = "different"
        with self.assertRaises(Refusal):
            self.server.report(bundle, digest(encode(bundle)))

    def test_sealed_preparation_cancel_recovers_without_launch(self):
        job = self.submit()
        local = Local(self.mac)
        local.receive(self.server.claim(opaque()))
        row = local.row(job)
        bundle = local.publisher.bundle(job, row["claim"], "cancelled", 125, "CANCELLED")
        immutable(self.mac / "outbox" / job, encode(bundle))
        local.recover()
        self.assertEqual(local.row(job)["state"], "TERMINAL")
        self.assertEqual(local.row(job)["result_digest"], digest(encode(bundle)))

    def test_log_cap_drains_noisy_command(self):
        job = self.submit("python3 -c 'import sys;sys.stdout.write(\"x\"*3000000);sys.stderr.write(\"y\"*3000000)'", timeout=5)
        self.spawn("worker")
        result = self.finished(job)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["log_truncated"])
        self.assertLessEqual((self.mac / "jobs" / job / "stdout").stat().st_size, MAX_LOG)
        self.assertLessEqual(len(result["stdout"]), 16384)

    def test_long_output_keeps_head_tail_and_exit_status(self):
        job = self.submit("echo first-line; python3 -c 'print(\"noise line\\n\"*400000, end=\"\")'; echo last-line; exit 3", timeout=5)
        self.spawn("worker")
        result = self.finished(job)
        self.assertEqual(result["exit_code"], 3)
        self.assertTrue(result["log_truncated"])
        raw = (self.mac / "jobs" / job / "stdout").read_bytes()
        self.assertLessEqual(len(raw), MAX_LOG)
        self.assertTrue(raw.startswith(b"first-line\n") and raw.endswith(b"last-line\n"))
        self.assertIn(b"bytes omitted", raw)
        self.assertLessEqual(len(result["stdout"]), 16384)
        self.assertTrue(result["stdout"].startswith("first-line\n") and result["stdout"].endswith("noise line\nlast-line\n"))
        self.assertIn("chars omitted", result["stdout"])
        self.assertEqual(Publisher().sanitize(result["stdout"]), result["stdout"])

    def test_low_space_pauses_claim_and_spawn(self):
        job = self.submit()
        class IsolatedTransport:
            def call(inner, action, **parameters):
                return self.server.rpc({"token": self.server.provision(), "action": action, **parameters})
        local = Local(self.mac, IsolatedTransport())
        with patch.object(local, "space", return_value=False):
            local.tick()
        self.assertEqual(self.server.job(job)["state"], "QUEUED")
        local.receive(self.server.claim(opaque()))
        local.prepare(job)
        with patch.object(local, "space", return_value=False):
            local.launch(job)
        self.assertEqual(local.row(job)["state"], "READY")

    def test_every_published_byte_is_filtered_and_thread_uuid_preserved(self):
        thread = "00000000-1111-2222-3333-444444444444"
        private = "fixture-private-literal"
        command = "printf '\033[31m/Users/fixture/private 192.0.2.99 2001:db8::1 ::1 SHA256:fixturefixture Bearer fixturesecret " + private + "'; printf '{\"status\":0,\"thread_id\":\"" + thread + "\"}' > \"$REXEC_ARTIFACTS/status.json\"; printf '/home/fixture/private " + private + "' > \"$REXEC_ARTIFACTS/response.md\"; : > \"$REXEC_ARTIFACTS/changes.patch\""
        atomic(self.mac / "private-literals.json", encode([private]))
        job = self.submit(command)
        self.spawn("worker")
        result = self.finished(job)
        bundle = self.server.bundle(self.server.job(job))
        captured = encode([result, self.server.trace(job), bundle])
        for forbidden in (b"/Users/fixture", b"192.0.2.99", b"2001:db8::1", b"::1", b"SHA256:fixturefixture", b"Bearer fixturesecret", private.encode(), b"\\u001b"):
            self.assertNotIn(forbidden, captured)
        target = self.root / "output"
        write_artifacts(bundle, target)
        self.assertEqual(json.loads((target / "status.json").read_text())["thread_id"], thread)
        self.assertEqual((target / "changes.patch").read_bytes(), b"")

    def test_privacy_failure_has_empty_output_without_raw_fallback(self):
        publisher = Publisher()
        with patch.object(publisher, "sanitize", side_effect=RuntimeError()):
            bundle = publisher.bundle(opaque(), opaque(), "completed", 0, "COMPLETED", b"raw-private")
        self.assertEqual(bundle["reason"], "OUTPUT_BLOCKED")
        self.assertEqual(bundle["stdout"], "")
        self.assertEqual(bundle["artifacts"], [])

    def test_trace_field_types_refuse_private_injection(self):
        value = {"job_id": opaque(), "sequence": 1, "phase": "RUNNING", "duration": 1.5, "attempt": 1, "outcome": "pending", "reason": "STARTED"}
        for key, bad in (("duration", "private"), ("duration", float('nan')), ("attempt", "private"), ("attempt", True), ("phase", "private"), ("sequence", True)):
            with self.subTest(key=key):
                changed = dict(value, **{key: bad})
                with self.assertRaises(Refusal):
                    Publisher().events([changed])

    def test_artifact_refusals_include_patch_binary_and_symlinks(self):
        artifacts = self.root / "artifacts"
        artifacts.mkdir()
        for name, content in (("changes.patch", "+++ /Users/fixture/private\n"), ("changes.patch", "GIT binary patch\n"), ("raw.jsonl", "safe"), (".hidden.txt", "safe"), ("value.bin", "safe"), ("secret.txt", "safe")):
            with self.subTest(name=name, content=content):
                path = artifacts / name
                path.write_text(content)
                with self.assertRaises(Refusal):
                    Publisher().artifacts(artifacts)
                path.unlink()
        (artifacts / "response.md").symlink_to(self.source)
        with self.assertRaises(Refusal):
            Publisher().artifacts(artifacts)
        link = self.root / "link"
        link.symlink_to(artifacts)
        with self.assertRaises(Refusal):
            Publisher().artifacts(link)

    def test_snapshot_excludes_secrets_caches_and_git_local_material(self):
        for folder in ("node_modules", ".codex-out", ".git/hooks", ".git/objects"):
            (self.source / folder).mkdir(parents=True)
        for name in (".env", "fixture.pem", "node_modules/cache.txt", ".codex-out/response.md", ".git/config", ".git/hooks/post-checkout", ".git/objects/fixture", "normal.txt"):
            (self.source / name).write_text("safe")
        def names(blob):
            with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
                return archive.getnames()
        self.assertEqual(names(freeze(self.source)), ["normal.txt"])
        self.assertEqual(set(names(freeze(self.source, True))), {"normal.txt", ".git", ".git/objects", ".git/objects/fixture"})

    def test_snapshot_rejects_links_traversal_and_wrong_digest(self):
        (self.source / "link").symlink_to("outside")
        (self.source / "kept.txt").write_text("safe")
        report = {}
        with tarfile.open(fileobj=io.BytesIO(freeze(self.source, report=report))) as archive:
            self.assertEqual(archive.getnames(), ["kept.txt"])
        self.assertEqual((report["skipped"], report["skipped_count"], report["files"]), (["link"], 1, 1))
        (self.source / "link").unlink()
        link = self.root / "source-link"
        link.symlink_to(self.source)
        with self.assertRaises(Refusal):
            freeze(link)
        for name in ("../outside", "/outside", "normal"):
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                entry = tarfile.TarInfo(name)
                entry.size = 1
                if name == "normal":
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = "outside"
                tar.addfile(entry, io.BytesIO(b"x"))
            data = archive.getvalue()
            with self.assertRaises(Refusal):
                extract(data, digest(data), self.root / "extract")
        with self.assertRaises(Refusal):
            extract(freeze(self.source), "wrong", self.root / "extract")

    def test_gc_excludes_active_unknown_and_unacknowledged(self):
        job = self.submit()
        self.server.cancel(job)
        self.server.db.execute("UPDATE jobs SET completed=0 WHERE id=?", (job,))
        self.assertEqual(self.server.gc(True)["eligible_jobs"], 0)
        row = self.server.job(job)
        self.server.ack(job, row["result_digest"])
        self.assertEqual(self.server.gc(True)["eligible_jobs"], 0)
        self.server.ack(job, row["result_digest"], True)
        self.assertEqual(self.server.gc(True)["eligible_jobs"], 1)
        with self.assertRaises(Refusal):
            self.server.job(job)

    def test_launchagent_plist_and_actions_without_real_install(self):
        value = plist(self.mac)
        decoded = plistlib.loads(plistlib.dumps(value))
        self.assertEqual(decoded["ProgramArguments"][0], sys.executable)
        self.assertTrue(Path(decoded["EnvironmentVariables"]["PYTHONPATH"]).is_absolute())
        with patch("rexec_runtime.service.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"private", b"private")) as run:
            self.assertTrue(service(self.mac, "status")["running"])
            self.assertNotIn("private", encode(service(self.mac, "stop")).decode())
            self.assertEqual(run.call_args.args[0][0], "launchctl")

    def test_wait_actual_exit_75_and_pending_are_distinct(self):
        job = self.submit("exit 75")
        args = [sys.executable, "-m", "rexec_runtime", "server", "wait", job, "--wait-timeout", "0"]
        env = dict(self.environment, REXEC_STATE_DIR=str(self.remote))
        pending = subprocess.run(args, env=env, capture_output=True)
        self.assertEqual(pending.returncode, 75)
        self.assertNotIn("outcome", json.loads(pending.stdout))
        self.spawn("worker")
        self.finished(job)
        completed = subprocess.run(args, env=env, capture_output=True)
        self.assertEqual(completed.returncode, 75)
        self.assertEqual(json.loads(completed.stdout)["outcome"], "completed")
        repeated = subprocess.run(args, env=env, capture_output=True)
        self.assertEqual(completed.stdout, repeated.stdout)

    def test_legacy_controls_and_invalid_args_have_fixed_errors(self):
        for extra, environment in ((["--mac", "private"], {}), (["status"], {"REXEC_HOST": "private"})):
            result = subprocess.run([sys.executable, "-m", "rexec_runtime", "server", *extra], env=dict(self.environment, **environment), capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b"private", result.stdout + result.stderr)

    def test_trace_retry_has_no_duplicate_and_retains_timing(self):
        job = self.submit()
        row = self.server.claim(opaque())["job"]
        value = {"job_id": job, "sequence": 1, "phase": "RUNNING", "duration": 4.125, "attempt": 1, "outcome": "pending", "reason": "STARTED"}
        request = {"token": self.server.provision(), "action": "reconcile", "jobs": [{"job_id": job, "claim_id": row["claim"], "events": [value]}]}
        self.server.rpc(request)
        self.server.rpc(request)
        trace = self.server.trace(job)
        run = [v for v in trace if v["phase"] == "RUNNING"]
        self.assertEqual(len(run), 1)
        self.assertEqual(run[0]["duration"], 4.125)

    def test_empty_cwd_survives_snapshot(self):
        (self.source / "empty").mkdir()
        job = self.server.submit("printf safe", self.source, "empty", 5, opaque())["job_id"]
        self.spawn("worker")
        self.assertEqual(self.finished(job)["stdout"], "safe")

    def test_channel_status_and_low_space_use_fixed_states(self):
        self.assertEqual(self.server.channel()["state"], "OFFLINE")
        self.server.rpc({"token": self.server.provision(), "action": "heartbeat", "state": "READY"})
        self.assertEqual(self.server.channel()["state"], "READY")
        self.server.rpc({"token": self.server.provision(), "action": "heartbeat", "state": "LOW_SPACE"})
        self.assertEqual(self.server.channel()["state"], "LOW_SPACE")
        self.assertGreaterEqual(self.server.channel()["last_contact_age_seconds"], 0)

    def test_artifact_receiver_failure_does_not_ack(self):
        job = self.submit()
        row = self.server.claim(opaque())["job"]
        artifacts = self.root / "artifact-source"
        artifacts.mkdir()
        (artifacts / "response.md").write_text("safe")
        bundle = Publisher().bundle(job, row["claim"], "completed", 0, "COMPLETED", artifacts=Publisher().artifacts(artifacts))
        self.server.report(bundle, digest(encode(bundle)))
        destination = self.root / "destination"
        destination.symlink_to(artifacts)
        environment = dict(self.environment, REXEC_STATE_DIR=str(self.remote))
        result = subprocess.run([sys.executable, "-m", "rexec_runtime", "server", "artifacts", job, "--into", str(destination)], env=environment, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.server.job(job)["artifact_ack"])
        destination.unlink()
        result = subprocess.run([sys.executable, "-m", "rexec_runtime", "server", "artifacts", job, "--into", str(destination)], env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.server.job(job)["artifact_ack"])
        self.assertEqual((destination / "response.md").read_text(), "safe")

    def test_installer_isolated_paths_and_no_service_actions(self):
        state = self.root / "install-state"
        binary = self.root / "install-bin"
        installer = RUNTIME.parent / "install.sh"
        environment = dict(self.environment, REXEC_STATE_DIR=str(state), REXEC_INSTALL_BIN_DIR=str(binary))
        result = subprocess.run(["bash", str(installer)], env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["services_started"])
        self.assertTrue((binary / "rexec").is_symlink())
        environment["REXEC_STATE_DIR"] = str(state)
        receipt = subprocess.run([str(binary / "rexec"), "status"], env=environment, capture_output=True)
        self.assertEqual(receipt.returncode, 0)
        self.assertEqual(json.loads(receipt.stdout)["channel"]["state"], "AUTHORIZATION_REQUIRED")

    def test_one_line_update_pulls_runtime_and_restarts_worker(self):
        state = self.root / "install-state"
        home = self.root / "home"
        tools = self.root / "update-bin"
        for path in (home, tools):
            path.mkdir()
        environment = dict(self.environment, REXEC_STATE_DIR=str(state), REXEC_INSTALL_BIN_DIR=str(self.root / "install-bin"))
        self.assertEqual(subprocess.run(["bash", str(RUNTIME.parent / "install.sh")], env=environment, capture_output=True).returncode, 0)
        (tools / "ssh").write_text('#!/bin/sh\n[ "$1" = vps-cc ] || exit 99\nexec sh -c "$2"\n')
        (tools / "uv").write_text("#!/bin/sh\necho " + sys.executable + "\n")
        log = self.root / "launchctl.log"
        (tools / "launchctl").write_text('#!/bin/sh\necho "$1" >> ' + str(log) + '\nloaded=' + str(self.root / "loaded") + '\ncase "$1" in print) [ -e "$loaded" ];; bootstrap) touch "$loaded";; bootout) rm "$loaded";; esac\n')
        for name in ("ssh", "uv", "launchctl"):
            (tools / name).chmod(0o755)
        environment = dict(os.environ, HOME=str(home), PATH=str(tools) + os.pathsep + os.environ["PATH"], REXEC_STATE_DIR=str(self.mac), REXEC_REMOTE_ROOT=str(state))
        line = "mkdir -p ~/.rexec && ssh vps-cc 'cat " + str(state) + "/agent.sh' > ~/.rexec/agent.sh && bash ~/.rexec/agent.sh"
        for _ in range(2):
            result = subprocess.run(["bash", "-c", line], env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"updated": True, "running": True})
        self.assertTrue((home / ".rexec/runtime/rexec_runtime/__main__.py").is_file())
        self.assertFalse(list((home / ".rexec").glob(".runtime-*")))
        installed = plistlib.loads((home / "Library/LaunchAgents/dev.xiaowan.rexec.worker.plist").read_bytes())
        self.assertEqual(installed["EnvironmentVariables"]["PYTHONPATH"], str((home / ".rexec/runtime").resolve()))
        self.assertEqual(log.read_text().split().count("bootstrap"), 2)
        self.assertEqual(log.read_text().split().count("bootout"), 1)

    def test_service_install_plist_with_isolated_home(self):
        home = self.root / "home"
        parent = home / "Library/LaunchAgents"
        parent.mkdir(parents=True)
        parent.chmod(0o755)
        with patch("rexec_runtime.service.Path.home", return_value=home):
            self.assertEqual(service(self.mac, "install"), {"installed": True, "started": False})
        self.assertEqual(parent.stat().st_mode & 0o777, 0o755)
        installed = plistlib.loads((parent / "dev.xiaowan.rexec.worker.plist").read_bytes())
        self.assertTrue(installed["AbandonProcessGroup"])

    def test_artifact_expansion_and_private_filenames_refused_before_seal(self):
        artifacts = self.root / "artifact-source"
        artifacts.mkdir()
        path = artifacts / "response.md"
        path.write_text("abc" * 699000)
        with self.assertRaises(Refusal):
            Publisher(["abc"]).artifacts(artifacts)
        path.unlink()
        for name in ("192.0.2.99.txt", "fixture-private.txt"):
            path = artifacts / name
            path.write_text("safe")
            with self.assertRaises(Refusal):
                Publisher(["fixture-private"]).artifacts(artifacts)
            path.unlink()

    def test_supervisor_loss_recovers_unknown_during_blocked_network(self):
        job = self.submit("sleep 3", timeout=5)
        self.spawn("worker")
        local = Local(self.mac)
        self.until(lambda: local.db.execute("SELECT 1 FROM jobs WHERE id=? AND state='RUNNING'", (job,)).fetchone())
        (self.remote / "block-reconcile").touch()
        row = local.row(job)
        pid = None
        output = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout
        for line in output.splitlines():
            if "rexec_runtime supervise " + job in line:
                pid = int(line.split()[0])
                break
        self.assertIsNotNone(pid)
        os.kill(pid, signal.SIGKILL)
        self.assertEqual(self.local_finished(job)["outcome"], "unknown")

    def test_empty_claim_bookkeeping_is_bounded(self):
        for _ in range(30):
            self.server.claim(opaque())
        self.assertEqual(self.server.db.execute("SELECT COUNT(*) FROM claims").fetchone()[0], 1)

    def test_redaction_marker_survives_receipt_validation(self):
        job = self.submit()
        local = Local(self.mac)
        local.receive(self.server.claim(opaque()))
        local.publisher = Publisher(["private", "[private]"])
        local.terminal(job, "completed", 7, "COMPLETED", stdout=b"/Users/fixture/example")
        result = json.loads((self.mac / "outbox" / job).read_bytes())
        self.assertEqual(result["stdout"], "[private]")
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(local.publisher.sanitize(result["stdout"]), result["stdout"])
        self.server.report(result, digest(encode(result)))
        self.assertEqual(self.server.status(job)["outcome"], "completed")

    def test_filter_failure_publishes_empty_completed_receipt(self):
        job = self.submit()
        local = Local(self.mac)
        local.receive(self.server.claim(opaque()))
        with patch.object(local.publisher, "sanitize", side_effect=RuntimeError("filter failed")):
            local.terminal(job, "completed", 7, "COMPLETED", stdout=b"private data")
        result = json.loads((self.mac / "outbox" / job).read_bytes())
        self.assertEqual((result["stdout"], result["stderr"], result["artifacts"]), ("", "", []))
        self.assertEqual((result["outcome"], result["exit_code"], result["reason"]), ("completed", 7, "OUTPUT_BLOCKED"))
        self.server.report(result, digest(encode(result)))
        self.assertEqual(local.view(job)[-1]["reason"], "OUTPUT_BLOCKED")

    def test_remote_gc_failure_does_not_restore_deleted_blob_references(self):
        job = self.submit()
        claim = self.server.claim(opaque())["job"]["claim"]
        result = Publisher().bundle(job, claim, "completed", 0, "COMPLETED")
        value = self.server.report(result, digest(encode(result)))["digest"]
        self.server.ack(job, value)
        self.server.ack(job, value, artifacts=True)
        self.server.db.execute("UPDATE jobs SET completed=0 WHERE id=?", (job,))
        (self.source / "live.txt").write_text("live source")
        live = self.submit()
        unlink = Path.unlink
        def interrupted_unlink(path, *args, **kwargs):
            unlink(path, *args, **kwargs)
            raise OSError("cleanup interrupted")
        with patch.object(Path, "unlink", interrupted_unlink), self.assertRaises(OSError):
            self.server.gc(True)
        for row in self.server.db.execute("SELECT snapshot FROM jobs UNION SELECT result_digest FROM jobs WHERE result_digest IS NOT NULL"):
            self.assertTrue((self.remote / "blobs" / row[0]).is_file())
        self.assertEqual(self.server.status(live)["state"], "QUEUED")
        with self.assertRaises(Refusal):
            self.server.job(job)
        self.server.gc(True)

    def test_local_gc_recovers_orphans_after_committed_deletion(self):
        job = self.submit()
        local = Local(self.mac)
        local.receive(self.server.claim(opaque()))
        local.prepare(job)
        local.terminal(job, "completed", 0, "COMPLETED")
        local.db.execute("UPDATE jobs SET acknowledged=1,completed=0 WHERE id=?", (job,))
        with patch.object(local, "discard", side_effect=OSError("cleanup interrupted")), self.assertRaises(OSError):
            local.gc()
        self.assertIsNone(local.db.execute("SELECT id FROM jobs WHERE id=?", (job,)).fetchone())
        self.assertTrue((self.mac / "jobs" / job).is_dir())
        self.assertTrue((self.mac / "outbox" / job).is_file())
        local.gc()
        self.assertFalse((self.mac / "jobs" / job).exists())
        self.assertFalse((self.mac / "outbox" / job).exists())

    def test_tick_claims_and_prepares_several_jobs(self):
        jobs = []
        for index in range(3):
            other = self.root / f"tick{index}"
            other.mkdir()
            jobs.append(self.server.submit("true", other, ".", 10, opaque())["job_id"])
        class IsolatedTransport:
            def call(inner, action, **parameters):
                return self.server.rpc({"token": self.server.provision(), "action": action, **parameters})
        local = Local(self.mac, IsolatedTransport())
        with patch.object(local, "launch"):
            local.tick()
        self.assertEqual({row[0] for row in local.db.execute("SELECT id FROM jobs WHERE state='READY'")}, set(jobs))
        self.assertIsNotNone(self.server.channel()["worker_timing"])

    def test_finished_job_drops_workspace_and_snapshot(self):
        job = self.submit()
        local = Local(self.mac)
        local.receive(self.server.claim(opaque()))
        local.prepare(job)
        self.assertTrue((self.mac / "jobs" / job / "workspace").is_dir())
        local.terminal(job, "completed", 0, "COMPLETED")
        local.gc()
        for name in ("workspace", "tmp", "artifacts"):
            self.assertFalse((self.mac / "jobs" / job / name).exists())
        self.assertEqual(list((self.mac / "snapshots").iterdir()), [])
        self.assertTrue((self.mac / "outbox" / job).is_file())
        local.sweeper.wait(timeout=10)
        self.assertEqual(list((self.mac / "trash").iterdir()), [])

    def test_invalid_wait_deadline_has_no_submission_side_effect(self):
        environment = dict(self.environment, REXEC_STATE_DIR=str(self.remote))
        for timeout in ("-1", "nan", "inf", "86401"):
            result = subprocess.run([sys.executable, "-m", "rexec_runtime", "server", "--no-sync", "--wait-timeout", timeout, "true"],
                                    env=environment, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout), {"error": "INVALID_REQUEST"})
            self.assertEqual(self.server.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_outbox_temporary_retention_keeps_fresh_seals(self):
        local = Local(self.mac)
        fresh = self.mac / "outbox" / ".seal-fresh"
        fresh.write_bytes(b"pending seal")
        for prefix in (".seal-", ".write-"):
            stale = self.mac / "outbox" / (prefix + "stale")
            stale.write_bytes(b"abandoned seal")
            os.utime(stale, (0, 0))
        local.gc()
        self.assertEqual(fresh.read_bytes(), b"pending seal")
        self.assertFalse((self.mac / "outbox" / ".seal-stale").exists())
        self.assertFalse((self.mac / "outbox" / ".write-stale").exists())

    def isolated(self):
        class IsolatedTransport:
            def call(inner, action, **parameters):
                return self.server.rpc({"token": self.server.provision(), "action": action, **parameters})
        return IsolatedTransport()

    def test_receipt_timing_and_summary_keep_command_private(self):
        job = self.submit("sleep 0.3; printf safe")
        again = self.submit("sleep 0.3; printf safe")
        other = self.submit("true")
        self.assertIsNotNone(self.server.status(job)["timing"]["queued_s"])
        self.spawn("worker")
        result = self.finished(job)
        timing = result["timing"]
        self.assertEqual(set(timing), {"queued_s", "start_s", "run_s", "report_s"})
        self.assertTrue(all(isinstance(value, float) for value in timing.values()))
        self.assertGreaterEqual(timing["run_s"], 0.3)
        self.finished(again)
        self.finished(other)
        rows = {row["job_id"]: row for row in self.server.db.execute("SELECT * FROM summaries")}
        self.assertEqual(rows[job]["fingerprint"], rows[again]["fingerprint"])
        self.assertNotEqual(rows[job]["fingerprint"], rows[other]["fingerprint"])
        self.assertRegex(rows[job]["fingerprint"], r"^[a-f0-9]{12}$")
        self.assertEqual((rows[job]["outcome"], rows[job]["exit_code"], rows[job]["channel"]), ("completed", 0, "OFFLINE"))
        self.assertIsNotNone(rows[job]["claimed"])
        self.assertAlmostEqual(rows[job]["run_s"], timing["run_s"], places=3)
        self.assertNotIn("sleep", json.dumps(self.server.channel()) + json.dumps(self.server.queue()))

    def test_bundle_without_timing_stays_valid(self):
        bundle = Publisher().bundle(opaque(), opaque(), "completed", 0, "COMPLETED")
        self.assertNotIn("timing", bundle)
        Publisher().validate_bundle(bundle)
        for timing in ({"start_s": -1, "run_s": None}, {"start_s": None}, {"start_s": "x", "run_s": None}):
            with self.assertRaises(Refusal):
                Publisher().validate_bundle(dict(bundle, timing=timing))

    def test_worker_failures_reach_channel_health(self):
        local = Local(self.mac, self.isolated())
        local.failure("RPC_TIMEOUT")
        local.failure("RPC_TIMEOUT")
        local.failure("OS_ERROR")
        local.tick()
        channel = self.server.channel()
        self.assertEqual(channel["recent_failures"], {"OS_ERROR": 1, "RPC_TIMEOUT": 2})
        self.assertIn(channel["last_failure"]["reason"], {"OS_ERROR", "RPC_TIMEOUT"})
        self.assertEqual(local.health(), [])
        local.tick()
        self.assertEqual(self.server.channel()["recent_failures"], {"OS_ERROR": 1, "RPC_TIMEOUT": 2})
        batch = {"id": opaque(), "counts": {"RPC_TIMEOUT": 1}}
        for _ in range(2):
            self.server.rpc({"token": self.server.provision(), "action": "heartbeat", "state": "READY", "health": [batch]})
        self.assertEqual(self.server.channel()["recent_failures"]["RPC_TIMEOUT"], 3)
        for counts in ({"free text": 1}, {"RPC_TIMEOUT": 0}, {"RPC_TIMEOUT": "1"}, ["RPC_TIMEOUT"]):
            health = [{"id": opaque(), "counts": counts}]
            with self.assertRaises(Refusal):
                self.server.rpc({"token": self.server.provision(), "action": "heartbeat", "state": "READY", "health": health})

    def test_worker_loop_records_failed_tick_and_crash(self):
        (self.mac / "worker.failure").write_text("Traceback: private")
        (self.remote / "lose-heartbeat").touch()
        self.spawn("worker")
        failures = self.until(lambda: self.server.channel()["recent_failures"].get("SSH_FAILED") and self.server.channel()["recent_failures"])
        self.assertEqual(failures.get("WORKER_CRASH"), 1)
        self.assertTrue((self.mac / "tick.failure").is_file())
        self.assertNotIn("private", json.dumps(self.server.channel()))

    def test_server_refusal_keeps_its_code_over_ssh(self):
        atomic(self.mac / "worker.token", b"wrong")
        with patch.dict(os.environ, {key: self.environment[key] for key in ("PATH", "PYTHONPATH", "REXEC_TEST_REMOTE")}):
            with self.assertRaises(Refusal) as caught:
                Transport(self.mac).call("heartbeat", state="READY")
        self.assertEqual(caught.exception.reason, "AUTHORIZATION_REQUIRED")

    def test_foreground_submit_reports_job_first_and_refuses_offline_mac(self):
        environment = dict(self.environment, REXEC_STATE_DIR=str(self.remote))
        cli = lambda *words: subprocess.run([sys.executable, "-m", "rexec_runtime", "server", *words], env=environment, capture_output=True, cwd=self.source)
        offline = cli("printf hi")
        self.assertEqual((offline.returncode, json.loads(offline.stdout)), (75, {"error": "CHANNEL_OFFLINE"}))
        self.assertEqual(self.server.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        self.server.rpc({"token": self.server.provision(), "action": "heartbeat", "state": "READY"})
        pending = cli("--label", "unit tests", "--wait-timeout", "0", "printf hi")
        self.assertEqual(pending.returncode, 75)
        job = json.loads(pending.stderr)["job_id"]
        waited = json.loads(pending.stdout)
        self.assertEqual((waited["job_id"], waited["job_state"], waited["channel"]), (job, "QUEUED", "READY"))
        self.spawn("worker")
        self.finished(job)
        item = json.loads(cli("status").stdout)["jobs"][0]
        self.assertEqual((item["job_id"], item["label"], item["exit_code"], item["unread"]), (job, "unit tests", 0, True))
        self.assertNotIn("stdout", item)
        self.assertEqual(json.loads(cli("status", job).stdout)["stdout"], "hi")
        self.assertFalse(json.loads(cli("status").stdout)["jobs"][0]["unread"])
        self.assertEqual(json.loads(cli("--background", "--label", "/home/agent/private", "true").stdout), {"error": "LABEL_INVALID"})

    def test_status_lists_only_jobs_needing_attention(self):
        settled = []
        for index in range(8):
            source = self.root / f"settled{index}"
            source.mkdir()
            job = self.server.submit("true", source, ".", 10, opaque())["job_id"]
            self.server.cancel(job)
            self.server.ack(job, self.server.job(job)["result_digest"])
            settled.append(job)
        unread = self.submit()
        self.server.cancel(unread)
        queued = self.server.submit("true", self.root, ".", 10, opaque())["job_id"]
        listing = self.server.queue()
        self.assertEqual({item["job_id"] for item in listing["jobs"]}, {queued, unread, *settled[-5:]})
        self.assertEqual(listing["hidden"], 3)
        self.assertEqual(len(self.server.queue(True)["jobs"]), 10)

    def test_snapshot_follows_gitignore_and_names_its_failures(self):
        git = lambda *words: subprocess.run(["git", "-C", str(self.source), *words], check=True, capture_output=True)
        git("init", "-q")
        for name in ("src/app.py", "build/out.txt", "secret_store.py", "secrets.yaml", "notes.txt"):
            (self.source / name).parent.mkdir(exist_ok=True)
            (self.source / name).write_text("safe")
        (self.source / ".gitignore").write_text("build/\n")
        git("add", "src/app.py")
        report = {}
        with tarfile.open(fileobj=io.BytesIO(freeze(self.source, report=report))) as archive:
            names = {entry.name for entry in archive if entry.isfile()}
        self.assertEqual(names, {".gitignore", "src/app.py", "secret_store.py", "notes.txt"})
        self.assertTrue(report["gitignore"])
        with tarfile.open(fileobj=io.BytesIO(freeze(self.source, ignored=True))) as archive:
            self.assertIn("build/out.txt", archive.getnames())
        with patch("rexec_runtime.snapshot.MAX_FILES", 2):
            with self.assertRaises(Refusal) as caught:
                freeze(self.source)
        self.assertEqual(caught.exception.reason, "SNAPSHOT_TOO_MANY_FILES")
        self.assertIn("at", caught.exception.detail)
        with self.assertRaises(Refusal) as caught:
            self.server.submit("true", self.source, "missing", 10, opaque())
        self.assertEqual(caught.exception.reason, "CWD_NOT_FOUND")
        self.assertEqual(self.server.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_output_keeps_workspace_paths_and_times(self):
        local = Local(self.mac)
        workspace = self.mac / "jobs" / opaque() / "workspace"
        text = local.publisher.sanitize(f'File "{workspace}/src/app.py", line 12 at 12:34:56 from fe80::1 and 2001:db8:0:0:0:0:0:1')
        self.assertEqual(text, 'File "$WS/src/app.py", line 12 at 12:34:56 from [private] and [private]')
        self.assertEqual(Publisher().sanitize(text), text)

    def test_one_refused_artifact_keeps_the_others(self):
        artifacts = self.root / "artifact-source"
        artifacts.mkdir()
        (artifacts / "report.xml").write_text("<ok/>")
        (artifacts / "huge.txt").write_text("x" * (MAX_ARTIFACT + 1))
        (artifacts / "value.bin").write_text("safe")
        accepted, refused = Publisher().collect(artifacts)
        self.assertEqual([item["name"] for item in accepted], ["report.xml"])
        self.assertEqual(refused, ["huge.txt", None])
        bundle = Publisher().bundle(opaque(), opaque(), "completed", 0, "COMPLETED", artifacts=accepted, refused=refused)
        self.assertEqual(Publisher().validate_bundle(bundle)["artifacts_refused"], ["huge.txt", None])

    def test_cli_usage_and_errors_are_recorded(self):
        environment = dict(self.environment, REXEC_STATE_DIR=str(self.remote))
        cli = lambda *words: subprocess.run([sys.executable, "-m", "rexec_runtime", "server", *words], env=environment, capture_output=True)
        job = self.submit()
        self.assertEqual(cli("wait", job, "--wait-timeout", "0").returncode, 75)
        cli("status", job)
        cli("trace", job)
        self.assertEqual(cli("status", opaque()).returncode, 66)
        cli("bogus", "extra", "words")
        row = self.server.db.execute("SELECT * FROM summaries WHERE job_id=?", (job,)).fetchone()
        self.assertEqual((row["wait_calls"], row["wait_timeouts"], row["status_calls"], row["trace_calls"]), (1, 1, 1, 1))
        self.assertIsNone(row["read"])
        self.spawn("worker")
        self.finished(job)
        self.assertEqual(cli("wait", job).returncode, 0)
        self.assertIsNotNone(self.server.db.execute("SELECT read FROM summaries WHERE job_id=?", (job,)).fetchone()[0])
        errors = [tuple(row) for row in self.server.db.execute("SELECT action,reason FROM cli_errors ORDER BY at")]
        self.assertEqual(errors, [("status", "JOB_NOT_FOUND"), ("submit", "INVALID_REQUEST")])

    def test_legacy_server_state_migrates_and_backfills(self):
        legacy = self.root / "legacy"
        legacy.mkdir(mode=0o700)
        import sqlite3
        db = sqlite3.connect(legacy / "state.sqlite")
        db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY, request TEXT UNIQUE NOT NULL, spec_digest TEXT NOT NULL, workspace TEXT NOT NULL, command TEXT NOT NULL, cwd TEXT NOT NULL, timeout INTEGER NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL, claim TEXT UNIQUE, cancel INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, completed REAL, result_digest TEXT, ack INTEGER NOT NULL DEFAULT 0, artifact_ack INTEGER NOT NULL DEFAULT 0)")
        job = opaque()
        db.execute("INSERT INTO jobs(id,request,spec_digest,workspace,command,cwd,timeout,snapshot,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)", (job, opaque(), "x", opaque(), "true", ".", 10, "x", "QUEUED", time.time()))
        db.commit()
        db.close()
        server = Server(legacy)
        self.assertIsNone(server.job(job)["claimed"])
        self.assertEqual(server.db.execute("SELECT channel FROM summaries WHERE job_id=?", (job,)).fetchone()[0], "UNRECORDED")
        self.assertIsNotNone(server.status(job)["timing"]["queued_s"])
        server.db.close()
        Server(legacy).db.close()

    def test_history_outlives_job_retention(self):
        job = self.submit()
        old = self.submit()
        self.server.db.execute("UPDATE summaries SET created=? WHERE job_id=?", (time.time() - 91 * 86400, old))
        self.server.db.execute("INSERT INTO health VALUES(?,?,?,?)", (opaque(), time.time() - 91 * 86400, "RPC_TIMEOUT", 1))
        self.server.gc(True)
        self.assertEqual([row[0] for row in self.server.db.execute("SELECT job_id FROM summaries")], [job])
        self.assertEqual(self.server.db.execute("SELECT COUNT(*) FROM health").fetchone()[0], 0)

    def test_feedback_is_sanitized_bounded_and_kept_out_of_trace(self):
        environment = dict(self.environment, REXEC_STATE_DIR=str(self.remote))
        cli = lambda *words: subprocess.run([sys.executable, "-m", "rexec_runtime", "server", *words], env=environment, capture_output=True)
        job = self.submit()
        result = cli("feedback", job, "--category", "confusing_output", "--note", "wait said pending under /home/agent/x")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)["recorded"])
        self.assertEqual(cli("feedback", "--category", "docs_unclear").returncode, 0)
        self.assertEqual(json.loads(cli("feedback", "--category", "bogus", "--note", "x").stdout), {"error": "FEEDBACK_CATEGORY"})
        self.assertEqual(json.loads(cli("feedback", "--category", "slow", "--note", "x" * 281).stdout), {"error": "FEEDBACK_TOO_LONG"})
        self.assertEqual(cli("feedback", opaque(), "--category", "slow").returncode, 66)
        self.assertEqual(cli("feedback", job).returncode, 2)
        rows = [tuple(row) for row in self.server.db.execute("SELECT job_id,category,note FROM feedback ORDER BY id")]
        self.assertEqual(rows, [(job, "confusing_output", "wait said pending under [private]"), (None, "docs_unclear", "")])
        self.assertNotIn("pending under", json.dumps(self.server.trace(job)) + json.dumps(self.server.status(job)))
        errors = {row[1] for row in self.server.db.execute("SELECT action,reason FROM cli_errors WHERE action='feedback'")}
        self.assertEqual(errors, {"FEEDBACK_CATEGORY", "FEEDBACK_TOO_LONG", "JOB_NOT_FOUND", "INVALID_REQUEST"})
        self.server.db.execute("UPDATE feedback SET at=?", (time.time() - 91 * 86400,))
        self.server.gc(True)
        self.assertEqual(self.server.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)

    def test_report_aggregates_history_without_private_text(self):
        environment = dict(self.environment, REXEC_STATE_DIR=str(self.remote))
        cli = lambda *words: subprocess.run([sys.executable, "-m", "rexec_runtime", "server", *words], env=environment, capture_output=True)
        ok = self.submit("printf secretword")
        bad = self.submit("exit 3")
        worker = self.spawn("worker")
        self.finished(ok)
        self.finished(bad)
        rerun = self.submit("exit 3")
        self.finished(rerun)
        # Stop the worker so its in-flight RPCs finish before teardown removes the state.
        worker.kill()
        worker.wait()
        time.sleep(1)
        self.server.feedback(bad, "unexpected_failure", "exit 3 surprised me")
        self.server.db.execute("UPDATE summaries SET completed=completed-90000,claimed=claimed-90000,created=created-90000 WHERE job_id=?", (ok,))
        self.server.db.execute("INSERT INTO health VALUES(?,?,?,?)", (opaque(), time.time(), "RPC_TIMEOUT", 2))
        cli("status", opaque())
        result = cli("report")
        self.assertEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["window"], {"since_seconds": 604800, "jobs": 3, "failed": 2})
        self.assertEqual(report["outcomes"], {"completed:COMPLETED": 3})
        self.assertEqual(report["timing"]["run_s"]["count"], 3)
        self.assertLessEqual(report["timing"]["run_s"]["p50"], report["timing"]["run_s"]["p95"])
        self.assertEqual(report["health"], {"RPC_TIMEOUT": 2})
        self.assertEqual(report["usage"]["unread_results"], 1)
        self.assertEqual(report["usage"]["cli_errors"], {"status:JOB_NOT_FOUND": 1})
        self.assertEqual(len(report["failing_commands"]), 1)
        self.assertEqual(report["failing_commands"][0]["runs"], 2)
        self.assertEqual(report["failing_commands"][0]["failures"], 2)
        self.assertEqual(report["feedback"]["categories"], {"unexpected_failure": 1})
        self.assertEqual(report["feedback"]["recent"][0]["note"], "exit 3 surprised me")
        self.assertNotIn(b"secretword", result.stdout)
        self.assertEqual(json.loads(cli("report", "--since", "1h").stdout)["window"]["jobs"], 2)
        for since in ("0d", "91d", "7", "-1d", "1w"):
            self.assertEqual(cli("report", "--since", since).returncode, 2)
        self.assertEqual(self.server.overview(3600)["timing"]["queued_s"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
