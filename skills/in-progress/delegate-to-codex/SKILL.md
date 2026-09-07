---
name: delegate-to-codex
description: Send this project to Codex on the user's Mac for a second opinion or a patch. Use when the user wants a spec, plan, page, or change reviewed by Codex, or an agreed plan carried out by Codex.
---

# Delegate to Codex

The mirror of `delegate-to-cc`: that one hands work from Codex to Claude Code on `vps-2g`, this one hands
work from here to the **Codex CLI on the user's Mac**. Codex is a **second opinion**, never the authority.
You own the handoff, the final judgment, and verification.

The server cannot reach the Mac (home NAT), so the only channel is the `rexec` skill: the Mac's resident
agent pulls the job. `rexec` also decides **which** Mac — the one this session ssh'd in from, identified by
`ComputerName` plus a hardware-UUID hash rather than by IP, so a changing IP never misroutes a job.
`scripts/delegate.sh` wraps all of it.

## Process

1. **Dispatch a sub-agent.** Codex output runs to thousands of lines; keeping it out of this context is the
   point. Give the sub-agent this file, the handoff path, and the mode, and require **a receipt back**:
   verdict, findings, artifact paths, `THREAD_ID`. Fifty lines, no transcript.

2. **Choose one mode.**

   - `consult` (default) for review, diagnosis, architecture, or a recommendation. Codex is sandboxed
     read-only and the patch comes back empty.
   - `implement` when the user wants Codex to carry out an agreed plan. Codex may edit the synced copy and
     run commands in it.

   The mode is settled when the requested deliverable is either advice or a patch.

3. **Write the handoff** as Markdown, following `references/handoff.md` beside this file. Save it under
   the project root and check that `.gitignore` does not match it: `rexec` syncs the directory, and a
   handoff it would never carry is refused rather than sent as a dangling path.

4. **Install dependencies first, if the task needs them.** The Codex sandbox has **no network**, so a build
   or test run inside it fails on a missing dependency. Split the work the way the two channels split:
   **`rexec` runs, Codex thinks and writes.** Use `/rexec` to install and warm the workspace, then delegate.

5. **Run it from the project root** (`rexec` syncs the current directory). Resolve `SKILL_DIR` to the
   directory holding this file:

   ```bash
   "$SKILL_DIR/scripts/delegate.sh" --mode consult --prompt-file ./handoff.md
   ```

   Add `--with-git` when the review depends on history — a base-branch or single-commit review, or "what
   changed and why". It syncs the whole repository history, so leave it off otherwise. Add
   `--resume <THREAD_ID>` to continue an earlier Codex thread. See `--help` for mac, model, timeout, and
   output options. A successful run prints `STATUS=0` plus paths for `response.md`, `changes.patch`, and
   `codex.jsonl`; the bulk stays on disk under `.codex-out/`, never in context. On any other status, read the
   error line — it names the next action — and report the failed delegation rather than retrying blind.
   On `GITIGNORE_HINT`, add `.codex-out/` to `.gitignore`.

6. **Adjudicate here.** Read `response.md` in full. For `implement`, run `git apply --check` as a preflight,
   then inspect **every hunk** and show the user the diff. Apply only what the user accepts, and apply it
   yourself — the sub-agent never applies a patch. Codex's own test runs help it converge and are not
   evidence: re-run the checks through `/rexec` on the applied result.

   Done when every hunk is accepted or rejected on purpose, and the accepted ones pass a real run.

## Notes

- The Mac workspace is not a clone of your repo unless you ask for one: `rexec` excludes `.git` by default.
  In `implement` mode `delegate.sh` commits a disposable baseline there purely to diff against, so the patch
  holds Codex's edits and nothing else. `--with-git` brings the real history over, which is what makes
  `codex exec review --base <branch>` possible in the handoff.
- `--with-git` needs a Mac agent new enough to know the flag. If `rexec` refuses, ask the user to restart the
  agent on that Mac; a second Mac being ready is not a reason to retarget.
