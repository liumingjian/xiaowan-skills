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

Repo offsets join the same fit as signed per-repo terms, one for each repo with at least
MIN_OFFSET_ROWS usable rows, except the repo with the most rows (ties: first by name). That
one is the reference the base is fitted to: giving it an offset too would leave the base to
whatever smaller repos remain, letting a repo with too few rows set the base.

Rules (constants.RULES, schema in rules.py) are priced from their own per-row effects: a term
rule adds tokens per unit to the rows it lists, a tagging rule replaces a row's stored
footprint with the re-explored one. Pruning removes each enabled rule in turn (in order,
greedily), refits without it, and deletes it when the backtest is no worse without it.

"before" is whatever the constants file ships, and --adopt rewrites that same file.
"""
import ast
import pprint
import re
from pathlib import Path
from statistics import median

from .common import Refusal
from .estimate import tier
from .record import COLUMNS, DEFAULT_TABLE
from .rules import apply, checked, pending

DEFAULT_CONSTANTS = Path(__file__).resolve().parent / "constants.py"
NAMES = ("base", "k_semantic", "k_mechanical")
# Written coefficients are rounded; "after" is scored with exactly what would be written.
DIGITS = {"base": 0, "k_semantic": 4, "k_mechanical": 0}
MIN_ROWS = 3
MIN_OFFSET_ROWS = 5


def require(condition):
    if not condition:
        raise Refusal()


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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


def assignment(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node
    raise Refusal()


def read_constants(path):
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        coefficients = ast.literal_eval(assignment(tree, "COEFFICIENTS").value)
        offsets = ast.literal_eval(assignment(tree, "REPO_OFFSETS").value)
        rules = ast.literal_eval(assignment(tree, "RULES").value)
    except (OSError, SyntaxError, ValueError):
        raise Refusal()
    require(isinstance(coefficients, dict) and set(coefficients) == set(NAMES))
    require(all(number(v) for v in coefficients.values()))
    require(isinstance(offsets, dict) and all(isinstance(k, str) and isinstance(v, int) for k, v in offsets.items()))
    return {"coefficients": {name: coefficients[name] for name in NAMES}, "offsets": offsets,
            "rules": checked(rules)}


def features(row, rules):
    semantic, mechanical, _ = apply(row, rules)
    return (1.0, float(semantic), float(mechanical))


def enabled(rules):
    return [rule for rule in rules if rule["enabled"]]


def predict(row, model):
    active = enabled(model["rules"])
    linear = sum(c * x for c, x in zip((model["coefficients"][n] for n in NAMES), features(row, active)))
    return round(linear + apply(row, active)[2] + model["offsets"].get(row["repo"], 0))


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


def repo_counts(rows):
    counts = {}
    for row in rows:
        counts[row["repo"]] = counts.get(row["repo"], 0) + 1
    return counts


def offset_repos(rows):
    """Repos with enough rows for an offset, never the reference repo the base is fitted to."""
    counts = repo_counts(rows)
    reference = min(counts, key=lambda repo: (-counts[repo], repo))
    return sorted(repo for repo, n in counts.items() if n >= MIN_OFFSET_ROWS and repo != reference)


def fit(rows, shipped, rules):
    """Non-negative least squares on relative error, by enumerating free-coefficient subsets.

    Offsets for offset_repos(rows) are always free and may be negative. Enabled rules are
    fixed: their tokens are taken off each row's target and tagging effects set its features.
    """
    repos = offset_repos(rows)
    active = enabled(rules)
    feats = [features(r, active) for r in rows]
    targets = [(r["actual"] - apply(r, active)[2]) / r["actual"] for r in rows]
    informed = [i for i in range(len(NAMES)) if any(f[i] for f in feats)]
    # Scale columns so bytes (~1e5) and counts (~1) condition the normal equations alike.
    scale = [max(abs(f[i]) for f in feats) or 1.0 for i in range(len(NAMES))]
    best, best_loss = None, None
    for mask in range(0 if repos else 1, 1 << len(informed)):
        free = [informed[j] for j in range(len(informed)) if mask >> j & 1]
        x = [[f[i] / scale[i] / r["actual"] for i in free]
             + [(1.0 if r["repo"] == repo else 0.0) / r["actual"] for repo in repos] for f, r in zip(feats, rows)]
        width = len(free) + len(repos)
        gram = [[sum(row[p] * row[q] for row in x) for q in range(width)] for p in range(width)]
        rhs = [sum(row[p] * y for row, y in zip(x, targets)) for p in range(width)]
        solution = solve(gram, rhs)
        if solution is None or any(value < 0 for value in solution[:len(free)]):
            continue
        loss = sum((sum(s * v for s, v in zip(solution, row)) - y) ** 2 for row, y in zip(x, targets))
        if best_loss is None or loss < best_loss - 1e-15:
            best, best_loss = (dict(zip(free, solution)), solution[len(free):]), loss
    if best is None:
        return None
    values, offsets = best
    coefficients = {}
    for i, name in enumerate(NAMES):
        value = values.get(i, 0.0) / scale[i] if i in informed else shipped["coefficients"][name]
        coefficients[name] = round(value, DIGITS[name]) if DIGITS[name] else int(round(value))
    return {"coefficients": coefficients, "offsets": {repo: int(round(o)) for repo, o in zip(repos, offsets)},
            "rules": rules}


def worse(candidate, baseline):
    """The regression guard's reasons, empty when candidate is no worse than baseline."""
    reasons = []
    if candidate["tier_accuracy"] < baseline["tier_accuracy"]:
        reasons.append("tier_accuracy_dropped")
    if candidate["median_error"] > baseline["median_error"]:
        reasons.append("median_error_rose")
    return reasons


