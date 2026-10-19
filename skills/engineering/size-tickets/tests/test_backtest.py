import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
RUNTIME = SKILL / "runtime"
SHIPPED_CONSTANTS = RUNTIME / "size_tickets_runtime" / "constants.py"
HEADER = "repo\tspec\tticket\testimate\tactual\tsemantic_bytes\tmechanical_files\tcompacted\tdate"
REPO = "github.com/example/app"


def tsv_row(ticket, actual, semantic_bytes, mechanical_files=0, estimate=0, compacted=False, repo=REPO):
    return "\t".join(str(v) for v in [repo, 1, ticket, estimate, actual, semantic_bytes, mechanical_files,
                                       "true" if compacted else "false", "2026-10-19"])


def constants_text(base, k_semantic, k_mechanical):
    return (SHIPPED_CONSTANTS.read_text(encoding="utf-8")
            .replace('"base": 30000,', f'"base": {base},')
            .replace('"k_semantic": 0.5,', f'"k_semantic": {k_semantic},')
            .replace('"k_mechanical": 1500,', f'"k_mechanical": {k_mechanical},'))


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

    def ship(self, base, k_semantic, k_mechanical):
        self.constants.write_text(constants_text(base, k_semantic, k_mechanical), encoding="utf-8")

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
            "coefficients": {"base": 30000, "k_semantic": 0.5, "k_mechanical": 1500},
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

    def test_the_shipped_empty_table_is_too_few_rows(self):
        code, out = self.backtest("--calibration", str(SKILL / "calibration.tsv"))
        self.assertEqual(code, 0)
        self.assertEqual((out["rows"], out["verdict"], out["reasons"]), (0, "refuse", ["too_few_rows"]))

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

    def test_a_malformed_table_is_refused(self):
        self.table.write_text("not\ta\theader\n", encoding="utf-8")
        code, out = self.backtest()
        self.assertEqual((code, out), (2, {"error": "INVALID_REQUEST"}))


if __name__ == "__main__":
    unittest.main()
