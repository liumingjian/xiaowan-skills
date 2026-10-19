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
            {"repo": str(self.repo), "tickets": [{"id": "T1", "title": "t", "footprint": [{"path": "a.py", "kind": "semantic", "group": 3}]}]},
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

    def test_oversized_ticket_is_split_by_directory_with_an_estimate_per_part(self):
        self.write("api/a.py", 90000)
        self.write("api/b.py", 30000)
        self.write("web/c.py", 80000)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": UNIT,
            "tickets": [{"id": "T1", "title": "Big", "footprint": [
                {"path": "web/c.py", "kind": "semantic"},
                {"path": "api/a.py", "kind": "semantic"},
                {"path": "api/b.py", "kind": "semantic"},
            ]}],
        })
        self.assertEqual(code, 0)
        [ticket] = out["tickets"]
        self.assertEqual(ticket["tier"], "oversized")
        self.assertEqual(ticket["split"]["by"], "directory")
        self.assertEqual(ticket["split"]["parts"], [
            {"id": "T1.1", "groups": ["api"], "paths": ["api/a.py", "api/b.py"],
             "semantic_bytes": 120000, "mechanical_files": 0, "estimate": 120000, "tier": "fits"},
            {"id": "T1.2", "groups": ["web"], "paths": ["web/c.py"],
             "semantic_bytes": 80000, "mechanical_files": 0, "estimate": 80000, "tier": "fits"},
        ])

    def test_small_groups_are_packed_together_in_order_until_the_budget(self):
        for name, size in [("a/x.py", 60000), ("b/x.py", 60000), ("c/x.py", 60000), ("d/x.py", 60000), ("e/x.py", 60000)]:
            self.write(name, size)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": UNIT,
            "tickets": [{"id": "T1", "title": "Big", "footprint": [
                {"path": p, "kind": "semantic"} for p in ["e/x.py", "d/x.py", "c/x.py", "b/x.py", "a/x.py"]]}],
        })
        self.assertEqual(code, 0)
        [ticket] = out["tickets"]
        self.assertEqual(ticket["tier"], "must_split")
        self.assertEqual([(p["groups"], p["estimate"]) for p in ticket["split"]["parts"]], [
            (["a", "b"], 120000), (["c", "d"], 120000), (["e"], 60000)])

    def test_tagged_groups_drive_the_split_and_an_oversized_group_splits_by_file(self):
        self.write("src/model.py", 100000)
        self.write("src/view.py", 70000)
        self.write("tests/test_model.py", 20000)
        self.write("src/huge1.py", 100000)
        self.write("src/huge2.py", 100000)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": {"base": 10000, "k_semantic": 1, "k_mechanical": 0},
            "tickets": [{"id": "#7", "title": "Big", "footprint": [
                {"path": "src/model.py", "kind": "semantic", "group": "model"},
                {"path": "tests/test_model.py", "kind": "semantic", "group": "model"},
                {"path": "src/view.py", "kind": "semantic", "group": "view"},
                {"path": "src/huge2.py", "kind": "semantic", "group": "export"},
                {"path": "src/huge1.py", "kind": "semantic", "group": "export"},
            ]}],
        })
        self.assertEqual(code, 0)
        [ticket] = out["tickets"]
        self.assertEqual(ticket["split"]["by"], "group")
        self.assertEqual([(p["id"], p["groups"], p["paths"], p["estimate"]) for p in ticket["split"]["parts"]], [
            ("#7.1", ["export"], ["src/huge1.py"], 110000),
            ("#7.2", ["export"], ["src/huge2.py"], 110000),
            ("#7.3", ["model"], ["src/model.py", "tests/test_model.py"], 130000),
            ("#7.4", ["view"], ["src/view.py"], 80000),
        ])

    def test_tickets_within_budget_get_no_split(self):
        self.write("a/x.py", 150000)
        self.write("b/y.py", 10)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": UNIT,
            "tickets": [
                {"id": "T1", "title": "t", "footprint": [{"path": "a/x.py", "kind": "semantic"}]},
                {"id": "T2", "title": "t", "footprint": [{"path": "b/y.py", "kind": "semantic"}]},
            ],
        })
        self.assertEqual(code, 0)
        self.assertEqual([t["split"] for t in out["tickets"]], [None, None])

    def merge_request(self, a, b):
        return {"repo": str(self.repo), "coefficients": UNIT, "tickets": [a, b]}

    def test_merge_is_proposed_for_undersized_tickets_adjacent_on_a_blocking_chain(self):
        self.write("a.py", 20000)
        self.write("b.py", 25000)
        code, out = self.estimate(self.merge_request(
            {"id": "#1", "title": "t", "footprint": [{"path": "a.py", "kind": "semantic"}]},
            {"id": "#2", "title": "t", "blocked_by": ["#1"], "footprint": [{"path": "b.py", "kind": "semantic"}]},
        ))
        self.assertEqual(code, 0)
        self.assertEqual(out["merges"], [{
            "tickets": ["#1", "#2"], "reasons": ["blocking"], "paths": ["a.py", "b.py"],
            "semantic_bytes": 45000, "mechanical_files": 0, "estimate": 45000, "tier": "undersized",
        }])

    def test_merge_is_proposed_for_undersized_tickets_sharing_files_counted_once(self):
        self.write("shared.py", 30000)
        self.write("a.py", 10000)
        self.write("b.py", 10000)
        code, out = self.estimate(self.merge_request(
            {"id": "#1", "title": "t", "footprint": [{"path": "shared.py", "kind": "semantic"}, {"path": "a.py", "kind": "semantic"}]},
            {"id": "#2", "title": "t", "footprint": [{"path": "b.py", "kind": "semantic"}, {"path": "shared.py", "kind": "semantic"}]},
        ))
        self.assertEqual(code, 0)
        [merge] = out["merges"]
        self.assertEqual(merge["tickets"], ["#1", "#2"])
        self.assertEqual(merge["reasons"], ["shared_files"])
        self.assertEqual(merge["estimate"], 50000)  # shared.py once: 30000 + 10000 + 10000
        self.assertEqual(merge["tier"], "fits")

    def test_no_merge_when_any_one_condition_fails(self):
        self.write("small1.py", 20000)
        self.write("small2.py", 25000)
        self.write("medium.py", 60000)
        self.write("big1.py", 140000)
        self.write("big2.py", 140000)
        cases = {
            # adjacent, union within budget, but one side fits rather than undersized
            "not_both_undersized": (UNIT,
                {"id": "#1", "title": "t", "footprint": [{"path": "small1.py", "kind": "semantic"}]},
                {"id": "#2", "title": "t", "blocked_by": ["#1"], "footprint": [{"path": "medium.py", "kind": "semantic"}]}),
            # both undersized, union within budget, but neither adjacent nor sharing files
            "unrelated": (UNIT,
                {"id": "#1", "title": "t", "footprint": [{"path": "small1.py", "kind": "semantic"}]},
                {"id": "#2", "title": "t", "footprint": [{"path": "small2.py", "kind": "semantic"}]}),
            # both undersized and adjacent, but the recomputed union is over budget.
            # With a non-negative base two undersized tickets always fit together, so a
            # negative base stands in for whatever term (offset, rule) could break that.
            "union_over_budget": ({"base": -100000, "k_semantic": 1, "k_mechanical": 0},
                {"id": "#1", "title": "t", "footprint": [{"path": "big1.py", "kind": "semantic"}]},
                {"id": "#2", "title": "t", "blocked_by": ["#1"], "footprint": [{"path": "big2.py", "kind": "semantic"}]}),
        }
        for name, (coefficients, a, b) in cases.items():
            with self.subTest(name):
                request = self.merge_request(a, b)
                request["coefficients"] = coefficients
                code, out = self.estimate(request)
                self.assertEqual(code, 0)
                self.assertEqual(out["merges"], [])

    def test_merge_pairs_follow_input_order_and_each_pair_appears_once(self):
        for name in ("a.py", "b.py", "c.py"):
            self.write(name, 10000)
        code, out = self.estimate({"repo": str(self.repo), "coefficients": UNIT, "tickets": [
            {"id": "#3", "title": "t", "blocked_by": ["#2"], "footprint": [{"path": "c.py", "kind": "semantic"}]},
            {"id": "#1", "title": "t", "footprint": [{"path": "a.py", "kind": "semantic"}]},
            {"id": "#2", "title": "t", "blocked_by": ["#1"], "footprint": [{"path": "b.py", "kind": "semantic"}, {"path": "a.py", "kind": "semantic"}]},
        ]})
        self.assertEqual(code, 0)
        self.assertEqual([(m["tickets"], m["reasons"]) for m in out["merges"]], [
            (["#3", "#2"], ["blocking"]),
            (["#1", "#2"], ["blocking", "shared_files"]),
        ])

    def test_breakdown_names_the_three_most_expensive_groups(self):
        self.write("api/a.py", 30000)
        self.write("api/b.py", 50000)
        self.write("web/c.py", 70000)
        self.write("lib/d.py", 1000)
        self.write("docs/e.md", 500)
        for n in range(4):
            self.write(f"pkg/m{n}.py", 999999)
        code, out = self.estimate({
            "repo": str(self.repo),
            "coefficients": {"base": 30000, "k_semantic": 1, "k_mechanical": 2000},
            "tickets": [{"id": "T1", "title": "t", "footprint": [
                {"path": "lib/d.py", "kind": "semantic"},
                {"path": "docs/e.md", "kind": "semantic"},
                {"path": "web/c.py", "kind": "semantic"},
                {"path": "api/a.py", "kind": "semantic"},
                {"path": "api/b.py", "kind": "semantic"},
            ] + [{"path": f"pkg/m{n}.py", "kind": "mechanical"} for n in range(4)]}],
        })
        self.assertEqual(code, 0)
        self.assertEqual(out["tickets"][0]["breakdown"], [
            {"group": "api", "tokens": 80000, "files": 2, "largest": "api/b.py"},
            {"group": "web", "tokens": 70000, "files": 1, "largest": "web/c.py"},
            {"group": "pkg", "tokens": 8000, "files": 4, "largest": "pkg/m0.py"},
        ])

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

    def test_the_repo_offset_and_enabled_term_rules_are_added_to_every_estimate(self):
        self.write("app/models.py", 40000)
        self.write("app/migrations/0001_a.py", 1000)
        self.write("app/migrations/0002_b.py", 1000)
        rule = {"id": "migrations", "kind": "term", "enabled": True, "text": "Migrations cost 15k each.",
                "match": "*/migrations/*.py", "tokens": 15000,
                "cites": ["github.com/example/app#2"], "rows": {"github.com/example/app#2": {"units": 2}}}
        off = dict(rule, id="fixtures", enabled=False, match="*.py")
        tagging = {"id": "generated", "kind": "tagging", "enabled": True, "text": "Generated code is mechanical.",
                   "match": "*.py", "cites": ["github.com/example/app#3"], "rows": {"github.com/example/app#3": None}}
        code, out = self.estimate({
            "repo": str(self.repo), "remote": "github.com/example/app",
            "coefficients": UNIT, "offsets": {"github.com/example/app": 10000, "github.com/example/other": 99999},
            "rules": [rule, off, tagging],
            "tickets": [{"id": "T1", "title": "Add a field", "footprint": [
                {"path": "app/models.py", "kind": "semantic"},
                {"path": "app/migrations/0001_a.py", "kind": "semantic"},
                {"path": "app/migrations/0002_b.py", "kind": "mechanical"},
            ]}],
        })
        self.assertEqual(code, 0)
        [ticket] = out["tickets"]
        self.assertEqual(ticket["estimate"], 41000 + 10000 + 30000)
        self.assertEqual(ticket["offset"], 10000)
        self.assertEqual(ticket["terms"], [{"rule": "migrations", "units": 2, "tokens": 30000}])
        self.assertEqual(out["remote"], "github.com/example/app")

    def test_no_remote_or_an_unknown_remote_gets_no_offset(self):
        self.write("a.py", 60000)
        for remote in (None, "github.com/example/unknown"):
            request = {"repo": str(self.repo), "coefficients": UNIT, "offsets": {"github.com/example/app": 10000},
                       "tickets": [{"id": "T1", "footprint": [{"path": "a.py", "kind": "semantic"}]}]}
            if remote:
                request["remote"] = remote
            code, out = self.estimate(request)
            self.assertEqual((code, out["tickets"][0]["estimate"], out["tickets"][0]["offset"]), (0, 60000, 0))


if __name__ == "__main__":
    unittest.main()
