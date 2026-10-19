import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
RUNTIME = SKILL / "runtime"
FIXTURES = SKILL / "tests" / "fixtures"
SHIPPED_CONSTANTS = RUNTIME / "size_tickets_runtime" / "constants.py"
HEADER = "repo\tspec\tticket\testimate\tactual\tsemantic_bytes\tmechanical_files\tcompacted\tdate"
REPO = "github.com/example/app"
OTHER = "github.com/example/other"
SIZES = [100000, 200000, 50000, 400000, 10000, 300000]


def tsv_row(ticket, actual, semantic_bytes, mechanical_files=0, estimate=0, compacted=False, repo=REPO):
    return "\t".join(str(v) for v in [repo, 1, ticket, estimate, actual, semantic_bytes, mechanical_files,
                                       "true" if compacted else "false", "2026-10-19"])


def constants_text(base, k_semantic, k_mechanical, offsets=None, rules=None):
    """The shipped constants file with the given knowledge, whatever values it currently ships."""
    text = SHIPPED_CONSTANTS.read_text(encoding="utf-8")
    text = re.sub(r"^CALIBRATED = .*$", "CALIBRATED = False", text, count=1, flags=re.M)
    text = re.sub(r"^REPO_OFFSETS = \{\}$|^REPO_OFFSETS = \{.*?^\}$", "REPO_OFFSETS = {}", text, count=1, flags=re.M | re.S)
    text = re.sub(r"^RULES = \[\]$|^RULES = \[.*?^\]$", "RULES = []", text, count=1, flags=re.M | re.S)
    for name, value in (("base", base), ("k_semantic", k_semantic), ("k_mechanical", k_mechanical)):
        text, count = re.subn(rf'^(    "{name}": )[^,]+,', rf"\g<1>{value},", text, count=1, flags=re.M)
        assert count == 1, name
    if offsets is not None:
        text = text.replace("REPO_OFFSETS = {}", f"REPO_OFFSETS = {offsets!r}")
    if rules is not None:
        text = text.replace("RULES = []", f"RULES = {rules!r}")
    return text


