---
name: size-tickets
description: Estimate each ticket's implementer context peak and tier before slicing is final.
disable-model-invocation: true
---

# size-tickets

Estimates how much context an implementer subagent will peak at for each ticket, against a 150k budget, and returns one table. The estimate is a **footprint** (the files the implementer must read and change) priced by a fixed formula: base + k₁ × semantic bytes + k₂ × mechanical file count.

Branches, picked from the argument:

- `/size-tickets` with drafts in this conversation, `/size-tickets <spec>`, or `/size-tickets <ticket> <ticket> ...` → **Estimate**.
- `/size-tickets learn <spec>` → **Learn**.

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
   {"repo": "<repo root>",
    "tickets": [{"id": "#12", "title": "...", "human": false, "labels": [], "blocked_by": ["#11"],
                 "footprint": [{"path": "src/a.py", "kind": "semantic", "group": "parse totals"}]}]}
   ```

   `footprint` is the subagent's list as returned, `group` included. Byte counts are measured by the CLI from the files on disk (as `wc -c` does); the request never carries a model-written number.
4. **Estimate.** Run `SKILL_DIR/bin/size-tickets estimate <tmp>/request.json`. It prints one JSON line: `calibrated`, `budget`, `tickets[]`, `skipped[]` and `merges[]`. Each ticket has `estimate`, `tier`, `semantic_bytes`, `mechanical_files`, `files[]` (sized per path; `exists: false` marks files the ticket creates), `breakdown[]` (its three most expensive groups: `group`, `tokens`, `files`, `largest`) and `split` (`null` unless the ticket is over budget). Exit 2 with `{"error":"INVALID_REQUEST"}` means the request is malformed: fix it and rerun.

   The CLI makes every proposal, so never dispatch another subagent or redo the arithmetic yourself:
   - **Split** (oversized and must_split): the split line falls between groups. A group is the subagent's `group` tag, or the file's directory when untagged (`split.by` says which). Groups are taken in sorted order and packed into parts while each part's recomputed estimate stays within budget; a group too big alone is cut file by file. Each `split.parts[]` entry has `id` (`<ticket>.1`, ...), `groups`, `paths`, `estimate` and `tier`.
   - **Merge**: `merges[]` holds a pair only when both tickets are undersized, they are directly adjacent on a blocking chain or share footprint files (`reasons`: `blocking`, `shared_files`), and the recomputed union (shared files counted once) stays within budget. Unrelated small tickets are never paired.
5. **Report.** One table, in the input's ticket order:

   | Ticket | Title | Estimate | Tier | Semantic KB | Mechanical files | Footprint from | Proposal |
   |---|---|---|---|---|---|---|---|

   Estimates in k tokens. Tiers: `undersized` (< 50k), `fits` (≤ 150k), `oversized` (< 300k), `must_split` (≥ 300k). **Footprint from** lists each `breakdown` entry as `group (largest) Nk`, e.g. `src/api (src/api/b.py) 80k`. **Proposal** is one of:
   - `split → #7.1 [export] 110k fits; #7.2 [model, view] 140k fits`, one entry per part;
   - `merge with #2 → 45k undersized (blocking)`, for each `merges` pair naming the ticket;
   - `—` when there is none.

   Under the table, list skipped tickets with their reason. When `calibrated` is false, open the report with: **Uncalibrated: placeholder coefficients, so read tiers as rough guidance.**
6. Delete the temp directory.

## Learn

Not yet available. Tell the user that `learn` ships in a later version and stop.
