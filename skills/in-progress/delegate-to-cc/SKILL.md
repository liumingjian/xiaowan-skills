---
name: delegate-to-cc
description: Delegate a project problem to Claude Code on vps-2g and return its advice or patch for local review.
---

# Delegate to CC

Use Claude Code as a **second opinion**, never as the authority. Codex owns the handoff, the final judgment, and local verification.

## Process

1. Choose one mode:

   - `consult` for diagnosis, architecture, naming, prose, UI judgment, or another recommendation. Claude receives read-only tools. This is the default.
   - `implement` when the user explicitly wants Claude to produce a patch. Claude may edit the remote snapshot but cannot run shell commands.

   The mode is settled when the requested deliverable is either advice or a patch.

2. Write the handoff as Markdown, following `references/handoff.md` beside this file. Save it to a temporary path outside the project. The script reads the file and sends its contents as the prompt, so the handoff itself does not have to be inside the snapshot.

3. Close the transmission boundary. Run from the target project root. The script chooses a snapshot mode automatically:

   - In a Git project, it sends the current contents of tracked files and excludes `.git`, ignored files, and untracked files. If relevant work is untracked, inspect every entry from:

     ```bash
     git ls-files --others --exclude-standard
     ```

     Add `--include-untracked` only after every entry is relevant and safe to send.
   - In a non-Git project, it sends eligible files below the current directory, excluding `.git`, common dependency/build/cache directories, and obvious credential files. `--include-untracked` has no effect in this mode.

   The boundary is closed when all required context is included and no secret crosses it.

4. Keep the working directory at the target project root. Resolve `SKILL_DIR` to the directory containing this file, then run:

   ```bash
   "$SKILL_DIR/scripts/delegate.sh" \
     --mode consult \
     --prompt-file /absolute/path/to/handoff.md
   ```

   Use `implement` when selected above. Run `"$SKILL_DIR/scripts/delegate.sh" --help` for model, timeout, host, output, and untracked options. A successful run reports `SNAPSHOT_MODE=git|filesystem`, `STATUS=0`, and paths for `response.md`, `changes.patch`, `claude.stderr`, and `status`. On any other status, read the diagnostics and report the failed delegation.

5. Adjudicate locally:

   - For `consult`, require a non-empty response and an empty patch. Compare Claude's recommendation with project evidence.
   - For `implement`, read the complete response and patch. In a Git project, run `git apply --check` as a preflight; in a non-Git project, use `git apply --check` when Git is available or the host's patch dry-run for text-only changes. Then inspect every hunk. Apply only accepted changes through the host agent's normal editing mechanism.
   - Run local tests, type checks, or visual verification appropriate to the accepted change. Claude has no shell access in `implement` mode, so its test claims are not evidence.

   Finish only when the final report separates Claude's recommendation, Codex's judgment, and locally verified results. Preserve user changes made during the delegation.