def prune(rows, shipped, rules):
    """Refit with every enabled rule, then try each without it; (model, verdicts) or (None, [])."""
    current = fit(rows, shipped, enabled(rules))
    if current is None:
        return None, []
    verdicts = []
    for rule in rules:
        entry = {"id": rule["id"], "kind": rule["kind"], "cites": rule["cites"], "enabled": rule["enabled"],
                 "verdict": "delete", "without": None}
        verdicts.append(entry)
        if not rule["enabled"]:
            continue  # contributes nothing, so removing it changes nothing
        trial = fit(rows, shipped, [r for r in current["rules"] if r is not rule])
        if trial is None:
            entry["verdict"] = "keep"
            continue
        entry["without"] = score(rows, trial)
        if worse(entry["without"], score(rows, current)):
            entry["verdict"] = "keep"
        else:
            current = trial
    return current, verdicts


def score(rows, model):
    estimates = [predict(r, model) for r in rows]
    errors = [abs(e - r["actual"]) / r["actual"] for e, r in zip(estimates, rows)]
    hits = sum(1 for e, r in zip(estimates, rows) if tier(e) == tier(r["actual"]))
    return {
        "coefficients": model["coefficients"],
        "offsets": model["offsets"],
        "rules": [rule["id"] for rule in enabled(model["rules"])],
        "tier_accuracy": round(hits / len(rows), 4),
        "median_error": round(median(errors), 4),
        "within_50": round(sum(1 for e in errors if e <= 0.5) / len(rows), 4),
    }


def toggled(rules, enable, disable):
    """The shipped rules with each named rule switched on or off; unknown or clashing names refuse."""
    enable, disable = set(enable or ()), set(disable or ())
    require(not enable & disable and enable | disable <= {rule["id"] for rule in rules})
    return [dict(rule, enabled=True) if rule["id"] in enable else
            dict(rule, enabled=False) if rule["id"] in disable else rule for rule in rules]


