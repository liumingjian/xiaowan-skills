---
name: size-tickets
description: Estimate each ticket's implementer context peak and tier before slicing is final.
disable-model-invocation: true
---

# size-tickets

Estimates how much context an implementer subagent will peak at for each ticket, against a 150k budget, and returns one table. The estimate is a **footprint** (the files the implementer must read and change) priced by a fixed formula: base + k₁ × semantic bytes + k₂ × mechanical file count, plus the repo's offset and any learned cost-term rules, all shipped in `runtime/size_tickets_runtime/constants.py`.

Branches, picked from the argument:

- `/size-tickets` with drafts in this conversation, `/size-tickets <spec>`, or `/size-tickets <ticket> <ticket> ...` → **Estimate**.
- `/size-tickets learn <spec>` → **Learn**: read [LEARN.md](LEARN.md) and follow it. It reuses Estimate steps 1–4 below.

`SKILL_DIR` below is this skill's directory.

## Estimate

Stateless: every run re-estimates every ticket from scratch. Read no repo config, keep no cache, and write only inside the temp directory, which you delete at the end. The report goes to the user only: tickets stay unedited and nothing is posted to the tracker.

1. **Drafts.** Run `mktemp -d /tmp/size-tickets.XXXXXX` and write one Markdown file per ticket into it, named `<id>.md`:
   - Drafts in the conversation: title, what it delivers, acceptance criteria, blockers, a pointer to the spec, and `human: true` when the draft is marked human. Ids are the draft numbers you showed the user.
   - A published spec or ticket list: read each ticket through the repo's issue-tracker doc (`docs/agents/issue-tracker.md` or whatever the repo's agent docs name), and for a spec, collect its child tickets. Write the body verbatim plus its labels and blockers. Ids are the tracker's ticket numbers.

   Done when every ticket has a file. Human tickets (`human: true`, or the `ready-for-human` label, or the repo's equivalent in its triage-labels doc) get a file too, since the CLI lists them as skipped; they get no subagent.
2. **Footprints.** Dispatch one read-only subagent per non-human ticket, all in a single message so they run in parallel (Claude Code: `Explore` agent, `model: sonnet`). Each prompt carries only:

   ```
   Read SKILL_DIR/FOOTPRINT.md and follow it for the draft at <tmp>/<id>.md in the repo at <repo root>.
   ```

   with `Code map: <path>` appended when this session already has one. Done when every subagent has returned its footprint JSON.
3. **Request.** Write `<tmp>/request.json`:

   ```json
   {"repo": "<repo root>", "remote": "github.com/owner/name",
    "tickets": [{"id": "#12", "title": "...", "human": false, "labels": [], "blocked_by": ["#11"],
                 "footprint": [{"path": "src/a.py", "kind": "semantic", "group": "parse totals"}]}]}
   ```

   `footprint` is the subagent's list as returned, `group` included. Byte counts are measured by the CLI from the files on disk (as `wc -c` does); the request never carries a model-written number. `remote` is `git remote get-url origin` reduced to `host/owner/name` (no scheme, user, port or `.git`); leave it out when the repo has no `origin`. It selects the repo's shipped offset, if it has one.
4. **Estimate.** Run `SKILL_DIR/bin/size-tickets estimate <tmp>/request.json`. It prints one JSON line: `calibrated`, `budget`, `tickets[]`, `skipped[]` and `merges[]`. Each ticket has `estimate`, `tier`, `semantic_bytes`, `mechanical_files`, `files[]` (sized per path; `exists: false` marks files the ticket creates), `breakdown[]` (its three most expensive groups: `group`, `tokens`, `files`, `largest`), `offset` (the repo's, included in `estimate`), `terms[]` (each learned cost-term rule its footprint triggered: `rule`, `units`, `tokens`, included in `estimate`) and `split` (`null` unless the ticket is over budget). Exit 2 with `{"error":"INVALID_REQUEST"}` means the request is malformed: fix it and rerun.

   The CLI makes every split and merge proposal; report them as printed and leave the arithmetic to it. A ticket's `split.parts[]` entries each have `id` (`<ticket>.1`, ...), `groups`, `paths`, `estimate` and `tier`; each `merges[]` pair has `tickets`, `reasons`, `paths`, `estimate` and `tier`.
5. **Report.** One table, in the input's ticket order:

   | Ticket | Title | Estimate | Tier | Semantic KB | Mechanical files | Footprint from | Proposal |
   |---|---|---|---|---|---|---|---|

   Estimates in k tokens. Tiers: `undersized` (< 50k), `fits` (≤ 150k), `oversized` (< 300k), `must_split` (≥ 300k). **Footprint from** lists each `breakdown` entry as `group (largest) Nk`, e.g. `src/api (src/api/b.py) 80k`, then each `terms` entry as `rule ×units Nk`. **Proposal** is one of:
   - `split → #7.1 [export] 110k fits; #7.2 [model, view] 140k fits`, one entry per part;
   - `merge with #2 → 45k undersized (blocking)`, for each `merges` pair naming the ticket;
   - `—` when there is none.

   Under the table, list skipped tickets with their reason. When `calibrated` is false, open the report with: **Uncalibrated: placeholder coefficients, so read tiers as rough guidance.**
6. Delete the temp directory.
