import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
RUNTIME = SKILL / "runtime"

# The columns spec #36 (Learn, item 3) lists for a calibration row.
HEADER = "repo\tspec\tticket\testimate\tactual\tsemantic_bytes\tmechanical_files\tcompacted\tdate"


def row(**overrides):
    value = {
        "repo": "github.com/liumingjian/reimburse-ai", "spec": 412, "ticket": 422,
        "estimate": 98000, "actual": 105965, "semantic_bytes": 136000,
        "mechanical_files": 0, "compacted": False, "date": "2026-10-19",
    }
    value.update(overrides)
    return value


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="size-tickets-test-")
        self.table = Path(self.temp.name) / "calibration.tsv"
        # Start from the shipped columns only, so the tests don't depend on the shipped rows.
        header = (SKILL / "calibration.tsv").read_text(encoding="utf-8").splitlines()[0]
        self.table.write_text(header + "\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def record(self, request, *words):
        env = dict(os.environ, PYTHONPATH=str(RUNTIME))
        result = subprocess.run(
            [sys.executable, "-m", "size_tickets_runtime", "record", "--calibration", str(self.table), *words, "-"],
            input=json.dumps(request).encode(), env=env, capture_output=True,
        )
        return result.returncode, json.loads(result.stdout)

    def lines(self):
        return self.table.read_text(encoding="utf-8").splitlines()

    def test_shipped_table_starts_with_the_spec_columns(self):
        self.assertEqual(self.lines()[0], HEADER)

    def test_rows_are_appended_one_per_ticket_in_column_order(self):
        code, out = self.record({"rows": [row(), row(ticket=423, actual=247621, compacted=True)]})
        self.assertEqual(code, 0)
        self.assertEqual(out, {"calibration": str(self.table), "appended": 2, "replaced": 0})
        self.assertEqual(self.lines(), [
            HEADER,
            "github.com/liumingjian/reimburse-ai\t412\t422\t98000\t105965\t136000\t0\tfalse\t2026-10-19",
            "github.com/liumingjian/reimburse-ai\t412\t423\t98000\t247621\t136000\t0\ttrue\t2026-10-19",
        ])

    def test_rerunning_learn_replaces_a_tickets_row_instead_of_duplicating_it(self):
        self.record({"rows": [row(ticket=421), row(ticket=422)]})
        code, out = self.record({"rows": [row(ticket=421, estimate=120000, date="2026-11-02"),
                                          row(repo="github.com/other/repo", ticket=421)]})
        self.assertEqual(code, 0)
        self.assertEqual((out["appended"], out["replaced"]), (1, 1))
        self.assertEqual(self.lines(), [
            HEADER,
            "github.com/liumingjian/reimburse-ai\t412\t421\t120000\t105965\t136000\t0\tfalse\t2026-11-02",
            "github.com/liumingjian/reimburse-ai\t412\t422\t98000\t105965\t136000\t0\tfalse\t2026-10-19",
            "github.com/other/repo\t412\t421\t98000\t105965\t136000\t0\tfalse\t2026-10-19",
        ])

    def test_a_malformed_row_is_refused_and_the_table_left_untouched(self):
        before = self.lines()
        bad = [
            {"rows": [row(), row(ticket="#423")]},           # numbers must be integers
            {"rows": [row(compacted="no")]},                 # flag must be a boolean
            {"rows": [{k: v for k, v in row().items() if k != "date"}]},  # every column required
            {"rows": [row(repo="a\tb")]},                    # a tab would shift the columns
            [row()],
        ]
        for request in bad:
            code, out = self.record(request)
            self.assertEqual((code, out), (2, {"error": "INVALID_REQUEST"}), request)
        self.assertEqual(self.lines(), before)


if __name__ == "__main__":
    unittest.main()
