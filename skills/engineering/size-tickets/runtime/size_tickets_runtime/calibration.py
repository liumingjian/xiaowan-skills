"""calibration.tsv, the learn branch's data: one reader and one writer for every command.

One row per (repo, ticket). Every column is a non-negative integer except `repo` and `date`
(text without tabs or newlines) and `compacted` (`true`/`false`).
"""
from pathlib import Path

from .common import Refusal, require

COLUMNS = ["repo", "spec", "ticket", "estimate", "actual", "semantic_bytes", "mechanical_files", "compacted", "date"]
TEXT = ("repo", "date")
DEFAULT_TABLE = Path(__file__).resolve().parents[2] / "calibration.tsv"


def cell(name, value):
    """A column value as written to the table; refuses a value of the wrong type."""
    if name == "compacted":
        require(isinstance(value, bool))
        return "true" if value else "false"
    if name in TEXT:
        require(isinstance(value, str) and value and not any(c in value for c in "\t\r\n"))
        return value
    require(isinstance(value, int) and not isinstance(value, bool) and value >= 0)
    return str(value)


def checked(row):
    """A row with exactly the table's columns, each of the right type."""
    require(isinstance(row, dict) and set(row) == set(COLUMNS))
    for name in COLUMNS:
        cell(name, row[name])
    return row


def parsed(name, text):
    if name == "compacted":
        require(text in ("true", "false"))
        return text == "true"
    if name in TEXT:
        return text
    require(text.isdigit())
    return int(text)


def read(path):
    """Every row, typed; refuses a missing table, a wrong header or a malformed row."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        raise Refusal()
    require(lines and lines[0].split("\t") == COLUMNS)
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split("\t")
        require(len(fields) == len(COLUMNS))
        rows.append({name: parsed(name, text) for name, text in zip(COLUMNS, fields)})
    return rows


def write(path, rows):
    lines = ["\t".join(COLUMNS)] + ["\t".join(cell(name, row[name]) for name in COLUMNS) for row in rows]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
