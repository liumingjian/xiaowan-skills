"""Learned rules: the schema, its checks, and how a rule changes a calibration row or a footprint.

This docstring is the one definition of the rule schema; everything else points here.

A rule is a dict with exactly these keys:

    id        str, unique short kebab-case name
    kind      "term" | "tagging"
    enabled   bool; a disabled rule contributes nothing (and the backtest deletes it)
    text      str; for a tagging rule, the instruction a footprint subagent follows
    match     fnmatch glob over repo-relative paths (`*` also crosses `/`)
    tokens    int, term rules only: tokens added per footprint file matching `match`
    cites     non-empty list of calibration rows ("<repo>#<ticket>") it came from, each a key of rows
    rows      {row: effect | None}: every calibration row the rule changes; None = not re-explored yet
    proposed  optional, true only while a learn run is judging the rule: the backtest leaves it out
              of "before" (what ships), and --adopt writes a kept rule without this key

A term effect is {"units": n} (matching footprint files). A tagging effect is the row's
re-explored footprint, {"semantic_bytes": n, "mechanical_files": n}, used instead of the
stored columns. FOOTPRINT.md applies enabled tagging rules; estimate applies enabled term rules.
"""
from collections import namedtuple
from fnmatch import fnmatchcase

from .common import require

KINDS = ("term", "tagging")
EFFECT_KEYS = {"term": {"units"}, "tagging": {"semantic_bytes", "mechanical_files"}}
REQUIRED = {"id", "kind", "enabled", "text", "match", "cites", "rows"}

# A calibration row as priced under some rules: its footprint and the term rules' extra tokens.
Applied = namedtuple("Applied", ["semantic_bytes", "mechanical_files", "tokens"])


def count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def text(value):
    return isinstance(value, str) and value.strip() != ""


def checked(rules):
    require(isinstance(rules, list))
    seen = set()
    for rule in rules:
        require(isinstance(rule, dict) and text(rule.get("id")) and rule["id"] not in seen)
        seen.add(rule["id"])
        kind = rule.get("kind")
        require(kind in KINDS and isinstance(rule.get("enabled"), bool))
        require(text(rule.get("text")) and text(rule.get("match")))
        expected = REQUIRED | ({"tokens"} if kind == "term" else set())
        require(set(rule) - {"proposed"} == expected and isinstance(rule.get("proposed", False), bool))
        if kind == "term":
            require(isinstance(rule["tokens"], int) and not isinstance(rule["tokens"], bool))
        rows = rule["rows"]
        require(isinstance(rows, dict) and all(text(key) and "#" in key for key in rows))
        for effect in rows.values():
            require(effect is None or (isinstance(effect, dict) and set(effect) == EFFECT_KEYS[kind]
                                       and all(count(v) for v in effect.values())))
        # A rule is auditable only through the rows it came from.
        cites = rule["cites"]
        require(isinstance(cites, list) and cites and all(isinstance(c, str) and c in rows for c in cites))
    return rules


def row_key(repo, ticket):
    return f"{repo}#{ticket}"


def apply(row, rules):
    """The row's Applied footprint and extra tokens under the given rules, in order."""
    key = row_key(row["repo"], row["ticket"])
    semantic, mechanical, tokens = row["semantic_bytes"], row["mechanical_files"], 0
    for rule in rules:
        effect = rule["rows"].get(key)
        if effect is None:
            continue
        if rule["kind"] == "tagging":
            semantic, mechanical = effect["semantic_bytes"], effect["mechanical_files"]
        else:
            tokens += rule["tokens"] * effect["units"]
    return Applied(semantic, mechanical, tokens)


def pending(row, rules):
    """Ids of the rules that change this row but whose effect has not been re-explored yet."""
    key = row_key(row["repo"], row["ticket"])
    return [rule["id"] for rule in rules if key in rule["rows"] and rule["rows"][key] is None]


def terms(paths, rules):
    """Each term rule that matches footprint paths: its units (matching files) and tokens."""
    found = []
    for rule in rules:
        if rule["kind"] != "term":
            continue
        units = sum(1 for path in paths if fnmatchcase(path, rule["match"]))
        if units:
            found.append({"rule": rule["id"], "units": units, "tokens": rule["tokens"] * units})
    return found
