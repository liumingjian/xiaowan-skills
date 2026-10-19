import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Fixtures are excerpts cut from real reimburse-ai session logs, with the real
# usage numbers kept, so the expected peaks below are the measured ones.


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="size-tickets-test-")
        self.logs = Path(self.temp.name) / "projects"
        self.logs.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def place(self, fixture, relative):
        """Put a fixture into the log tree at a Claude Code-shaped path."""
        path = self.logs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / fixture, path)
        return path

    def place_with_prompt(self, fixture, relative, prompt):
        """A copy of a fixture whose opening prompt is replaced (a relabelled real log)."""
        path = self.place(fixture, relative)
        lines = path.read_text(encoding="utf-8").splitlines()
        opening = json.loads(lines[0])
        opening["message"]["content"] = prompt
        lines[0] = json.dumps(opening, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def measure(self, *words):
        env = dict(os.environ, PYTHONPATH=str(RUNTIME))
        result = subprocess.run(
            [sys.executable, "-m", "size_tickets_runtime", "measure", *words],
            env=env, capture_output=True,
        )
        return result.returncode, json.loads(result.stdout)

    def test_implementer_subagent_is_matched_by_its_own_ticket_not_the_spec(self):
        # The prompt names spec #412 before its ticket #422; only tickets are requested.
        log = self.place("implementer-prompt.jsonl", "-repo-wt/sess-1/subagents/agent-a57.jsonl")
        code, out = self.measure("--logs", str(self.logs), "#422", "423")
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"], [
            {"ticket": 422, "peak": 105965, "compacted": False, "session": str(log)},
        ])
        self.assertEqual(out["unmatched"], [423])
        self.assertEqual(out["skipped"], [])

    def test_session_that_worked_on_several_tickets_is_skipped(self):
        # A code review whose first sentence lists tickets #407 #408 #409.
        log = self.place("multi-ticket-session.jsonl", "-repo/sess-2/subagents/agent-a6c.jsonl")
        code, out = self.measure("--logs", str(self.logs), "407", "408", "409")
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"], [])
        self.assertEqual(out["unmatched"], [407, 408, 409])
        self.assertEqual(out["skipped"], [
            {"session": str(log), "tickets": [407, 408, 409], "reason": "multi_ticket", "peak": 93327},
        ])

    def test_other_roles_naming_the_ticket_are_skipped_as_not_implementers(self):
        implementer = self.place("implementer-prompt.jsonl", "-repo/sess-3/subagents/agent-impl.jsonl")
        # The merger prompt shape seen in real logs, on a copy of the implementer's turns.
        merger = self.place_with_prompt(
            "implementer-prompt.jsonl", "-repo/sess-3/subagents/agent-merge.jsonl",
            "You are the merger for spec #412 in liumingjian/reimburse-ai. Merge branch spec-412/422-pairing-endpoint (ticket #422).",
        )
        code, out = self.measure("--logs", str(self.logs), "422")
        self.assertEqual(code, 0)
        self.assertEqual([(t["ticket"], t["session"]) for t in out["tickets"]], [(422, str(implementer))])
        self.assertEqual(out["skipped"], [
            {"session": str(merger), "tickets": [422], "reason": "not_implementer", "peak": 105965},
        ])

    def test_hand_opened_top_level_session_is_matched_by_issue_url(self):
        # Real log: "开始实现 https://github.com/liumingjian/reimburse-ai/issues/406" ("start
        # implementing"), a Chinese prompt with no sentence end. 406 is a spec in real life;
        # it stands in for a ticket here because no hand-opened ticket session exists.
        log = self.place("hand-opened-prompt.jsonl", "-home-agent-repos-reimburse-ai/6420531b.jsonl")
        code, out = self.measure("--logs", str(self.logs), "406")
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"], [
            {"ticket": 406, "peak": 185215, "compacted": False, "session": str(log)},
        ])
        self.assertEqual(out["skipped"], [])

    def test_compacted_session_is_flagged(self):
        # Real /implement-spec slash-command session with two compact_boundary records.
        log = self.place("compacted-session.jsonl", "-repo-wt/42e47119.jsonl")
        code, out = self.measure("--logs", str(self.logs), "412")
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"], [
            {"ticket": 412, "peak": 274097, "compacted": True, "session": str(log)},
        ])

    def test_turns_without_usage_are_ignored_and_a_live_tail_is_tolerated(self):
        # Real #436 implementer: ends with a <synthetic> rate_limit record whose usage is all zero.
        log = self.place("no-usage-turns.jsonl", "-repo/sess-4/subagents/agent-a27.jsonl")
        with open(log, "a", encoding="utf-8") as tail:
            tail.write('{"type":"assistant","message":{"usage":{"input_tok')  # still being written
        code, out = self.measure("--logs", str(self.logs), "436")
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"], [
            {"ticket": 436, "peak": 656849, "compacted": False, "session": str(log)},
        ])

    def test_session_with_no_usable_usage_is_skipped(self):
        # The #436 implementer cut down to its prompt, tool output and the zero-usage record:
        # the shape of a session that hit the rate limit before its first real turn.
        log = self.place("no-usage-turns.jsonl", "-repo/sess-5/subagents/agent-a27.jsonl")
        kept = [line for line in log.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["type"] != "assistant" or json.loads(line)["message"]["model"] == "<synthetic>"]
        log.write_text("\n".join(kept) + "\n", encoding="utf-8")
        code, out = self.measure("--logs", str(self.logs), "436")
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"], [])
        self.assertEqual(out["unmatched"], [436])
        self.assertEqual(out["skipped"], [
            {"session": str(log), "tickets": [436], "reason": "no_usage", "peak": 0},
        ])

    def test_several_log_dirs_are_searched_and_the_largest_implementer_wins(self):
        # Worktrees get their own project dir, so one ticket's sessions can sit in two dirs.
        smaller = self.place("implementer-prompt.jsonl", "-repo/sess-6/subagents/agent-first.jsonl")
        other = Path(self.temp.name) / "other-projects"
        larger = other / "-repo-wt/sess-7/subagents/agent-retry.jsonl"
        larger.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURES / "no-usage-turns.jsonl", larger)
        lines = larger.read_text(encoding="utf-8").splitlines()
        opening = json.loads(lines[0])
        opening["message"]["content"] = "You are an implementer for ticket #422 of spec #412."
        larger.write_text("\n".join([json.dumps(opening)] + lines[1:]) + "\n", encoding="utf-8")
        code, out = self.measure("--logs", str(self.logs), "--logs", str(other), "422")
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"], [
            {"ticket": 422, "peak": 656849, "compacted": False, "session": str(larger)},
        ])
        self.assertEqual(out["skipped"], [
            {"session": str(smaller), "tickets": [422], "reason": "duplicate_implementer", "peak": 105965},
        ])

    def test_bad_input_is_refused_with_the_json_error_contract(self):
        for words in (["--logs", str(self.logs / "missing"), "422"], ["--logs", str(self.logs), "abc"], ["--logs", str(self.logs)]):
            code, out = self.measure(*words)
            self.assertEqual((code, out), (2, {"error": "INVALID_REQUEST"}), words)


if __name__ == "__main__":
    unittest.main()
