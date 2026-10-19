# Learn

`SKILL_DIR` is this skill's directory (beside this file); "Estimate steps" are the steps of SKILL.md's Estimate branch.

Run after a spec is implemented, from the repo that holds it. Compares the current skill version's estimate of each published ticket with the context peak its implementer actually reached, appends the results to `SKILL_DIR/calibration.tsv`, turns outliers into cited rules, prunes rules that no longer help, and refits the coefficients and repo offsets, all behind one regression guard. It writes only inside the temp directory and the skill's own repo (`SKILL_REPO` = `git -C SKILL_DIR rev-parse --show-toplevel`, the `xiaowan-skills` checkout), and changes to the shipped constants reach the user only as a PR.

1. **Estimate the published tickets.** Run Estimate steps 1–4 on `<spec>` as a published spec: its child tickets' bodies verbatim, since that is what the implementers received. Keep the temp directory, and save the estimate output as `<tmp>/estimate.json`. Human tickets are skipped there and stay out of everything below.
2. **Find the logs.** Claude Code keeps one directory per working directory under `~/.claude/projects`, named after the path with `/` and `.` replaced by `-`, and each worktree gets its own. Take every directory whose name starts with the repo root's encoded path (e.g. `/home/me/app` → `-home-me-app`, which also matches `-home-me-app--claude-worktrees-x`). Only read these logs; never write under `~/.claude/projects`.
3. **Measure.** Run `SKILL_DIR/bin/size-tickets measure --logs <dir> [--logs <dir> ...] <ticket> ...` with every estimated ticket number. It searches each directory recursively, subagent logs included, and prints one JSON line:
   - `tickets[]`: `ticket`, `peak` (the largest input context across the session's turns), `compacted`, `session` (the log file). A session belongs to a ticket when the first requested ticket named in its opening prompt is that ticket and the prompt's first sentence states an implementer role (`implement`, `implementer`, `实现`). This covers `/implement-spec` implementers and hand-opened sessions alike.
   - `skipped[]`: `session`, `tickets`, `reason`, `peak`. Reasons: `multi_ticket` (the first sentence names several requested tickets), `not_implementer` (a reviewer, merger or fixer naming the ticket), `no_usage` (no turn carried usage), `duplicate_implementer` (a second implementer for a ticket; the larger peak is kept).
   - `unmatched[]`: requested tickets with no implementer session.
4. **Report.** One table, in ticket order:

   | Ticket | Title | Estimate | Tier | Actual | Error | Compacted |
   |---|---|---|---|---|---|---|

   Estimate and Actual in k tokens. Error is `(estimate − actual) / actual` as a signed percent. Mark compacted tickets: their peak is a lower bound, because compaction cut the context. Under the table, list every `skipped` session with its reason and ticket, then the `unmatched` tickets.
5. **Record.** Write `<tmp>/rows.json` as `{"rows": [...]}` with one object per matched ticket:

   ```json
   {"repo": "github.com/owner/name", "spec": 36, "ticket": 39, "estimate": 98000, "actual": 105965,
    "semantic_bytes": 136000, "mechanical_files": 0, "compacted": false, "date": "2026-10-19"}
   ```

   `repo` is `git remote get-url origin` reduced to `host/owner/name` (no scheme, user, port or `.git`). `estimate`, `semantic_bytes` and `mechanical_files` come from step 1, `actual` and `compacted` from step 3, and `date` is today's UTC date. Run `SKILL_DIR/bin/size-tickets record <tmp>/rows.json`. It prints `{"calibration", "appended", "replaced"}`; a rerun replaces a ticket's existing row instead of adding a second one. Exit 2 with `{"error":"INVALID_REQUEST"}` means a row is malformed and nothing was written: fix it and rerun.
6. **Outliers.** A ticket is an outlier when its Error from step 4 is beyond ±50% and it is not compacted. Accurately estimated tickets get no subagent and produce no rule. Dispatch one subagent per outlier, all in a single message (Claude Code: `general-purpose` agent, `model: sonnet`), each prompt carrying only:

   ```
   Read SKILL_DIR/OUTLIER.md and follow it for row <repo>#<ticket>: implementation log <session>, estimate output <tmp>/estimate.json, estimated <estimate>, actual <actual>.
   ```

   Each returns one proposed rule, or `null` when no rule explains the miss. Done when every subagent has returned. Add each proposal to `RULES` in `SKILL_DIR/runtime/size_tickets_runtime/constants.py` with `"enabled": true` and `"proposed": true`, after the existing rules, completing it to the rule schema in the docstring of `SKILL_DIR/runtime/size_tickets_runtime/rules.py`; its `evidence` goes in the report and the PR, not into `RULES`. Its `cites` is its outlier row; its `rows` must hold every calibration row it changes, keyed `<repo>#<ticket>`:
   - This spec's rows, from `<tmp>/estimate.json`'s `files[]`: a **term** rule (`tokens` per footprint file matching `match`) gets `{"units": n}` for each ticket with n ≥ 1 matching files. A **tagging** rule (it changes how matching files are tagged) gets `null` for each ticket with a matching file, since that footprint must be re-tagged.
   - Earlier rows: when that repo is checked out locally, `null` for each row whose ticket's merged commits touch a file matching `match` (`git log --name-only --grep '#<ticket>\b'` in that repo). Leave every other row out: the backtest reuses its stored footprint.

   Two proposals with the same kind and `match`: keep the one whose outlier missed by more.
7. **Re-explore only affected rows.** Run `SKILL_DIR/bin/size-tickets backtest`. When `reasons` is `["needs_reexploration"]`, `reexplore[]` lists exactly the rows (`repo`, `ticket`, `rules`) that an enabled rule changes but whose effect is still `null`. For each, rerun Estimate steps 1–4 on that one published ticket, in that repo (FOOTPRINT.md now applies the enabled tagging rules), and set the rule's `rows["<repo>#<ticket>"]` from the output: `{"semantic_bytes": n, "mechanical_files": n}` for a tagging rule, `{"units": n}` from its `terms[]` for a term rule. Never re-explore a row that is not listed. A row you cannot re-explore (its repo is not available) comes out of the rule's `rows`; if it is the cited row, the rule comes out. Rerun the backtest until `reexplore` is empty.
8. **Backtest.** The last run of step 7, with `reexplore` empty, is the backtest: in one run it refits the coefficients and repo offsets over `calibration.tsv`, judges every rule, and guards the result against what ships. How it fits, and the guard's keep/delete/adopt semantics, are defined in the docstring of `SKILL_DIR/runtime/size_tickets_runtime/backtest.py`; read it when a verdict surprises you. `--disable <id>` and `--enable <id>` (repeatable) score with a shipped rule switched off or on.

   It prints one JSON line:
   - `before` (what ships: committed rules only, proposals left out) and `after` (refit with the kept rules), each `coefficients`, `offsets`, `rules` (enabled ids), `tier_accuracy`, `median_error` (median of |estimate − actual| / actual) and `within_50` (share of rows within ±50%); `after` is `null` when no fit was made.
   - `rules[]`: `id`, `kind`, `cites`, `enabled`, `proposed`, `verdict` (`keep` or `delete`) and `without` (the refit without it, or `null`).
   - `repos[]`: `repo`, `rows`, `offset` (`null` when it gets none).
   - `verdict`: `adopt`, or `refuse` with `reasons[]`: `tier_accuracy_dropped`, `median_error_rose`, `needs_reexploration` (back to step 7), `too_few_rows` (under 3 usable rows), `unchanged` (refit, offsets and rules equal the shipped ones), `no_fit`.
   - `rows` used and `excluded[]` (`repo`, `ticket`, `reason`).

   Show the user a before/after table of the three coefficients, the offsets, tier accuracy, median error and within ±50%, plus the verdict, then one line per rule: `id`, kind, cited rows, verdict, and the median error without it. A proposal deleted here did not beat the refit without it, so it is not adopted.
9. **Refused.** Say why, from `reasons`, and list the step 6 proposals so none is lost. Restore `constants.py` to its committed state (`git -C SKILL_REPO checkout -- skills/engineering/size-tickets/runtime/size_tickets_runtime/constants.py`) and change nothing else: no branch, no commit. The new rows stay uncommitted in `calibration.tsv`, so the next learning run fits over them too. Go to step 11.
10. **Adopted.** Ship the change as a PR for the user to merge; never merge it yourself.
    1. `git -C SKILL_REPO status --porcelain` must list only `calibration.tsv`, plus `constants.py` when step 6 added rules. Anything else: stop and tell the user, so their uncommitted work never rides along.
    2. `git -C SKILL_REPO switch -c size-tickets/learn-<repo name>-<spec>` from the current branch.
    3. Run `SKILL_DIR/bin/size-tickets backtest --adopt`. The same data gives the same verdict; it now rewrites `CALIBRATED`, `COEFFICIENTS`, `REPO_OFFSETS` and `RULES` (deleted rules removed, kept proposals without `proposed`) in `runtime/size_tickets_runtime/constants.py` and prints `"written": true`. Anything else: stop and report.
    4. Commit `calibration.tsv` and `constants.py` with `feat(size-tickets): learn from <repo> spec #<spec>`, push the branch, and open a PR against the repo's default branch with `gh pr create`. Write the body with the `pr` skill's template:
       - **Summary**: a `diff` of the `COEFFICIENTS` and `REPO_OFFSETS` blocks; each rule added or deleted, with its `text` and cited rows; the rows the fit used (count, repos, specs) and the rows re-explored.
       - **Evidence**: the backtest table, before → after, for tier accuracy, median error and within ±50%, with `rows` and `excluded`, and each rule's verdict with its median error without it.
       - **Merge Danger**: a two-way door (revert the commit); blast radius: every future estimate's numbers and tiers, and every footprint a tagging rule re-tags.
    5. `git -C SKILL_REPO switch -` back to the branch you started from, so the installed skill keeps the shipped constants until the user merges.
11. Delete the temp directory. Tell the user how many rows were appended or replaced in `calibration.tsv`, the rules proposed, kept and deleted, the verdict, and the PR link when one was opened.
