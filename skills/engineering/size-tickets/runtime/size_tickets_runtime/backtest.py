"""Refit the formula's coefficients over calibration.tsv behind a regression guard.

Works only from the stored footprint columns (semantic_bytes, mechanical_files), so a
backtest never re-explores a repo and its cost does not grow with the repos involved.

Objective: minimise the sum of squared *relative* errors, sum(((estimate - actual) / actual)^2).
The acceptance bar is ±50% of the actual peak, so a 20k miss on a 60k ticket must weigh more
than a 20k miss on a 600k one; plain least squares would let the largest tickets dominate.
Dividing each row by its actual keeps the problem linear, so it is solved exactly with the
normal equations. Coefficients are constrained to be non-negative (a negative base or cost
per byte means nothing) by solving every subset of free coefficients and keeping the best
feasible one. A coefficient no row informs (e.g. no row has mechanical files) keeps its
shipped value.

"before" is whatever the constants file ships, and --adopt rewrites that same file, so rule
toggles and per-repo offsets (#41) can join as further constants and inputs without
changing this contract.
"""
import ast
import re
from pathlib import Path
from statistics import median

from .common import Refusal
from .estimate import tier
from .record import COLUMNS, DEFAULT_TABLE

DEFAULT_CONSTANTS = Path(__file__).resolve().parent / "constants.py"
NAMES = ("base", "k_semantic", "k_mechanical")
# Written coefficients are rounded; "after" is scored with exactly what would be written.
DIGITS = {"base": 0, "k_semantic": 4, "k_mechanical": 0}
MIN_ROWS = 3


def require(condition):
    if not condition:
        raise Refusal()


