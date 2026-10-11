---
name: rexec
description: Run builds, dependency installation, test suites, services for end-to-end checks, and other memory-intensive or long-running commands from vps-cc on the user's Mac mini. Use for durable background work, collecting results or text artifacts, inspecting the queue or safe trace, cancelling jobs, and cleaning retained work.
---

# rexec

`rexec` sends a frozen project snapshot from `vps-cc` to one Mac mini. A user background service pulls jobs; independent supervisors execute them with finite deadlines. Jobs survive conversation loss, interrupted waits, closed viewers, and worker restarts.

## Workflow

1. Run `rexec status` to inspect existing work. For initial setup, authorization, or service management, read [REFERENCE.md](REFERENCE.md#setup-and-service). Report the required action without installing or changing a live service unless the user requested it.
   - `rexec` not on PATH → the VPS side is not installed: report `sudo bash install.sh` from this skill directory and stop.
   - `channel.state` is `AUTHORIZATION_REQUIRED` → the Mac side is not set up: report `bash agent.sh setup`, `bash agent.sh service install`, `bash agent.sh service start` (needs `uv`) and stop.
2. Submit the command from the project root. The default sync captures the current directory; use `--sync DIR` for another source, `--cwd RELATIVE` for a subdirectory, or `--no-sync` for a fresh empty workspace when checking system tools. Add `--with-git` only when the command needs history. Keep the command unattended and run it bare: rexec keeps long output's head and tail, and the receipt's exit status is the command's own.

   ```bash
   rexec 'pytest -q'
   rexec --sync ./project --cwd frontend 'npm run build'
   rexec --no-sync 'node --version'
   ```

3. For work to collect later, submit with `--background` and save `job_id` from the acceptance JSON. Every job has an execution deadline of 1 to 86400 seconds, default 1800. Set `--timeout` to the required finite bound. A receipt saying accepted confirms submission, not completion.

   ```bash
   rexec --background --timeout 3600 'cargo build --release'
   rexec wait JOB --wait-timeout 60
   rexec trace JOB --after 0
   ```

4. Read the terminal receipt and exit status. Successful completion returns 0; command failures pass through their exit codes. Timeout returns 124, cancellation 125, and an expired wait returns pending with 75. Connectivity loss or unknown execution is not evidence that the command failed. Inspect `rexec status JOB` and `rexec trace JOB`; reconcile before deciding whether another submission is safe. See [REFERENCE.md](REFERENCE.md#recovery-and-results) for recovery and acknowledgment behavior.
5. Fetch requested text artifacts with `rexec artifacts JOB --into DIR`. Commands publish them as bounded regular UTF-8 files beneath `$REXEC_ARTIFACTS`. Use `$TMPDIR` for private scratch files. Verify the collected result before claiming the work passed. See [REFERENCE.md](REFERENCE.md#output-and-artifacts) for export limits.

## Management

When the user requests queue, status, trace, cancellation, or cleanup, run the corresponding command directly:

```bash
rexec status [JOB]
rexec queue
rexec trace JOB [--after SEQUENCE]
rexec cancel JOB
rexec gc
rexec gc --apply
rexec report [--since 7d]
```

Inspect the cleanup preview before applying it. Explicit cancellation stops only that job. Closing a viewer or interrupting `wait` leaves execution running until completion, explicit cancellation, or its deadline.

## Feedback

When rexec surprises you or gets in your way (a confusing receipt, an unexplained failure, slowness, a missing capability, unclear docs), record one note as you move on:

```bash
rexec feedback [JOB] --category confusing_output|unexpected_failure|slow|missing_capability|docs_unclear|other --note 'what you expected and what happened'
```

Reserve it for surprises; a job that behaved as documented needs no note. Keep the note to 280 characters of plain description, without command text, paths, or output. When the user asks how rexec is doing or what to improve, run `rexec report` and summarize its failures, slow phases, health, usage, and notes into concrete fixes.

## Privacy

Use structured receipts, safe traces, and validated text artifacts as the returned evidence. Raw command logs and SSH diagnostics remain private on the Mac. Export strips known private data and terminal controls; a filter failure returns `OUTPUT_BLOCKED` without a raw fallback. This is known-data filtering, not a sandbox or a guarantee against a program deliberately encoding hidden data. Read [REFERENCE.md](REFERENCE.md#output-and-artifacts) when publishing a new artifact type or investigating blocked output. Local private logs require an explicit user request before inspection.
