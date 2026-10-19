import os
from pathlib import Path

from .common import Refusal
from .constants import BUDGET, CALIBRATED, COEFFICIENTS

HUMAN_LABELS = {"ready-for-human"}
KINDS = {"semantic", "mechanical"}


def tier(estimate, budget=BUDGET):
    if estimate < budget / 3:
        return "undersized"
    if estimate <= budget:
        return "fits"
    if estimate < 2 * budget:
        return "oversized"
    return "must_split"


def require(condition):
    if not condition:
        raise Refusal()


def strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def is_human(ticket):
    return ticket.get("human") is True or bool(HUMAN_LABELS & set(ticket.get("labels", [])))


def checked_coefficients(value):
    if value is None:
        return dict(COEFFICIENTS), "shipped"
    require(isinstance(value, dict) and set(value) == set(COEFFICIENTS))
    require(all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in value.values()))
    return value, "input"


def checked_ticket(ticket):
    require(isinstance(ticket, dict) and isinstance(ticket.get("id"), str) and ticket["id"])
    require(isinstance(ticket.get("title", ""), str))
    require(strings(ticket.get("labels", [])) and strings(ticket.get("blocked_by", [])))
    require(isinstance(ticket.get("human", False), bool))
    footprint = ticket.get("footprint", [])
    require(isinstance(footprint, list))
    for item in footprint:
        require(isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"])
        require(item.get("kind") in KINDS)
        require("group" not in item or (isinstance(item["group"], str) and item["group"]))
    return footprint


def files(repo, footprint):
    """One entry per path, sized like `wc -c`; semantic wins over mechanical for a duplicate.

    A path that does not exist yet is a file the ticket creates: zero bytes, flagged.
    """
    merged, groups = {}, {}
    for item in footprint:
        if merged.get(item["path"]) != "semantic":
            merged[item["path"]] = item["kind"]
        if "group" in item:
            groups.setdefault(item["path"], item["group"])
    entries = []
    for path, kind in merged.items():
        target = Path(os.path.realpath(repo / path))
        require(not Path(path).is_absolute() and target.is_relative_to(repo))
        exists = target.is_file()
        entry = {"path": path, "kind": kind, "bytes": target.stat().st_size if exists else 0, "exists": exists}
        if path in groups:
            entry["group"] = groups[path]
        entries.append(entry)
    return entries


def score(entries, coefficients):
    semantic = sum(entry["bytes"] for entry in entries if entry["kind"] == "semantic")
    mechanical = sum(1 for entry in entries if entry["kind"] == "mechanical")
    value = round(coefficients["base"] + coefficients["k_semantic"] * semantic + coefficients["k_mechanical"] * mechanical)
    return {"semantic_bytes": semantic, "mechanical_files": mechanical, "estimate": value, "tier": tier(value)}


def group_key(entry):
    """The subagent's behaviour group when tagged, else the file's directory."""
    return entry.get("group") or (os.path.dirname(entry["path"]) or ".")


def cost(entry, coefficients):
    if entry["kind"] == "semantic":
        return coefficients["k_semantic"] * entry["bytes"]
    return coefficients["k_mechanical"]


def breakdown(entries, coefficients, top=3):
    """Where the footprint comes from: the most expensive groups, base excluded."""
    by_key = {}
    for entry in entries:
        by_key.setdefault(group_key(entry), []).append(entry)
    rows = []
    for key, members in by_key.items():
        largest = min(members, key=lambda entry: (-cost(entry, coefficients), entry["path"]))
        rows.append({
            "group": key,
            "tokens": round(sum(cost(entry, coefficients) for entry in members)),
            "files": len(members),
            "largest": largest["path"],
        })
    rows.sort(key=lambda row: (-row["tokens"], row["group"]))
    return rows[:top]


def split(ticket_id, entries, coefficients):
    """Deterministic split line for a ticket over budget; None when it fits.

    Groups are taken in sorted key order and packed greedily: a group joins the
    current part while the part's recomputed estimate stays within the budget.
    A group too big for any part on its own is packed file by file in path order.
    """
    if score(entries, coefficients)["estimate"] <= BUDGET:
        return None
    by_key = {}
    for entry in entries:
        by_key.setdefault(group_key(entry), []).append(entry)
    parts, current = [], []

    def fits(candidate):
        return score([entry for _, entry in candidate], coefficients)["estimate"] <= BUDGET

    for key in sorted(by_key):
        members = [(key, entry) for entry in sorted(by_key[key], key=lambda entry: entry["path"])]
        if fits(current + members):
            current += members
            continue
        if current:
            parts.append(current)
            current = []
        if fits(members):
            current = members
            continue
        for member in members:
            if current and not fits(current + [member]):
                parts.append(current)
                current = []
            current.append(member)
    if current:
        parts.append(current)
    result = []
    for number, part in enumerate(parts, 1):
        keys = []
        for key, _ in part:
            if key not in keys:
                keys.append(key)
        result.append({
            "id": f"{ticket_id}.{number}",
            "groups": keys,
            "paths": [entry["path"] for _, entry in part],
            **score([entry for _, entry in part], coefficients),
        })
    return {"by": "group" if any("group" in entry for entry in entries) else "directory", "parts": result}


def union(first, second):
    """Both footprints with each path once; semantic wins over mechanical."""
    merged = {}
    for entry in first + second:
        if merged.get(entry["path"], {}).get("kind") != "semantic":
            merged[entry["path"]] = entry
    return list(merged.values())


def merges(tickets, coefficients):
    """Pairs worth merging: both undersized, directly adjacent on a blocking chain
    or sharing footprint files, and the recomputed union still within the budget.
    """
    proposals = []
    for i, first in enumerate(tickets):
        for second in tickets[i + 1:]:
            if first["tier"] != "undersized" or second["tier"] != "undersized":
                continue
            reasons = []
            if first["id"] in second["blocked_by"] or second["id"] in first["blocked_by"]:
                reasons.append("blocking")
            if {entry["path"] for entry in first["files"]} & {entry["path"] for entry in second["files"]}:
                reasons.append("shared_files")
            if not reasons:
                continue
            entries = union(first["files"], second["files"])
            combined = score(entries, coefficients)
            if combined["estimate"] > BUDGET:
                continue
            proposals.append({
                "tickets": [first["id"], second["id"]],
                "reasons": reasons,
                "paths": [entry["path"] for entry in entries],
                **combined,
            })
    return proposals


def estimate(request):
    require(isinstance(request, dict) and isinstance(request.get("repo"), str) and isinstance(request.get("tickets"), list))
    repo = Path(os.path.realpath(request["repo"]))
    require(repo.is_dir())
    coefficients, source = checked_coefficients(request.get("coefficients"))
    footprints = [checked_ticket(ticket) for ticket in request["tickets"]]
    tickets, skipped = [], []
    for ticket, footprint in zip(request["tickets"], footprints):
        title = ticket.get("title", "")
        if is_human(ticket):
            skipped.append({"id": ticket["id"], "title": title, "reason": "human"})
            continue
        entries = files(repo, footprint)
        tickets.append({
            "id": ticket["id"],
            "title": title,
            "blocked_by": ticket.get("blocked_by", []),
            "files": entries,
            **score(entries, coefficients),
            "breakdown": breakdown(entries, coefficients),
            "split": split(ticket["id"], entries, coefficients),
        })
    return {
        "budget": BUDGET,
        "calibrated": CALIBRATED,
        "coefficients": coefficients,
        "coefficients_source": source,
        "tickets": tickets,
        "skipped": skipped,
        "merges": merges(tickets, coefficients),
    }
