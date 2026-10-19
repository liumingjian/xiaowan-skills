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
    return footprint


def files(repo, footprint):
    """One entry per path, sized like `wc -c`; semantic wins over mechanical for a duplicate.

    A path that does not exist yet is a file the ticket creates: zero bytes, flagged.
    """
    merged = {}
    for item in footprint:
        if merged.get(item["path"]) != "semantic":
            merged[item["path"]] = item["kind"]
    entries = []
    for path, kind in merged.items():
        target = Path(os.path.realpath(repo / path))
        require(not Path(path).is_absolute() and target.is_relative_to(repo))
        exists = target.is_file()
        entries.append({"path": path, "kind": kind, "bytes": target.stat().st_size if exists else 0, "exists": exists})
    return entries


def score(entries, coefficients):
    semantic = sum(entry["bytes"] for entry in entries if entry["kind"] == "semantic")
    mechanical = sum(1 for entry in entries if entry["kind"] == "mechanical")
    value = round(coefficients["base"] + coefficients["k_semantic"] * semantic + coefficients["k_mechanical"] * mechanical)
    return {"semantic_bytes": semantic, "mechanical_files": mechanical, "estimate": value, "tier": tier(value)}


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
        })
    return {
        "budget": BUDGET,
        "calibrated": CALIBRATED,
        "coefficients": coefficients,
        "coefficients_source": source,
        "tickets": tickets,
        "skipped": skipped,
    }