def exact(ticket, semantic_bytes, extra=0, repo=REPO, mechanical_files=0):
    """A row whose actual peak is exactly 20000 + 0.3 * semantic bytes + extra."""
    return tsv_row(ticket, 20000 + semantic_bytes * 3 // 10 + extra, semantic_bytes, mechanical_files, repo=repo)


def read_constants(path):
    scope = {}
    exec(Path(path).read_text(encoding="utf-8"), scope)
    return scope


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="size-tickets-test-")
        self.dir = Path(self.temp.name)
        self.table = self.dir / "calibration.tsv"
        self.constants = self.dir / "constants.py"
        self.ship(30000, 0.5, 1500)

    def tearDown(self):
        self.temp.cleanup()

    def ship(self, base, k_semantic, k_mechanical, offsets=None, rules=None):
        self.constants.write_text(constants_text(base, k_semantic, k_mechanical, offsets, rules), encoding="utf-8")

    def rows(self, *lines):
        self.table.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")

    def backtest(self, *words):
        env = dict(os.environ, PYTHONPATH=str(RUNTIME))
        result = subprocess.run(
            [sys.executable, "-m", "size_tickets_runtime", "backtest",
             "--calibration", str(self.table), "--constants", str(self.constants), *words],
            env=env, capture_output=True, cwd=self.dir,
        )
        return result.returncode, json.loads(result.stdout)

    def test_refit_recovers_the_coefficients_that_generated_the_data(self):
        # actual = 20000 + 0.3 * semantic + 2000 * mechanical, exactly.
        self.rows(
            tsv_row(1, 20000 + 30000 + 0, 100000, 0),
            tsv_row(2, 20000 + 60000 + 4000, 200000, 2),
            tsv_row(3, 20000 + 15000 + 10000, 50000, 5),
            tsv_row(4, 20000 + 120000 + 2000, 400000, 1),
            tsv_row(5, 20000 + 3000 + 6000, 10000, 3),
        )
        code, out = self.backtest()
        self.assertEqual(code, 0)
        self.assertEqual(out["after"]["coefficients"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 2000})
        self.assertEqual(out["after"]["median_error"], 0)
        self.assertEqual(out["after"]["tier_accuracy"], 1)
        self.assertEqual(out["before"]["coefficients"], {"base": 30000, "k_semantic": 0.5, "k_mechanical": 1500})
        self.assertEqual(out["rows"], 5)
        self.assertEqual(out["verdict"], "adopt")
        self.assertEqual(out["reasons"], [])

    def test_before_is_scored_from_stored_footprints_without_the_repo_or_the_stored_estimate(self):
        # The repo is nowhere on disk and the stored estimate column is junk: only
        # semantic_bytes and mechanical_files, priced with the shipped constants, count.
        gone = "github.com/nowhere/missing"
        self.rows(
            tsv_row(1, 80000, 100000, 0, estimate=999999999, repo=gone),   # 80k, error 0, fits/fits
            tsv_row(2, 100000, 200000, 2, estimate=1, repo=gone),          # 133k, error 0.33, fits/fits
            tsv_row(3, 50000, 20000, 0, estimate=7, repo=gone),            # 40k, error 0.2, undersized/fits
        )
        code, out = self.backtest()
        self.assertEqual(code, 0)
        self.assertEqual(out["before"], {
            "coefficients": {"base": 30000, "k_semantic": 0.5, "k_mechanical": 1500}, "offsets": {}, "rules": [],
            "tier_accuracy": 0.6667, "median_error": 0.2, "within_50": 1.0,
        })

    def test_a_refit_that_raises_median_error_is_refused_and_writes_nothing(self):
        # Shipped constants are exact on three rows; two outliers drag any least-squares fit off them.
        self.rows(
            tsv_row(1, 80000, 100000),
            tsv_row(2, 130000, 200000),
            tsv_row(3, 50000, 40000),
            tsv_row(4, 400000, 10000),
            tsv_row(5, 40000, 300000),
        )
        before = self.constants.read_bytes()
        code, out = self.backtest("--adopt")
        self.assertEqual(code, 0)
        self.assertEqual(out["before"]["median_error"], 0)
        self.assertGreater(out["after"]["median_error"], 0)
        self.assertEqual(out["verdict"], "refuse")
        self.assertIn("median_error_rose", out["reasons"])
        self.assertFalse(out["written"])
        self.assertEqual(self.constants.read_bytes(), before)

    def test_too_few_rows_refuses_without_fitting(self):
        self.rows(tsv_row(1, 80000, 100000), tsv_row(2, 130000, 200000))
        code, out = self.backtest("--adopt")
        self.assertEqual(code, 0)
        self.assertEqual((out["verdict"], out["reasons"], out["after"], out["written"]),
                         ("refuse", ["too_few_rows"], None, False))

    def test_the_shipped_table_and_constants_agree(self):
        # The shipped coefficients are the backtest of the shipped table: rerunning it changes nothing.
        code, out = self.backtest("--calibration", str(SKILL / "calibration.tsv"),
                                  "--constants", str(SHIPPED_CONSTANTS))
        self.assertEqual(code, 0)
        self.assertGreaterEqual(out["rows"], 3)
        self.assertEqual((out["verdict"], out["reasons"], out["written"]), ("refuse", ["unchanged"], False))
        self.assertIs(read_constants(SHIPPED_CONSTANTS)["CALIBRATED"], True)

    def test_compacted_rows_are_excluded_because_their_peak_is_a_lower_bound(self):
        self.rows(
            tsv_row(1, 20000 + 30000, 100000),
            tsv_row(2, 20000 + 60000, 200000),
            tsv_row(3, 20000 + 15000, 50000),
            tsv_row(4, 5000, 400000, compacted=True),
        )
        code, out = self.backtest()
        self.assertEqual(out["rows"], 3)
        self.assertEqual(out["excluded"], [{"repo": REPO, "ticket": 4, "reason": "compacted"}])
        self.assertEqual(out["after"]["coefficients"]["base"], 20000)
        self.assertEqual(out["after"]["coefficients"]["k_semantic"], 0.3)

    def test_a_coefficient_no_row_informs_keeps_its_shipped_value(self):
        # No row has mechanical files, so the data says nothing about k_mechanical.
        self.rows(
            tsv_row(1, 20000 + 30000, 100000),
            tsv_row(2, 20000 + 60000, 200000),
            tsv_row(3, 20000 + 15000, 50000),
        )
        code, out = self.backtest()
        self.assertEqual(out["after"]["coefficients"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 1500})

    def test_fitted_coefficients_are_never_negative(self):
        # actual = 0.5 * semantic - 10000: an unconstrained fit would want base = -10000.
        self.rows(
            tsv_row(1, 40000, 100000),
            tsv_row(2, 90000, 200000),
            tsv_row(3, 140000, 300000),
            tsv_row(4, 190000, 400000),
        )
        code, out = self.backtest()
        after = out["after"]["coefficients"]
        self.assertEqual(after["base"], 0)
        self.assertGreater(after["k_semantic"], 0)
        self.assertTrue(all(value >= 0 for value in after.values()))

    def test_adopt_writes_the_refit_into_constants_and_a_rerun_finds_nothing_to_change(self):
        self.rows(
            tsv_row(1, 20000 + 30000 + 0, 100000, 0),
            tsv_row(2, 20000 + 60000 + 4000, 200000, 2),
            tsv_row(3, 20000 + 15000 + 10000, 50000, 5),
        )
        untouched = [line for line in self.constants.read_text(encoding="utf-8").splitlines()
                     if not line.startswith(("CALIBRATED", "COEFFICIENTS", "    \"", "}"))]
        code, out = self.backtest("--adopt")
        self.assertEqual((code, out["verdict"], out["written"]), (0, "adopt", True))
        shipped = read_constants(self.constants)
        self.assertIs(shipped["CALIBRATED"], True)
        self.assertEqual(shipped["COEFFICIENTS"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 2000})
        self.assertEqual(shipped["BUDGET"], 150000)
        self.assertEqual([line for line in self.constants.read_text(encoding="utf-8").splitlines()
                          if not line.startswith(("CALIBRATED", "COEFFICIENTS", "    \"", "}"))], untouched)
        written = self.constants.read_bytes()
        code, out = self.backtest("--adopt")
        self.assertEqual(out["before"]["coefficients"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 2000})
        self.assertEqual((out["verdict"], out["reasons"], out["written"]), ("refuse", ["unchanged"], False))
        self.assertEqual(self.constants.read_bytes(), written)

    def test_a_repo_with_five_rows_gets_an_offset_keyed_by_its_remote(self):
        # The largest repo is the reference the base is fitted to; the other runs 10k hotter.
        self.rows(*[exact(i, s) for i, s in enumerate(SIZES, 1)],
                  *[exact(10 + i, s, extra=10000, repo=OTHER) for i, s in enumerate(SIZES[:5], 1)])
        code, out = self.backtest()
        self.assertEqual(code, 0)
        self.assertEqual(out["after"]["coefficients"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 1500})
        self.assertEqual(out["after"]["offsets"], {OTHER: 10000})
        self.assertEqual(out["after"]["median_error"], 0)
        self.assertEqual(out["before"]["offsets"], {})
        self.assertEqual(out["repos"], [{"repo": REPO, "rows": 6, "offset": None},
                                        {"repo": OTHER, "rows": 5, "offset": 10000}])
        self.assertEqual(out["verdict"], "adopt")

    def test_a_repo_with_four_rows_gets_no_offset(self):
        self.rows(*[exact(i, s) for i, s in enumerate(SIZES, 1)],
                  *[exact(10 + i, s, extra=10000, repo=OTHER) for i, s in enumerate(SIZES[:4], 1)])
        code, out = self.backtest()
        self.assertEqual(code, 0)
        self.assertEqual(out["after"]["offsets"], {})
        self.assertEqual(out["repos"], [{"repo": REPO, "rows": 6, "offset": None},
                                        {"repo": OTHER, "rows": 4, "offset": None}])

    def test_a_single_repo_is_the_reference_and_gets_no_offset(self):
        self.rows(*[exact(i, s) for i, s in enumerate(SIZES, 1)])
        code, out = self.backtest()
        self.assertEqual(out["after"]["offsets"], {})
        self.assertEqual(out["repos"], [{"repo": REPO, "rows": 6, "offset": None}])

    def test_a_cost_term_rule_prices_its_rows_and_is_kept_with_its_citations(self):
        # Tickets 2 and 4 touched migrations, which cost 15k each beyond their bytes.
        rule = {"id": "migrations", "kind": "term", "enabled": True,
                "text": "Each migration file in the footprint costs 15k beyond its bytes.",
                "match": "*/migrations/*.py", "tokens": 15000,
                "cites": [f"{REPO}#2"], "rows": {f"{REPO}#2": {"units": 2}, f"{REPO}#4": {"units": 1}}}
        self.ship(30000, 0.5, 1500, rules=[rule])
        self.rows(exact(1, 100000), exact(2, 200000, extra=30000), exact(3, 50000),
                  exact(4, 400000, extra=15000), exact(5, 10000))
        code, out = self.backtest()
        self.assertEqual(code, 0)
        self.assertEqual(out["after"]["coefficients"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 1500})
        self.assertEqual(out["after"]["median_error"], 0)
        self.assertEqual(out["after"]["rules"], ["migrations"])
        [verdict] = out["rules"]
        self.assertEqual((verdict["id"], verdict["kind"], verdict["cites"], verdict["verdict"]),
                         ("migrations", "term", [f"{REPO}#2"], "keep"))
        self.assertGreater(verdict["without"]["median_error"], 0)

    def test_a_rule_whose_removal_changes_nothing_is_deleted_and_adopt_drops_it(self):
        useful = {"id": "migrations", "kind": "term", "enabled": True, "text": "Migrations cost 15k each.",
                  "match": "*/migrations/*.py", "tokens": 15000,
                  "cites": [f"{REPO}#2"], "rows": {f"{REPO}#2": {"units": 2}}}
        useless = {"id": "fixtures", "kind": "term", "enabled": True, "text": "Fixtures cost 8k each.",
                   "match": "*/fixtures/*", "tokens": 8000,
                   "cites": [f"{REPO}#3"], "rows": {f"{REPO}#3": {"units": 0}}}
        self.ship(30000, 0.5, 1500, rules=[useless, useful])
        self.rows(exact(1, 100000), exact(2, 200000, extra=30000), exact(3, 50000), exact(4, 400000), exact(5, 10000))
        code, out = self.backtest("--adopt")
        self.assertEqual(code, 0)
        self.assertEqual([(r["id"], r["verdict"]) for r in out["rules"]], [("fixtures", "delete"), ("migrations", "keep")])
        self.assertEqual(out["after"]["rules"], ["migrations"])
        self.assertEqual((out["verdict"], out["written"]), ("adopt", True))
        shipped = read_constants(self.constants)
        self.assertEqual(shipped["RULES"], [useful])
        self.assertEqual(shipped["COEFFICIENTS"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 1500})
        code, out = self.backtest()
        self.assertEqual((out["verdict"], out["reasons"]), ("refuse", ["unchanged"]))

    def tagging(self, rows):
        return {"id": "generated", "kind": "tagging", "enabled": True,
                "text": "Generated API clients are mechanical, not semantic.", "match": "*/generated/*",
                "cites": [f"{REPO}#2"], "rows": rows}

    def test_only_rows_a_new_tagging_rule_reclassifies_are_sent_for_re_exploration(self):
        # Tickets 2 and 4 stored generated clients as semantic bytes; the rule says they are
        # mechanical. #2 is re-explored already, #4 is not; no other row is touched.
        self.ship(30000, 0.5, 1500, rules=[self.tagging({
            f"{REPO}#2": {"semantic_bytes": 200000, "mechanical_files": 0}, f"{REPO}#4": None})])
        self.rows(exact(1, 100000), tsv_row(2, 80000, 900000), exact(3, 50000),
                  tsv_row(4, 140000, 700000), exact(5, 10000))
        before = self.constants.read_bytes()
        code, out = self.backtest("--adopt")
        self.assertEqual(code, 0)
        self.assertEqual(out["reexplore"], [{"repo": REPO, "ticket": 4, "rules": ["generated"]}])
        self.assertEqual((out["verdict"], out["reasons"], out["written"]), ("refuse", ["needs_reexploration"], False))
        self.assertEqual(self.constants.read_bytes(), before)

    def test_a_re_explored_tagging_rule_replaces_the_stored_footprint_of_its_rows(self):
        self.ship(30000, 0.5, 1500, rules=[self.tagging({
            f"{REPO}#2": {"semantic_bytes": 200000, "mechanical_files": 0},
            f"{REPO}#4": {"semantic_bytes": 400000, "mechanical_files": 0}})])
        self.rows(exact(1, 100000), tsv_row(2, 80000, 900000), exact(3, 50000),
                  tsv_row(4, 140000, 700000), exact(5, 10000))
        code, out = self.backtest()
        self.assertEqual(out["reexplore"], [])
        self.assertEqual(out["after"]["coefficients"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 1500})
        self.assertEqual(out["after"]["median_error"], 0)
        self.assertEqual([(r["id"], r["verdict"]) for r in out["rules"]], [("generated", "keep")])

    def migrations(self, enabled):
        return {"id": "migrations", "kind": "term", "enabled": enabled, "text": "Migrations cost 15k each.",
                "match": "*/migrations/*.py", "tokens": 15000,
                "cites": [f"{REPO}#2"], "rows": {f"{REPO}#2": {"units": 2}, f"{REPO}#4": {"units": 1}}}

    def migration_rows(self):
        self.rows(exact(1, 100000), exact(2, 200000, extra=30000), exact(3, 50000),
                  exact(4, 400000, extra=15000), exact(5, 10000))

    def test_toggling_off_a_rule_the_data_needs_is_refused_by_the_guard(self):
        self.ship(20000, 0.3, 1500, rules=[self.migrations(True)])
        self.migration_rows()
        code, out = self.backtest("--disable", "migrations", "--adopt")
        self.assertEqual(code, 0)
        self.assertEqual(out["before"]["rules"], ["migrations"])
        self.assertEqual(out["after"]["rules"], [])
        self.assertEqual(out["verdict"], "refuse")
        self.assertIn("median_error_rose", out["reasons"])
        self.assertFalse(out["written"])

    def test_toggling_on_a_shipped_rule_adopts_it_when_it_helps(self):
        self.ship(20000, 0.3, 1500, rules=[self.migrations(False)])
        self.migration_rows()
        code, out = self.backtest("--enable", "migrations", "--adopt")
        self.assertEqual((code, out["verdict"], out["written"]), (0, "adopt", True))
        self.assertEqual([(r["id"], r["verdict"]) for r in out["rules"]], [("migrations", "keep")])
        self.assertEqual(read_constants(self.constants)["RULES"], [self.migrations(True)])

    def test_toggling_an_unknown_rule_or_shipping_an_uncited_rule_is_refused(self):
        self.migration_rows()
        code, out = self.backtest("--enable", "nonexistent")
        self.assertEqual((code, out), (2, {"error": "INVALID_REQUEST"}))
        uncited = dict(self.migrations(True), cites=[])
        self.ship(30000, 0.5, 1500, rules=[uncited])
        code, out = self.backtest()
        self.assertEqual((code, out), (2, {"error": "INVALID_REQUEST"}))
        elsewhere = dict(self.migrations(True), cites=[f"{REPO}#3"])   # cited row the rule does not change
        self.ship(30000, 0.5, 1500, rules=[elsewhere])
        code, out = self.backtest()
        self.assertEqual((code, out), (2, {"error": "INVALID_REQUEST"}))

    def rename_consumer_tests(self):
        """The #42 outlier proposal, with #434's re-tagged footprint (commit d0b8797's run)."""
        row = "github.com/liumingjian/reimburse-ai#434"
        return {"id": "rename-consumer-tests", "kind": "tagging", "enabled": True, "proposed": True,
                "text": "Test files are mechanical when the ticket only renames what they reference.",
                "match": "*.test.*", "cites": [row],
                "rows": {row: {"semantic_bytes": 116982, "mechanical_files": 55}}}

    def test_a_helpful_proposal_and_a_refit_in_one_run_are_both_adopted(self):
        # The #42 run: placeholder constants, 18 reimburse-ai rows, one proposed tagging rule.
        # Before is what ships (placeholders, no rule); the rule beats the refit without it.
        self.table.write_bytes((FIXTURES / "calibration-reimburse-ai.tsv").read_bytes())
        self.ship(30000, 0.5, 1500, rules=[self.rename_consumer_tests()])
        code, out = self.backtest("--adopt")
        self.assertEqual(code, 0)
        self.assertEqual((out["before"]["rules"], out["before"]["tier_accuracy"], out["before"]["median_error"]),
                         ([], 0.5, 0.249))
        self.assertEqual(out["after"]["coefficients"], {"base": 60913, "k_semantic": 0.3859, "k_mechanical": 748})
        self.assertEqual((out["after"]["rules"], out["after"]["tier_accuracy"], out["after"]["median_error"]),
                         (["rename-consumer-tests"], 0.6667, 0.2178))
        [verdict] = out["rules"]
        self.assertEqual((verdict["id"], verdict["proposed"], verdict["verdict"]), ("rename-consumer-tests", True, "keep"))
        self.assertEqual((verdict["without"]["tier_accuracy"], verdict["without"]["median_error"]), (0.6111, 0.219))
        self.assertEqual((out["verdict"], out["reasons"], out["written"]), ("adopt", [], True))
        shipped = read_constants(self.constants)
        adopted = {k: v for k, v in self.rename_consumer_tests().items() if k != "proposed"}
        self.assertEqual(shipped["RULES"], [adopted])
        code, out = self.backtest()
        self.assertEqual((out["before"]["rules"], out["verdict"], out["reasons"]),
                         (["rename-consumer-tests"], "refuse", ["unchanged"]))

    def test_a_proposal_that_does_not_beat_the_refit_without_it_is_deleted_and_the_refit_still_adopted(self):
        # Data is exact without the rule, so the rule can only make the refit worse.
        harmful = dict(self.migrations(True), proposed=True)
        self.ship(30000, 0.5, 1500, rules=[harmful])
        self.rows(*[exact(i, s) for i, s in enumerate(SIZES, 1)])
        code, out = self.backtest("--adopt")
        self.assertEqual(code, 0)
        self.assertEqual(out["before"]["rules"], [])
        self.assertEqual([(r["id"], r["verdict"]) for r in out["rules"]], [("migrations", "delete")])
        self.assertEqual(out["after"]["coefficients"], {"base": 20000, "k_semantic": 0.3, "k_mechanical": 1500})
        self.assertEqual((out["after"]["rules"], out["verdict"], out["written"]), ([], "adopt", True))
        self.assertEqual(read_constants(self.constants)["RULES"], [])

    def test_a_proposal_that_changes_nothing_is_deleted(self):
        idle = dict(self.migrations(True), proposed=True, rows={f"{REPO}#2": {"units": 0}})
        self.ship(20000, 0.3, 1500, rules=[idle])
        self.rows(*[exact(i, s) for i, s in enumerate(SIZES, 1)])
        code, out = self.backtest()
        self.assertEqual([(r["id"], r["verdict"]) for r in out["rules"]], [("migrations", "delete")])
        self.assertEqual((out["verdict"], out["reasons"]), ("refuse", ["unchanged"]))

    def test_a_malformed_table_is_refused(self):
        self.table.write_text("not\ta\theader\n", encoding="utf-8")
        code, out = self.backtest()
        self.assertEqual((code, out), (2, {"error": "INVALID_REQUEST"}))


if __name__ == "__main__":
    unittest.main()
