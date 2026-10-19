# Outlier

One ticket's estimate missed its implementer's actual context peak by more than ±50%. You find where the context went and propose at most one rule that would have caught it. You are read-only: you write nothing, and you only read the implementation log and the repo.

## Find where the context went

1. In the estimate output, find this ticket: its `files[]` (each path with `kind` and `bytes`), `estimate` and `terms[]`. That is the footprint the formula priced.
2. The implementation log is JSON lines. Turns are `type: "assistant"` records; a turn's context is `message.usage.input_tokens + cache_creation_input_tokens + cache_read_input_tokens` (skip turns where these sum to 0). Tool calls are the `tool_use` blocks of assistant records, and their output is the `tool_result` block of the next `user` record. Use `jq` or a short script to list each turn's context, then the largest jumps between consecutive turns with the tool calls before each jump (file reads, greps, test or build runs, and their output sizes).
3. Attribute the growth from the first turn to the peak: which files or commands account for most of it, and how each compares with the footprint. Typical causes:
   - files the implementer read deeply that the footprint left out, or tagged mechanical;
   - files tagged semantic that were only skimmed or edited by pattern, when the estimate was too high;
   - a cost that scales with a kind of file rather than its bytes: migrations, generated code, snapshots, fixtures, long test or build output per test file.

Done when you can name the files or commands behind most of the miss, with token figures from the log.

## Propose a rule

A rule must generalise to other tickets in other repos: a pattern of paths, never this ticket's own file list.

- **tagging**: the miss comes from how files were tagged or left out. `text` tells a footprint subagent how to tag files matching `match`, e.g. "Files under a generated/ directory are mechanical: they are regenerated, not read."
- **term**: the miss is a cost per matching file beyond its bytes. `tokens` is that cost per file, from the log: the tokens those files cost, minus what the formula already charged for them, divided by how many there were.

Propose `null` when no pattern explains most of the miss: the context went to retries, rate limits, wandering, or work outside the ticket. A wrong rule costs more than no rule.

## Return

Your final message is exactly one JSON object, or `null`:

```json
{"id": "migrations", "kind": "term", "text": "Each migration file in the footprint costs 15k beyond its bytes.",
 "match": "*/migrations/*.py", "tokens": 15000, "cites": ["<repo>#<ticket>"],
 "evidence": "3 migrations read 4 times each with test output: 52k of the 160k miss (turns 41-57)."}
```

The fields follow the rule schema in the docstring of `runtime/size_tickets_runtime/rules.py`, beside this file; leave out `enabled`, `proposed` and `rows`, which the caller fills in. `cites` is the row you were given. `evidence` is yours alone: the files or commands and their token figures.
