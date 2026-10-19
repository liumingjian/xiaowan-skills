import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"

# Unit coefficients make an estimate equal to semantic bytes, so tier edges
# can be written as plain byte counts against the 150k budget.
UNIT = {"base": 0, "k_semantic": 1, "k_mechanical": 0}


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="size-tickets-test-")
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, size):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    def estimate(self, request):
        env = dict(os.environ, PYTHONPATH=str(RUNTIME))
        result = subprocess.run(
            [sys.executable, "-m", "size_tickets_runtime", "estimate", "-"],
            input=json.dumps(request).encode(), env=env, capture_output=True,
        )
        return result.returncode, json.loads(result.stdout)

    def test_semantic_bytes_are_read_from_the_repo_and_tiered(self):
        self.write("src/a.py", 60000)
        self.write("src/b.py", 40000)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": UNIT,
            "tickets": [{"id": "T1", "title": "Add a", "footprint": [
                {"path": "src/a.py", "kind": "semantic"},
                {"path": "src/b.py", "kind": "semantic"},
            ]}],
        })
        self.assertEqual(code, 0)
        [ticket] = out["tickets"]
        self.assertEqual(ticket["id"], "T1")
        self.assertEqual(ticket["semantic_bytes"], 100000)
        self.assertEqual(ticket["estimate"], 100000)
        self.assertEqual(ticket["tier"], "fits")

    def test_tier_edges_against_the_150k_budget(self):
        edges = {
            49999: "undersized",   # below a third of the budget
            50000: "fits",
            150000: "fits",        # at the budget still fits
            150001: "oversized",
            299999: "oversized",
            300000: "must_split",  # twice the budget or more
        }
        tickets = []
        for size in edges:
            self.write(f"f{size}.py", size)
            tickets.append({"id": str(size), "title": "t", "footprint": [{"path": f"f{size}.py", "kind": "semantic"}]})
        code, out = self.estimate({"repo": str(self.repo), "coefficients": UNIT, "tickets": tickets})
        self.assertEqual(code, 0)
        self.assertEqual(out["budget"], 150000)
        self.assertEqual({t["id"]: t["tier"] for t in out["tickets"]}, {str(k): v for k, v in edges.items()})

    def test_mechanical_files_count_by_number_not_bytes(self):
        self.write("big_semantic.py", 1000)
        self.write("rename1.py", 900000)
        self.write("rename2.py", 900000)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": {"base": 10000, "k_semantic": 2, "k_mechanical": 500},
            "tickets": [{"id": "T1", "title": "Rename", "footprint": [
                {"path": "big_semantic.py", "kind": "semantic"},
                {"path": "rename1.py", "kind": "mechanical"},
                {"path": "rename2.py", "kind": "mechanical"},
            ]}],
        })
        self.assertEqual(code, 0)
        [ticket] = out["tickets"]
        self.assertEqual(ticket["semantic_bytes"], 1000)
        self.assertEqual(ticket["mechanical_files"], 2)
        self.assertEqual(ticket["estimate"], 13000)  # 10000 + 2*1000 + 500*2
        self.assertEqual(ticket["tier"], "undersized")

    def test_shipped_coefficients_are_reported_as_uncalibrated(self):
        self.write("a.py", 100)
        code, out = self.estimate({
            "repo": str(self.repo),
            "tickets": [{"id": "T1", "title": "t", "footprint": [{"path": "a.py", "kind": "semantic"}]}],
        })
        self.assertEqual(code, 0)
        self.assertIs(out["calibrated"], False)
        self.assertEqual(out["coefficients_source"], "shipped")
        self.assertEqual(set(out["coefficients"]), {"base", "k_semantic", "k_mechanical"})

    def test_input_coefficients_are_echoed_as_input(self):
        code, out = self.estimate({"repo": str(self.repo), "coefficients": UNIT, "tickets": []})
        self.assertEqual(code, 0)
        self.assertEqual(out["coefficients_source"], "input")
        self.assertEqual(out["coefficients"], UNIT)

    def test_files_the_ticket_creates_count_zero_bytes_and_are_flagged(self):
        self.write("old.py", 700)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": UNIT,
            "tickets": [{"id": "T1", "title": "t", "footprint": [
                {"path": "old.py", "kind": "semantic"},
                {"path": "new_module.py", "kind": "semantic"},
            ]}],
        })
        self.assertEqual(code, 0)
        [ticket] = out["tickets"]
        self.assertEqual(ticket["estimate"], 700)
        self.assertEqual(ticket["files"], [
            {"path": "old.py", "kind": "semantic", "bytes": 700, "exists": True},
            {"path": "new_module.py", "kind": "semantic", "bytes": 0, "exists": False},
        ])

    def test_reads_the_request_from_a_file_path(self):
        self.write("a.py", 10)
        request = Path(self.temp.name) / "request.json"
        request.write_text(json.dumps({"repo": str(self.repo), "coefficients": UNIT, "tickets": [
            {"id": "T1", "title": "t", "footprint": [{"path": "a.py", "kind": "semantic"}]}]}))
        env = dict(os.environ, PYTHONPATH=str(RUNTIME))
        result = subprocess.run([sys.executable, "-m", "size_tickets_runtime", "estimate", str(request)], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["tickets"][0]["estimate"], 10)

    def test_the_shipped_wrapper_runs_estimate(self):
        self.write("a.py", 10)
        wrapper = Path(__file__).resolve().parents[1] / "bin" / "size-tickets"
        request = json.dumps({"repo": str(self.repo), "coefficients": UNIT, "tickets": [
            {"id": "T1", "title": "t", "footprint": [{"path": "a.py", "kind": "semantic"}]}]})
        result = subprocess.run([str(wrapper), "estimate", "-"], input=request.encode(), capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["tickets"][0]["tier"], "undersized")

    def test_invalid_requests_are_refused_with_exit_2(self):
        (Path(self.temp.name) / "outside.py").write_bytes(b"x")
        bad = [
            {"tickets": []},                                                     # no repo
            {"repo": str(self.repo), "tickets": [{"id": "T1", "title": "t", "footprint": [{"path": "a.py", "kind": "vibes"}]}]},
            {"repo": str(self.repo), "tickets": [{"id": "T1", "title": "t", "footprint": [{"path": "../outside.py", "kind": "semantic"}]}]},
            {"repo": str(self.repo), "tickets": [{"title": "no id", "footprint": []}]},
        ]
        for request in bad:
            with self.subTest(request=request):
                code, out = self.estimate(request)
                self.assertEqual(code, 2)
                self.assertEqual(out["error"], "INVALID_REQUEST")

    def test_unparseable_json_is_refused_with_exit_2(self):
        env = dict(os.environ, PYTHONPATH=str(RUNTIME))
        result = subprocess.run([sys.executable, "-m", "size_tickets_runtime", "estimate", "-"], input=b"{not json", env=env, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {"error": "INVALID_REQUEST"})

    def test_human_tickets_are_skipped_and_listed(self):
        self.write("a.py", 100)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": UNIT,
            "tickets": [
                {"id": "#1", "title": "Agent work", "footprint": [{"path": "a.py", "kind": "semantic"}]},
                {"id": "#2", "title": "Rotate prod secret", "human": True, "footprint": []},
                {"id": "#3", "title": "Approve design", "labels": ["ready-for-human"], "footprint": [{"path": "a.py", "kind": "semantic"}]},
            ],
        })
        self.assertEqual(code, 0)
        self.assertEqual([t["id"] for t in out["tickets"]], ["#1"])
        self.assertEqual(out["skipped"], [
            {"id": "#2", "title": "Rotate prod secret", "reason": "human"},
            {"id": "#3", "title": "Approve design", "reason": "human"},
        ])


if __name__ == "__main__":
    unittest.main()
