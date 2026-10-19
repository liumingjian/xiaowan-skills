"""Append measured tickets to calibration.tsv, the learn branch's data."""
from pathlib import Path

from .common import Refusal

COLUMNS = ["repo", "spec", "ticket", "estimate", "actual", "semantic_bytes", "mechanical_files", "compacted", "date"]
DEFAULT_TABLE = Path(__file__).resolve().parents[2] / "calibration.tsv"


def require(condition):
    if not condition:
        raise Refusal()


def cell(name, value):
    if name == "compacted":
        require(isinstance(value, bool))
        return "true" if value else "false"
    if name in ("repo", "date"):
        require(isinstance(value, str) and value and not any(c in value for c in "\t\r\n"))
        return value
    require(isinstance(value, int) and not isinstance(value, bool) and value >= 0)
    return str(value)


def record(request, table=None):
    table = Path(table) if table else DEFAULT_TABLE
    require(isinstance(request, dict) and isinstance(request.get("rows"), list))
    rows = []
    for value in request["rows"]:
        require(isinstance(value, dict) and set(value) == set(COLUMNS))
        rows.append([cell(name, value[name]) for name in COLUMNS])
    try:
        lines = table.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise Refusal()
    require(lines and lines[0].split("\t") == COLUMNS)
    # One row per (repo, ticket): a rerun of learn replaces the ticket's row in place.
    where = {}
    for index, line in enumerate(lines[1:], start=1):
        fields = line.split("\t")
        where[(fields[0], fields[2] if len(fields) > 2 else "")] = index
    appended = replaced = 0
    for each in rows:
        key = (each[0], each[2])
        if key in where:
            lines[where[key]] = "\t".join(each)
            replaced += 1
        else:
            where[key] = len(lines)
            lines.append("\t".join(each))
            appended += 1
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"calibration": str(table), "appended": appended, "replaced": replaced}
