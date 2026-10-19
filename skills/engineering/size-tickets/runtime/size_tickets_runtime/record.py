"""Append measured tickets to calibration.tsv, the learn branch's data."""
from pathlib import Path

from . import calibration
from .common import require


def record(request, table=None):
    table = Path(table) if table else calibration.DEFAULT_TABLE
    require(isinstance(request, dict) and isinstance(request.get("rows"), list))
    new = [calibration.checked(value) for value in request["rows"]]
    rows = calibration.read(table)
    # One row per (repo, ticket): a rerun of learn replaces the ticket's row in place.
    where = {(row["repo"], row["ticket"]): index for index, row in enumerate(rows)}
    appended = replaced = 0
    for row in new:
        key = (row["repo"], row["ticket"])
        if key in where:
            rows[where[key]] = row
            replaced += 1
        else:
            where[key] = len(rows)
            rows.append(row)
            appended += 1
    calibration.write(table, rows)
    return {"calibration": str(table), "appended": appended, "replaced": replaced}
