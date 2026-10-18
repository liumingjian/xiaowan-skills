---
name: rexec
description: Run builds, dependency installation, test suites, services for end-to-end checks, and other memory-intensive or long-running commands from vps-cc on the user's Mac mini. Use for durable background work, collecting results, text artifacts, or built packages, inspecting the queue or safe trace, cancelling jobs, and cleaning retained work.
---

# rexec

`rexec` sends a frozen project snapshot from `vps-cc` to one Mac mini. A user background service pulls jobs; independent supervisors execute them with finite deadlines. Jobs survive conversation loss, interrupted waits, closed viewers, and worker restarts.

## Workflow

1. Run `rexec status` to see the channel and the jobs that need attention: queued or running jobs, unread results from the last day, and the five most recent others, one line each (`--all` lists up to 100). For initial setup, authorization, or service management, read [REFERENCE.md](REFERENCE.md#setup-and-service). Report the required action without installing or changing a live service unless the user requested it.
   - `rexec` not on PATH → the VPS side is not installed: report `sudo bash install.sh` from this skill directory and stop.
   - `channel.state` is `AUTHORIZATION_REQUIRED` → the Mac side is not set up: report this one line for the Mac (needs `uv`) and stop: `mkdir -p ~/.rexec && ssh vps-cc 'cat /var/lib/rexec/agent.sh' > ~/.rexec/agent.sh && bash ~/.rexec/agent.sh`. The same line updates the Mac worker after every VPS installation.
   - `channel.runtime_skew` is present → the Mac runs a different release than the VPS. Jobs still run, but report the same update line to the user.
   - `channel.state` is `OFFLINE` or `LOW_SPACE` → the Mac cannot run work now. Foreground submission is refused with `CHANNEL_OFFLINE` or `CHANNEL_LOW_SPACE` (exit 75); report it, or queue with `--background` if the user wants the job to run when the Mac returns.
2. Submit the command from the project root. Add `--label 'short name'` so the job is recognizable in `rexec status`. The default sync captures the current directory; use `--sync DIR` for another source, `--cwd RELATIVE` for a subdirectory, or `--no-sync` for a fresh empty workspace when checking system tools. In a Git repository only files Git keeps are synced (add `--include-ignored` for ignored inputs); links are skipped and listed in the acceptance's `snapshot`. Add `--with-git` only when the command needs history. Keep the command unattended and run it bare: rexec keeps long output's head and tail, and the receipt's exit status is the command's own.

   ```bash
   rexec --label tests 'pytest -q'
   rexec --sync ./project --cwd frontend 'npm run build'
   rexec --no-sync 'node --version'
   ```

   Submit in the foreground only what finishes in about a minute (a version check, a typecheck, one test file). A foreground submission prints `{"accepted":true,"job_id":...}` on stderr first, then waits up to 540 seconds (`--wait-timeout` changes it) and prints the receipt on stdout. If the wait ends first, it prints pending with `job_state` and `channel` and exits 75; the job keeps running, so continue with `rexec wait JOB` instead of resubmitting.

   From a Claude Code worktree session, a guard refuses payloads it cannot read. Write the command literally: run a script as `./run.sh` after `chmod +x` (not `bash run.sh`), pass literal arguments and job ids (not `$(...)` or `$VAR`), and submit each job as its own command (not inside a loop).
3. Anything longer (installs, builds, whole suites) runs in the background, and you keep working while it runs. Every job has an execution deadline of 1 to 86400 seconds, default 1800; set `--timeout` to the required finite bound.
   1. Tell the user how long the job should take, then submit with `--background` and save `job_id` from the acceptance JSON. A receipt saying accepted confirms submission, not completion.
   2. Start one `rexec wait JOB` with `--wait-timeout` above the job's `--timeout`, as a background shell command that notifies you when it exits (Claude Code: Bash with `run_in_background`).
   3. Spend the wait on the next edit, a review, or another independent job; the Mac runs jobs in parallel. Whole test suites are the exception: run them one at a time, since two at once push timing-sensitive tests into timeouts. Judge whether the Mac is busy by CPU use (`rexec --no-sync 'top -l 2 -o cpu -n 10'`): it has 12 cores and 64 GB, so a load average of 5 to 15 is normal.
   4. Read the receipt when the notification arrives.

   ```bash
   rexec --background --timeout 3600 --label build 'cargo build --release'   # → job_id
   rexec wait JOB --wait-timeout 3700                                        # as a background shell command
   ```

   One background wait replaces every status poll and `sleep` loop. `rexec status JOB` and `rexec trace JOB --after 0` answer a question about a job you are already waiting on; they are not a way to wait.

4. Read the terminal receipt and exit status. Successful completion returns 0; command failures pass through their exit codes. Timeout returns 124, cancellation 125, and an expired wait returns pending with 75. Exit 126 with outcome `failed` means the command never started; fix the reported reason and resubmit. Outcome `unknown` (exit 70) means the command may have partly run: check its side effects before resubmitting, never assume it failed. See [REFERENCE.md](REFERENCE.md#recovery-and-results) for recovery and acknowledgment behavior.
5. Fetch requested artifacts with `rexec artifacts JOB --into DIR`. Commands publish them as bounded regular files beneath `$REXEC_ARTIFACTS`: UTF-8 text, or a build output packaged as `.zip`, `.vsix`, `.whl`, `.jar`, `.tgz`, or `.tar.gz`; zip any other binary first. Use `$TMPDIR` for private scratch files. Verify the collected result before claiming the work passed. See [REFERENCE.md](REFERENCE.md#output-and-artifacts) for export limits.

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

Reserve it for surprises; a job that behaved as documented needs no note. Keep the note to 280 characters of plain description, without command text, paths, or output. When the user asks how rexec is doing or what to improve, run `rexec report` and summarize its failures, slow phases, health, usage, and notes into concrete fixes. The report lists only open notes, each with an `id`; once a note's fix ships or the note needs no action, run `rexec feedback --close ID`.

## Privacy

Use structured receipts, safe traces, and validated artifacts as the returned evidence. Raw command logs and SSH diagnostics remain private on the Mac. Export strips known private data and terminal controls; a filter failure returns `OUTPUT_BLOCKED` without a raw fallback. This is known-data filtering, not a sandbox or a guarantee against a program deliberately encoding hidden data. Read [REFERENCE.md](REFERENCE.md#output-and-artifacts) when publishing a new artifact type or investigating blocked output. Local private logs require an explicit user request before inspection.