def backtest(table=None, constants=None, adopt=False, enable=(), disable=()):
    table = Path(table) if table else DEFAULT_TABLE
    constants = Path(constants) if constants else DEFAULT_CONSTANTS
    shipped = read_constants(constants)
    candidate = toggled(shipped["rules"], enable, disable)
    every = read_table(table)
    # A compacted session's peak is a lower bound, so it would bias the fit downwards.
    rows = [r for r in every if not r["compacted"] and r["actual"] > 0]
    excluded = [{"repo": r["repo"], "ticket": r["ticket"], "reason": "compacted" if r["compacted"] else "no_actual"}
                for r in every if r["compacted"] or r["actual"] <= 0]
    result = {"calibration": str(table), "constants": str(constants), "rows": len(rows), "excluded": excluded,
              "objective": "relative_squared_error", "before": None, "after": None, "repos": [], "rules": [], "reexplore": [],
              "verdict": "refuse", "reasons": [], "written": False}
    # Stored footprints are reused for every row except those an enabled rule changes and
    # nobody has re-explored yet: those, and only those, need a fresh footprint first.
    for row in sorted(rows, key=lambda r: (r["repo"], r["ticket"])):
        waiting = pending(row, [rule for rule in shipped["rules"] + candidate if rule["enabled"]])
        waiting = sorted(set(waiting), key=waiting.index)
        if waiting:
            result["reexplore"].append({"repo": row["repo"], "ticket": row["ticket"], "rules": waiting})
    if result["reexplore"]:
        result["reasons"] = ["needs_reexploration"]
        return result
    if len(rows) < MIN_ROWS:
        result["reasons"] = ["too_few_rows"]
        return result
    result["before"] = before = score(rows, shipped)
    fitted, result["rules"] = prune(rows, shipped, candidate)
    if fitted is None:
        result["reasons"] = ["no_fit"]
        return result
    result["after"] = after = score(rows, fitted)
    result["repos"] = [{"repo": repo, "rows": n, "offset": fitted["offsets"].get(repo)}
                       for repo, n in sorted(repo_counts(rows).items())]
    reasons = worse(after, before)
    if not reasons and fitted == shipped:
        reasons.append("unchanged")
    result["reasons"] = reasons
    result["verdict"] = "refuse" if reasons else "adopt"
    if adopt and not reasons:
        write_constants(constants, fitted)
        result["written"] = True
    return result


def replace_assignment(text, name, block):
    """Swap the whole `NAME = ...` statement, however many lines it spans, for block."""
    node = assignment(ast.parse(text), name)
    lines = text.split("\n")
    return "\n".join(lines[:node.lineno - 1] + [block] + lines[node.end_lineno:])


def write_constants(path, model):
    """Rewrite CALIBRATED, COEFFICIENTS, REPO_OFFSETS and RULES in place; the rest is kept."""
    text = Path(path).read_text(encoding="utf-8")
    comments = {}
    for name in NAMES:
        found = re.search(r'^\s*"%s":[^#\n]*(#.*)$' % name, text, re.M)
        comments[name] = "  " + found.group(1) if found else ""
    coefficients = model["coefficients"]
    block = "COEFFICIENTS = {\n" + "".join(
        '    "%s": %s,%s\n' % (name, repr(coefficients[name]), comments[name]) for name in NAMES) + "}"
    text, count = re.subn(r"^COEFFICIENTS = \{.*?^\}", lambda _: block, text, count=1, flags=re.M | re.S)
    require(count == 1)
    offsets = "REPO_OFFSETS = {" + "".join(
        "\n    %r: %r," % (repo, model["offsets"][repo]) for repo in sorted(model["offsets"])) + (
        "\n}" if model["offsets"] else "}")
    rules = "RULES = [" + "".join(
        "\n    " + pprint.pformat(rule, width=96, sort_dicts=False).replace("\n", "\n    ") + ","
        for rule in model["rules"]) + ("\n]" if model["rules"] else "]")
    text = replace_assignment(text, "REPO_OFFSETS", offsets)
    text = replace_assignment(text, "RULES", rules)
    text, count = re.subn(r"^CALIBRATED = .*$", "CALIBRATED = True", text, count=1, flags=re.M)
    require(count == 1)
    Path(path).write_text(text, encoding="utf-8")
