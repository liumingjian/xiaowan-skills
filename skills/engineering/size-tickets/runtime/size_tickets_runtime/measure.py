"""Actual context peaks per ticket, read from Claude Code session logs.

One .jsonl file is one session (subagent logs carry their parent's sessionId, so
grouping by sessionId would merge an implementer into its orchestrator).
"""
import json
from pathlib import Path
import re

from .common import Refusal

REF = re.compile(r"(?:#|issues/|gh issue view\s+)(\d+)\b")
# The opening sentence states the session's role; "implementation" alone (a reviewer's) doesn't count.
IMPLEMENTER = re.compile(r"\bimplement(?:er)?\b|实现", re.IGNORECASE)
SENTENCE_END =re.compile(r"[.!?。]\s")


def ticket_number(word):
    text = word[1:] if word.startswith("#") else word
    if not text.isdigit():
        raise Refusal()
    return int(text)


def records(path):
    """Parsed records; a line that doesn't parse (a live log's truncated tail) is dropped."""
    with open(path, "rb") as source:
        for line in source:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def prompt_text(record):
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")
    return ""


def first_sentence(prompt):
    end = SENTENCE_END.search(prompt)
    return prompt[:end.start() + 1] if end else prompt


def refs(text, requested):
    """Requested tickets referenced in text, in order of first mention."""
    found = []
    for ref in REF.findall(text):
        if int(ref) in requested and int(ref) not in found:
            found.append(int(ref))
    return found


def context(record):
    usage = (record.get("message") or {}).get("usage") or {}
    total = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            total += value
    return total


def read_session(path):
    prompt, peak, compacted = None, 0, False
    for record in records(path):
        kind = record.get("type")
        if kind == "user" and prompt is None:
            # Command caveats and compaction summaries come before or instead of the real prompt.
            if record.get("isMeta") is not True and record.get("isCompactSummary") is not True:
                prompt = prompt_text(record)
        elif kind == "assistant":
            peak = max(peak, context(record))
        elif kind == "system" and record.get("subtype") == "compact_boundary":
            compacted = True
    return {"prompt": prompt or "", "peak": peak, "compacted": compacted}


def session_files(directories):
    found = set()
    for directory in directories:
        root = Path(directory)
        if not root.is_dir():
            raise Refusal()
        found.update(path for path in root.rglob("*.jsonl") if path.is_file())
    return sorted(found)


def measure(directories, words):
    requested = []
    for word in words:
        number = ticket_number(word)
        if number not in requested:
            requested.append(number)
    best, skipped = {}, []
    for path in session_files(directories):
        session = read_session(path)
        named = refs(session["prompt"], requested)
        if not named:
            continue
        opening = refs(first_sentence(session["prompt"]), requested)
        if len(opening) > 1:
            skipped.append({"session": str(path), "tickets": opening, "reason": "multi_ticket", "peak": session["peak"]})
            continue
        if not IMPLEMENTER.search(first_sentence(session["prompt"])):
            skipped.append({"session": str(path), "tickets": named[:1], "reason": "not_implementer", "peak": session["peak"]})
            continue
        if session["peak"] == 0:
            # Synthetic error turns and replayed messages log zero usage; nothing to measure.
            skipped.append({"session": str(path), "tickets": named[:1], "reason": "no_usage", "peak": 0})
            continue
        # The primary ticket is the first requested one named: the spec and siblings come as context.
        ticket = named[0]
        found = {"ticket": ticket, "peak": session["peak"], "compacted": session["compacted"], "session": str(path)}
        if ticket in best:
            # Two implementer sessions for one ticket (e.g. a retry): keep the larger peak.
            found, loser = sorted((best[ticket], found), key=lambda each: each["peak"], reverse=True)
            skipped.append({"session": loser["session"], "tickets": [ticket], "reason": "duplicate_implementer", "peak": loser["peak"]})
        best[ticket] = found
    return {
        "tickets": [best[ticket] for ticket in requested if ticket in best],
        "unmatched": [ticket for ticket in requested if ticket not in best],
        "skipped": skipped,
    }
