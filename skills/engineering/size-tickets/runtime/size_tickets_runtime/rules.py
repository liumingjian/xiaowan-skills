"""Learned rules: schema checks and how a rule changes a calibration row or a footprint."""
from fnmatch import fnmatchcase

from .common import Refusal

KINDS = ("term", "tagging")
EFFECT_KEYS = {"term": {"units"}, "tagging": {"semantic_bytes", "mechanical_files"}}


def require(condition):
    if not condition:
        raise Refusal()


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
        expected = {"id", "kind", "enabled", "text", "match", "cites", "rows"} | ({"tokens"} if kind == "term" else set())
        require(set(rule) == expected)
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
    """(semantic_bytes, mechanical_files, extra tokens) for a row under the given rules, in order."""
    key = row_key(row["repo"], row["ticket"])
    semantic, mechanical, extra = row["semantic_bytes"], row["mechanical_files"], 0
    for rule in rules:
        effect = rule["rows"].get(key)
        if effect is None:
            continue
        if rule["kind"] == "tagging":
            semantic, mechanical = effect["semantic_bytes"], effect["mechanical_files"]
        else:
            extra += rule["tokens"] * effect["units"]
    return semantic, mechanical, extra


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