def read_table(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        raise Refusal()
    require(lines and lines[0].split("\t") == COLUMNS)
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = dict(zip(COLUMNS, line.split("\t")))
        require(len(fields) == len(COLUMNS))
        try:
            row = {"repo": fields["repo"], "ticket": int(fields["ticket"]), "actual": int(fields["actual"]),
                   "semantic_bytes": int(fields["semantic_bytes"]),
                   "mechanical_files": int(fields["mechanical_files"])}
        except ValueError:
            raise Refusal()
        require(fields["compacted"] in ("true", "false"))
        row["compacted"] = fields["compacted"] == "true"
        rows.append(row)
    return rows


def coefficients_node(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COEFFICIENTS" for t in node.targets):
            return node
    raise Refusal()


def read_constants(path):
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        value = ast.literal_eval(coefficients_node(tree).value)
    except (OSError, SyntaxError, ValueError):
        raise Refusal()
    require(isinstance(value, dict) and set(value) == set(NAMES))
    return {name: value[name] for name in NAMES}


def features(row):
    return (1.0, float(row["semantic_bytes"]), float(row["mechanical_files"]))


def predict(row, coefficients):
    return round(sum(c * x for c, x in zip((coefficients[n] for n in NAMES), features(row))))


def solve(matrix, vector):
    """Gaussian elimination with partial pivoting; None when singular."""
    size = len(vector)
    a = [list(matrix[i]) + [vector[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12 * max(1.0, max(abs(v) for v in a[pivot][:size])):
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(size):
            if r != col:
                factor = a[r][col] / a[col][col]
                a[r] = [x - factor * y for x, y in zip(a[r], a[col])]
    return [a[i][size] / a[i][i] for i in range(size)]


def fit(rows, shipped):
    """Non-negative least squares on relative error, by enumerating free-coefficient subsets."""
    informed = [i for i in range(len(NAMES)) if any(features(r)[i] for r in rows)]
    # Scale columns so bytes (~1e5) and counts (~1) condition the normal equations alike.
    scale = [max(abs(features(r)[i]) for r in rows) or 1.0 for i in range(len(NAMES))]
    best, best_loss = None, None
    for mask in range(1, 1 << len(informed)):
        free = [informed[j] for j in range(len(informed)) if mask >> j & 1]
        x = [[features(r)[i] / scale[i] / r["actual"] for i in free] for r in rows]
        gram = [[sum(row[p] * row[q] for row in x) for q in range(len(free))] for p in range(len(free))]
        rhs = [sum(row[p] for row in x) for p in range(len(free))]
        solution = solve(gram, rhs)
        if solution is None or any(value < 0 for value in solution):
            continue
        loss = sum((sum(s * v for s, v in zip(solution, row)) - 1) ** 2 for row in x)
        if best_loss is None or loss < best_loss - 1e-15:
            best, best_loss = dict(zip(free, solution)), loss
    if best is None:
        return None
    fitted = {}
    for i, name in enumerate(NAMES):
        value = best.get(i, 0.0) / scale[i] if i in informed else shipped[name]
        fitted[name] = round(value, DIGITS[name]) if DIGITS[name] else int(round(value))
    return fitted


def score(rows, coefficients):
    estimates = [predict(r, coefficients) for r in rows]
    errors = [abs(e - r["actual"]) / r["actual"] for e, r in zip(estimates, rows)]
    hits = sum(1 for e, r in zip(estimates, rows) if tier(e) == tier(r["actual"]))
    return {
        "coefficients": coefficients,
        "tier_accuracy": round(hits / len(rows), 4),
        "median_error": round(median(errors), 4),
        "within_50": round(sum(1 for e in errors if e <= 0.5) / len(rows), 4),
    }


def backtest(table=None, constants=None, adopt=False):
    table = Path(table) if table else DEFAULT_TABLE
    constants = Path(constants) if constants else DEFAULT_CONSTANTS
    shipped = read_constants(constants)
    every = read_table(table)
    # A compacted session's peak is a lower bound, so it would bias the fit downwards.
    rows = [r for r in every if not r["compacted"] and r["actual"] > 0]
    excluded = [{"repo": r["repo"], "ticket": r["ticket"], "reason": "compacted" if r["compacted"] else "no_actual"}
                for r in every if r["compacted"] or r["actual"] <= 0]
    result = {"calibration": str(table), "constants": str(constants), "rows": len(rows), "excluded": excluded,
              "objective": "relative_squared_error", "before": None, "after": None,
              "verdict": "refuse", "reasons": [], "written": False}
    if len(rows) < MIN_ROWS:
        result["reasons"] = ["too_few_rows"]
        return result
    result["before"] = before = score(rows, shipped)
    fitted = fit(rows, shipped)
    if fitted is None:
        result["reasons"] = ["no_fit"]
        return result
    result["after"] = after = score(rows, fitted)
    reasons = []
    if after["tier_accuracy"] < before["tier_accuracy"]:
        reasons.append("tier_accuracy_dropped")
    if after["median_error"] > before["median_error"]:
        reasons.append("median_error_rose")
    if not reasons and fitted == shipped:
        reasons.append("unchanged")
    result["reasons"] = reasons
    result["verdict"] = "refuse" if reasons else "adopt"
    if adopt and not reasons:
        write_constants(constants, fitted)
        result["written"] = True
    return result


def write_constants(path, coefficients):
    """Rewrite CALIBRATED and the COEFFICIENTS block in place; the rest of the file is kept."""
    text = Path(path).read_text(encoding="utf-8")
    comments = {}
    for name in NAMES:
        found = re.search(r'^\s*"%s":[^#\n]*(#.*)$' % name, text, re.M)
        comments[name] = "  " + found.group(1) if found else ""
    block = "COEFFICIENTS = {\n" + "".join(
        '    "%s": %s,%s\n' % (name, repr(coefficients[name]), comments[name]) for name in NAMES) + "}"
    text, count = re.subn(r"^COEFFICIENTS = \{.*?^\}", lambda _: block, text, count=1, flags=re.M | re.S)
    require(count == 1)
    text, count = re.subn(r"^CALIBRATED = .*$", "CALIBRATED = True", text, count=1, flags=re.M)
    require(count == 1)
    Path(path).write_text(text, encoding="utf-8")
