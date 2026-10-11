---
name: delegate-to-codex
description: Send this project to Codex on the paired Mac mini for a second opinion or a patch.
---

# Delegate to Codex

Use the Codex CLI on the paired Mac mini through `rexec`. You own the handoff, final judgment, and verification. This skill is user-invoked and consumes Codex quota.

## Process

1. Dispatch a subagent with this file and the handoff path. Require a receipt of at most fifty lines with verdict, findings, artifact paths, `JOB_ID`, and `THREAD_ID`. The subagent runs the delegation and never applies a patch.
2. Choose `consult` for advice or review, or `implement` for an agreed change. Consult is read-only and returns an empty patch; implement can edit and run checks in the synced copy. The default model is `gpt-6-astra` with `xhigh` effort. If the user already chose a model or effort, use it. Otherwise settle the choice once before dispatch and pass it through `--model` and `--effort`.
3. Write the handoff under the project root using [references/handoff.md](references/handoff.md). Keep it outside rexec's fixed secret and dependency exclusions. If the task needs dependencies, prepare the workspace through `rexec` first; the Codex workspace-write sandbox has no network.
4. From the project root, run the wrapper, resolving `SKILL_DIR` to this skill's directory:

   ```bash
   "$SKILL_DIR/scripts/delegate.sh" --mode consult --prompt-file ./handoff.md \
     --model gpt-6-astra --effort xhigh
   ```

   Add `--with-git` for history-based review and `--resume THREAD_ID` for explicit continuation. See `--help` for timeout and output options. The wrapper submits durably in the background, prints `JOB_ID`, waits, and fetches `response.md`, `changes.patch`, and `status.json` under `.codex-out/`. `STATUS=0` indicates Codex success. Other command exit codes pass through; 124 means execution timeout, 125 cancellation, and 75 a pending wait. Read the safe error and status before deciding whether another submission is appropriate.
5. Read the response in full. For implement mode, run `git apply --check`, inspect every hunk, and show the diff to the user. Apply accepted changes yourself and rerun the relevant checks through `rexec`. Finish when every hunk has a deliberate disposition and accepted changes pass verification. Codex's own test claims guide review; they do not replace your checks.

## Recovery and privacy

`rexec` connects only `vps-cc` and the paired Mac mini. Setup and user-service management belong to the [rexec skill](../../engineering/rexec/SKILL.md). A closed viewer, interrupted wait, or lost conversation leaves the job running until completion, explicit cancellation, or its finite deadline. Recover with `rexec wait JOB` and `rexec artifacts JOB --into DIR`; never automatically resubmit an unknown outcome.

Codex JSONL and stderr remain bounded private files on the Mac. Use the safe response, patch, and status as evidence. Output filtering can block export, and a patch requiring sanitization is refused intact. There is no raw-log fallback or automatic private-log inspection. Filtering covers known private data; it cannot prevent a program deliberately encoding hidden data.

`implement` records a disposable baseline inside the synced workspace so its patch contains only Codex's changes. Consult leaves history intact. `--with-git` transfers real history with rexec's credential/hook exclusions. Validate the returned patch before use and keep returned results in the fixed-excluded `.codex-out/` directory or outside the synced source. `.gitignore` does not control rexec transfer.
