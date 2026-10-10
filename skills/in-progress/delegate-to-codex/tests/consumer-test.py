#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
DELEGATE = SKILL / "scripts" / "delegate.sh"

FAKE_REXEC = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, signal, subprocess, sys
store = pathlib.Path(os.environ["FAKE_STORE"])
args = sys.argv[1:]
with (store / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
if args[0] == "wait":
    if os.environ.get("FAKE_INTERRUPT_WAIT"):
        os.kill(os.getppid(), signal.SIGTERM)
        sys.exit(143)
    status = int(os.environ.get("FAKE_WAIT_STATUS", (store / "exit").read_text()))
    if os.environ.get("FAKE_WAIT_PENDING"):
        print(json.dumps({"job_id": "j_fake", "state": "pending", "reason": "WAIT_TIMEOUT"}))
    else:
        outcome = os.environ.get("FAKE_WAIT_OUTCOME", "completed")
        print(json.dumps({"job_id": "j_fake", "state": "RESULT_STORED", "outcome": outcome, "exit_code": status}))
    sys.exit(status)
if args[0] == "artifacts":
    if os.environ.get("FAKE_ARTIFACT_FAIL"):
        sys.exit(74)
    destination = pathlib.Path(args[args.index("--into") + 1])
    for source in (store / "artifacts").iterdir():
        shutil.copyfile(source, destination / source.name)
    sys.exit(0)
if os.environ.get("FAKE_SUBMIT_STATUS"):
    sys.exit(int(os.environ["FAKE_SUBMIT_STATUS"]))
assert "--background" in args
assert "--timeout" in args
artifacts = store / "artifacts"
artifacts.mkdir()
scratch = store / "scratch"
scratch.mkdir()
env = dict(os.environ, REXEC_ARTIFACTS=str(artifacts), TMPDIR=str(scratch))
workspace = store / "workspace"
shutil.copytree(pathlib.Path.cwd(), workspace, ignore=None if "--with-git" in args else shutil.ignore_patterns(".git"))
with (store / "execution.out").open("wb") as out, (store / "execution.err").open("wb") as err:
    result = subprocess.run(["bash", "-c", args[-1]], cwd=workspace, env=env, stdout=out, stderr=err)
(store / "exit").write_text(str(result.returncode))
if os.environ.get("FAKE_CORRUPT_STATUS"):
    (artifacts / "status.json").write_text('{"status":true,"thread_id":"thread_fake"}')
if os.environ.get("FAKE_CONSULT_PATCH"):
    (artifacts / "changes.patch").write_text("unexpected patch")
if os.environ.get("FAKE_INVALID_UTF8"):
    (artifacts / "response.md").write_bytes(b"\xff")
print(json.dumps({"job_id": os.environ.get("FAKE_JOB_ID", "j_fake")}))
'''

FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
pathlib.Path(os.environ["FAKE_STORE"], "codex-args.json").write_text(json.dumps(args))
pathlib.Path(os.environ["FAKE_STORE"], "prompt.txt").write_text(sys.stdin.read())
output = pathlib.Path(args[args.index("-o") + 1])
output.write_text("A safe response.\n")
if "sandbox_mode=workspace-write" in args:
    pathlib.Path("example.txt").write_text("after\n")
print(json.dumps({"type": "thread.started", "thread_id": "thread_fake"}), flush=True)
print("PRIVATE_JSONL_MARKER", flush=True)
print("PRIVATE_STDERR_MARKER", file=sys.stderr, flush=True)
if os.environ.get("FAKE_LARGE_LOGS"):
    sys.stdout.write("x" * (5 * 1024 * 1024))
    sys.stderr.write("y" * (5 * 1024 * 1024))
sys.exit(int(os.environ.get("FAKE_CODEX_STATUS", "0")))
'''


class ConsumerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="delegate-consumer-")
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = self.root / "private-store"
        self.store.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, source in (("rexec", FAKE_REXEC), ("codex", FAKE_CODEX)):
            executable = self.bin / name
            executable.write_text(source)
            executable.chmod(0o700)
        self.prompt = self.project / "handoff ' $(touch INJECTED); `touch ALSO_INJECTED`.md"
        self.prompt.write_text("Objective: read this literal handoff.\n")
        (self.project / "example.txt").write_text("before\n")
        self.output = self.root / "output"
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_STORE=str(self.store))
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CEILING_DIRECTORIES=str(self.root))
        for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(variable, None)

    def tearDown(self):
        self.temporary.cleanup()

    def run_delegate(self, *args, **environment):
        return subprocess.run(
            ["bash", str(DELEGATE), "--prompt-file", str(self.prompt), "--output-dir", str(self.output), *args],
            cwd=self.project, env=dict(self.env, **environment), text=True, capture_output=True,
        )

    def calls(self):
        return [json.loads(line) for line in (self.store / "calls.jsonl").read_text().splitlines()]

    def test_consult_collects_only_text_artifacts_and_quotes_literal_path(self):
        result = self.run_delegate("--with-git", "--model", "chosen-model", "--effort", "high", "--resume", "thread_previous")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.project / "INJECTED").exists())
        self.assertFalse((self.project / "ALSO_INJECTED").exists())
        self.assertIn(self.prompt.read_text(), (self.store / "prompt.txt").read_text())
        calls = self.calls()
        self.assertEqual(calls[0][:-1], ["--background", "--timeout", "1800", "--with-git"])
        self.assertEqual(calls[1], ["wait", "j_fake"])
        self.assertEqual(calls[2], ["artifacts", "j_fake", "--into", str(self.output)])
        args = json.loads((self.store / "codex-args.json").read_text())
        self.assertEqual(args[:2], ["exec", "resume"])
        self.assertIn("sandbox_mode=read-only", args)
        self.assertIn("model_reasoning_effort=high", args)
        self.assertIn("chosen-model", args)
        self.assertIn("thread_previous", args)
        self.assertEqual((self.output / "changes.patch").read_text(), "")
        self.assertEqual(json.loads((self.output / "status.json").read_text()), {"status": 0, "thread_id": "thread_fake"})
        returned = result.stdout + result.stderr + "".join(path.read_text() for path in self.output.iterdir())
        self.assertNotIn("PRIVATE_JSONL_MARKER", returned)
        self.assertNotIn("PRIVATE_STDERR_MARKER", returned)
        self.assertEqual({path.name for path in self.output.iterdir()}, {"response.md", "changes.patch", "status.json", "acceptance.json", "wait.json"})
        private_logs = list((self.store / "scratch").glob("delegate-private.*/codex.*"))
        self.assertEqual(len(private_logs), 2)
        for log in private_logs:
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_implement_patch_is_valid_and_not_applied_to_caller(self):
        result = self.run_delegate("--mode", "implement")
        self.assertEqual(result.returncode, 0, result.stderr)
        patch = (self.output / "changes.patch").read_text()
        self.assertIn("-before", patch)
        self.assertIn("+after", patch)
        check = subprocess.run(["git", "apply", "--check", str(self.output / "changes.patch")], cwd=self.project, capture_output=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual((self.project / "example.txt").read_text(), "before\n")

    def test_codex_failure_keeps_response_and_returns_actual_exit(self):
        result = self.run_delegate(FAKE_CODEX_STATUS="23")
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertTrue((self.output / "response.md").is_file())
        self.assertIn("STATUS=23", result.stdout)

    def test_pending_wait_preserves_job_and_does_not_fetch(self):
        result = self.run_delegate(FAKE_WAIT_STATUS="75", FAKE_WAIT_PENDING="1")
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn("JOB_ID=j_fake", result.stdout)
        self.assertIn("remains durable", result.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_timeout_and_cancel_are_preserved_when_artifacts_unavailable(self):
        for status in ("124", "125"):
            with self.subTest(status=status):
                if self.output.exists():
                    shutil.rmtree(self.output)
                for path in self.store.iterdir():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                result = self.run_delegate(FAKE_WAIT_STATUS=status, FAKE_ARTIFACT_FAIL="1")
                self.assertEqual(result.returncode, int(status), result.stderr)
                self.assertIn("raw logs are not a fallback", result.stderr)

    def test_artifact_refusal_has_no_raw_fallback(self):
        result = self.run_delegate(FAKE_ARTIFACT_FAIL="1")
        self.assertEqual(result.returncode, 74, result.stderr)
        self.assertEqual(len(self.calls()), 3)
        self.assertNotIn("PRIVATE_", result.stdout + result.stderr)
        self.assertFalse((self.output / "codex.jsonl").exists())

    def test_invalid_artifacts_are_rejected(self):
        for flag in ("FAKE_CORRUPT_STATUS", "FAKE_CONSULT_PATCH", "FAKE_INVALID_UTF8"):
            with self.subTest(flag=flag):
                if self.output.exists():
                    shutil.rmtree(self.output)
                for path in self.store.iterdir():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                result = self.run_delegate(**{flag: "1"})
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("invalid or incomplete text artifacts", result.stderr)

    def test_invalid_job_identifier_is_not_used_as_a_command(self):
        result = self.run_delegate(FAKE_JOB_ID="j_fake;touch INJECTED")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertFalse((self.project / "INJECTED").exists())

    def test_legacy_target_and_invalid_timeout_are_rejected_before_submission(self):
        for args in (("--mac", "other"), ("--timeout-seconds", "0"), ("--timeout-seconds", "86401"), ("--timeout-seconds", "9999999999999999999999")):
            with self.subTest(args=args):
                result = self.run_delegate(*args)
                self.assertEqual(result.returncode, 1)
                self.assertFalse((self.store / "calls.jsonl").exists())

    def test_program_exits_matching_wait_codes_still_collect_artifacts(self):
        for status in ("75", "130", "143"):
            with self.subTest(status=status):
                if self.output.exists():
                    shutil.rmtree(self.output)
                for path in self.store.iterdir():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                result = self.run_delegate(FAKE_CODEX_STATUS=status)
                self.assertEqual(result.returncode, int(status), result.stderr)
                self.assertEqual(len(self.calls()), 3)
                self.assertTrue((self.output / "response.md").is_file())

    def test_interrupted_wait_returns_recovery_id_without_cancel(self):
        result = self.run_delegate(FAKE_INTERRUPT_WAIT="1")
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertIn("JOB_ID=j_fake", result.stdout)
        self.assertIn("remains durable", result.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_unknown_execution_is_not_resubmitted_or_exported(self):
        result = self.run_delegate(FAKE_WAIT_STATUS="70", FAKE_WAIT_OUTCOME="unknown")
        self.assertEqual(result.returncode, 70, result.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn("unknown", result.stderr)

    def test_private_logs_are_capped_and_fully_drained(self):
        result = self.run_delegate(FAKE_LARGE_LOGS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        for log in (self.store / "scratch").glob("delegate-private.*/codex.*"):
            self.assertLessEqual(log.stat().st_size, 4 * 1024 * 1024)
            self.assertTrue(log.read_bytes().endswith(b"[delegate log truncated]\n"))
        self.assertEqual((self.store / "execution.out").read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
