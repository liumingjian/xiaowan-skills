# rexec reference

Read this file for initial setup, service management, interrupted work, output filtering, or artifact publication. The normal dispatch workflow is in [SKILL.md](SKILL.md).

## Fixed channel

The only pair is `vps-cc` and one Mac mini. The Mac uses the existing SSH alias with its proxy, host-key policy, and 120-second connection timeout. That alias uses Cloudflare Access/Tunnel and local SOCKS; public SSH is closed. The runtime does not discover machines, select a host, or fail over.

A private dedicated worker credential binds the pair. Setup never prints it. Routing and receipts use opaque identifiers, not ComputerName, hostname, hardware UUID, source IP, or SSH fingerprints. Legacy machine flags and `REXEC_HOST`/`REXEC_MAC` overrides are rejected.

## Setup and service

The repository provides deployment and user-service tooling; changing the checkout does not deploy the VPS or install the Mac service. Live setup needs the user's instruction.

The VPS requires Python 3. Run `sudo bash install.sh` from this skill directory as the SSH account that will submit jobs. The installer preserves that initiating account as the owner of `/var/lib/rexec`, installs the three fixed endpoints under `/usr/local/bin`, places the Mac wrapper at `/var/lib/rexec/agent.sh`, and refuses an ambiguous direct-root installation. It replaces the runtime package as a whole and prints its `runtime` version. It does not provision a credential or start a service.

After each VPS installation, install or update the Mac worker with one line (needs `uv`):

```bash
mkdir -p ~/.rexec && ssh vps-cc 'cat /var/lib/rexec/agent.sh' > ~/.rexec/agent.sh && bash ~/.rexec/agent.sh
```

With no arguments, `agent.sh` pulls the wrapper and the runtime matching the VPS into `~/.rexec`, stops the worker and waits for launchd to unload it, swaps the runtime, provisions the credential if none exists, rewrites the LaunchAgent, and starts it. It then waits up to 60 seconds for the new worker to heartbeat to the VPS. Each step reports on stderr; stdout is one line. Success prints `{"updated":true,"connected":true,"runtime":...}`. Otherwise it restores the previous runtime (the failed one stays in `~/.rexec/runtime.failed`), restarts it, and prints `{"updated":false,"cause":...,"rolled_back":true,"running":...}` with exit 1. `cause` is the verify error, such as `WORKER_NOT_CONNECTED` with the failure reasons and log path, or `WORKER_CRASHED`. Running supervisors keep their deadlines across the restart. `rexec status` shows `channel.runtime_skew` while the two ends run different releases. The individual steps remain available:

```bash
bash agent.sh setup
bash agent.sh service install
bash agent.sh service start
bash agent.sh service status
bash agent.sh verify SINCE_EPOCH_SECONDS
bash agent.sh view [JOB]
```

`setup` provisions the dedicated credential through `vps-cc`. `service install` prepares the user LaunchAgent with explicit Python and program paths, environment, private stdout/stderr files, and restart policy. The service does not depend on interactive shell startup. Closing `view` leaves the service and supervisors running. `view` displays only safe events.

Supervisors run in separate sessions. The LaunchAgent also sets `AbandonProcessGroup` to preserve independent execution during worker shutdown, following [Apple's launchd contract](https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5).

```bash
bash agent.sh service stop
```

Stopping the worker pauses claims and reporting. Healthy job supervisors keep running with their own deadlines. Restarting the worker reconciles the local journal and durable outbox before claiming new work. Use `rexec cancel JOB` to stop a particular job.

## Submission and snapshots

The VPS CLI is:

```bash
rexec [--background] [--timeout SECONDS] [--sync DIR | --no-sync] [--cwd RELATIVE] [--with-git] [--include-ignored] [--request-id ID] [--label LABEL] [--wait-timeout SECONDS] 'shell command'
rexec status [JOB] [--all]
rexec queue
rexec wait JOB [--wait-timeout SECONDS]
rexec trace JOB [--after SEQUENCE]
rexec cancel JOB
rexec artifacts JOB --into DIR
rexec gc [--apply]
rexec feedback [JOB] --category CATEGORY [--note TEXT]
rexec feedback --close ID
rexec report [--since 7d]
```

Default submission durably enqueues, prints acceptance JSON on stderr, then waits up to 540 seconds (`--wait-timeout`), the same default as `rexec wait`. A wait that ends first exits 75 with `reason` `WAIT_TIMEOUT`, the server-side `job_state`, `channel`, and `timing`. While the channel is not `READY`, a new foreground submission is refused with `CHANNEL_<STATE>` and exit 75 before anything is queued. `--background` returns acceptance JSON immediately, whatever the channel state. A label is 1 to 64 letters, digits, spaces, or `._:/-`, starting with a letter or digit; anything else is refused with `LABEL_INVALID`.

`rexec status` lists one line per job, newest first: `job_id`, `state`, `age_s`, `label`, and, once finished, `outcome`, `exit_code`, `reason`, and `unread`. It lists queued and running jobs, unread results from the last day, and the five most recent others; `hidden` counts the rest, and `--all` or `rexec queue` lists up to 100. Output, artifacts, and timing stay behind `rexec status JOB`. Printing a finished result through `status JOB` or `wait` counts as reading it. Retrying a submission with the same `--request-id` is idempotent; retain that ID when recovering a lost acceptance response. Execution deadlines are finite, default 1800 seconds and range 1 to 86400. Wait timeout is separate from execution timeout.

`--no-sync` supplies an empty snapshot, not a previous project checkout. Submission freezes the input snapshot. The worker verifies its digest before extraction; rejected sync does not execute stale files.

Inside a Git work tree, sync takes the files Git would keep: tracked files plus untracked files that `.gitignore` does not exclude. `--include-ignored` takes ignored files too, for a build that needs generated inputs. Outside Git, sync takes the whole tree. Either way it excludes fixed secret paths (`.env*`, `.ssh`, `.netrc`, keys such as `*.pem`, and files named `secret`, `secrets`, `credential`, or `credentials` with any extension), dependency caches, `.codex-out/`, and `.git`. Explicit history transfer (`--with-git`) excludes Git hooks and local credential configuration. Links, sockets, and other special files are skipped. Keep handoffs outside excluded secret and dependency paths.

The acceptance JSON carries `snapshot`: `files`, `bytes`, whether `gitignore` applied, the `excluded` count, and the first ten `skipped` links with `skipped_count`. Check it when a file the command needs might be missing. Submission fails before anything is queued with a specific code: `SOURCE_NOT_FOUND`, `CWD_NOT_FOUND`, `CWD_INVALID`, `SNAPSHOT_TOO_LARGE` (over 64 MiB), `SNAPSHOT_TOO_MANY_FILES` (over 20000), `SNAPSHOT_UNSAFE_NAME`, or `SNAPSHOT_UNREADABLE`. The size and count errors include `at`, the path where the limit was crossed, usually inside a directory to ignore or exclude.

Commands sharing a source workspace execute serially. Different workspaces execute concurrently without a global limit. Each worker tick claims every available job (up to eight) and launches it in the same tick. An idle worker holds one claim open for up to 20 seconds, so a new job starts within a second while an idle Mac costs the VPS one SSH session per 20 seconds. The wait ends early for a cancel or a local result to report. Running jobs are reconciled when their state changes, when a cancel arrives, or every 15 seconds. A finished result travels in that same reconcile round trip; results over 8 MB in one round go separately. `rexec status` reports `channel.worker_timing`: the last tick and slowest SSH round trip in seconds, refreshed every 30 seconds. A slow `rpc` points at SSH connection setup; enable `ControlMaster`/`ControlPersist` for `vps-cc` in the Mac's SSH config. `channel.recent_failures` counts failed worker ticks from the last hour by fixed reason, and `channel.last_failure` names the latest one with its age. `RPC_TIMEOUT`, `SSH_FAILED`, and `RPC_INVALID` are transport failures; a server refusal keeps its own code, such as `AUTHORIZATION_REQUIRED`; `OS_ERROR` and `INTERNAL` are local; `WORKER_CRASH` counts a restart after a crash. The latest tick traceback stays private on the Mac in `tick.failure` and a crash traceback in `worker.failure`. Tool-native dependency caches can persist, but cache reuse must respect ownership and prevent concurrent unsafe mutation. For Python work, use `uv` and reuse a suitable environment. Dependencies needed inside a network-restricted tool must be prepared before delegation.

## Recovery and results

The VPS owns durable submission, claims, cancellation intent, safe events, and committed results. The Mac owns the execution journal, supervisors, private raw logs, and durable result outbox. SQLite transactions and fsynced immutable blobs preserve these records.

A claim request is durable before transport, so losing its response can be retried without claiming another job. Execution starts only after a durable launch record and gated supervisor agreement. Once start is reserved, arbitrary commands are never replayed automatically. Supervisors own the process group, finite deadline, and bounded log draining independently of SSH, the worker, or the caller.

Lost contact, expired authorization, and sleep are connectivity conditions. Inspect status and trace after contact returns. A reboot or unverifiable reused PID is not permission to rerun a command or signal that PID.

The worker checks each running job through its supervisor's file lock, which the kernel releases when the supervisor dies. A job whose supervisor never took the lock finishes `failed` with 126 and `LAUNCH_FAILED`: the command never started, so resubmitting is safe. A job whose supervisor died mid-run finishes `unknown` with 70 and `SUPERVISOR_LOST`: the command's process group was killed with its supervisor, so nothing still runs, but how far it got is unknown. An unknown result is terminal; it is never replayed, and the next job for the same source runs normally. Check whether its side effects happened before resubmitting.

The worker reports its complete list of held jobs with each heartbeat. A claimed job missing from that list for 10 minutes (Mac state lost, or a claim that never arrived) finishes `unknown` with `CLAIM_LOST`. A job the Mac fails to receive three times (corrupt or oversized snapshot) finishes `failed` with 126 and `CLAIM_REJECTED`. A result the VPS no longer tracks (after reinstallation or cleanup) is dropped from reporting and counted as `ORPHANED_RESULT` in worker health. Each job reconciles on its own, so one bad job never stalls the others.

The Mac seals a result before publication and retains its outbox until the VPS returns a matching job/digest acknowledgment after durable commit. Identical publication retries return the same acknowledgment; conflicting publications fail. Result completion and receipt acknowledgment are separate events. Repeated `wait` remains readable. Consumer and artifact acknowledgments follow validation and successful local writes.

| Result | Exit behavior |
|---|---|
| Command completed | Actual command exit code |
| Execution deadline expired | 124 |
| Explicitly cancelled | 125 |
| Wait deadline expired | 75, still pending |
| Never started (`LAUNCH_FAILED`, `CLAIM_REJECTED`, `SNAPSHOT_REJECTED`) | 126 |
| Unknown execution (`SUPERVISOR_LOST`, `CLAIM_LOST`, `EXECUTION_UNKNOWN`) | 70 |

Use the receipt's outcome to distinguish an infrastructure state from a program that returns the same numeric code. Every receipt carries `timing` in seconds: `queued_s` from submission to claim (growing while queued), `start_s` from Mac receipt to command start, `run_s` for the command itself, and `report_s` for the rest, mostly result delivery. A phase that has not happened yet, or was not recorded, is `null`. Wait interruption and viewer closure never cancel execution.

## Output and artifacts

One export implementation produces all outbound receipts, safe events, result summaries, manifests, and artifact contents. Receipts/status/trace are bounded JSON. Safe events correlate by opaque `job_id` and sequence, and contain phase, elapsed time or duration, attempt, outcome, and fixed reason codes. Command text, private absolute paths, raw SSH stderr, credentials, and physical machine identifiers are private.

Command output is capped to its head and tail around an explicit `... N chars omitted ...` line, so summaries and failures that print last survive without narrowing pipes. Filtering strips terminal controls, rewrites the job's own directories as `$WS`, `$TMPDIR`, and `$REXEC_ARTIFACTS` so tracebacks keep `path:line`, and redacts other known private home paths, addresses, fingerprint patterns, credentials, and configured private literals. A filtering failure returns empty output with `OUTPUT_BLOCKED`; it never substitutes raw output. This protects known data in constrained publication. It cannot prevent an arbitrary program from intentionally encoding hidden data and does not sandbox execution.

Raw logs stay owner-only on the Mac and keep their head and a rolling tail while pipes continue draining. Truncation is explicit. Diagnose from safe receipts and trace first; inspect local private logs only when the user explicitly requests it. The runtime does not enumerate unrelated home files.

To publish results, write only the requested regular UTF-8 text files beneath `$REXEC_ARTIFACTS`, using safe relative names. Artifacts have file/count/byte bounds. Allowed suffixes are `.md`, `.txt`, `.patch`, `.diff`, `.json`, `.xml`, and `.csv`. Traversal, binary content, secrets, configuration files, raw logs, and files over 2 MiB are refused one by one: the other artifacts are still published, and the receipt lists each refused file in `artifacts_refused` by name (an unsupported suffix is named too), or as `null` when the name itself is unsafe. A link or special file under `$REXEC_ARTIFACTS` refuses the whole set with `ARTIFACT_BLOCKED`. Prose is sanitized before hashing. A patch that needs sanitization is refused rather than modified, because rewriting a patch can corrupt it. Artifact refusal has no raw fallback.

`rexec artifacts JOB --into DIR` validates paths and hashes before atomic destination writes and acknowledgment. Artifact bytes never travel as base64 stdout. `delegate-to-codex` publishes only `response.md`, `changes.patch`, and `status.json`; its Codex JSONL and stderr stay on the Mac.

## Retention

Low disk space pauses claims and spawn. A finished job's Mac workspace, `$TMPDIR`, artifact staging, and snapshot are deleted as soon as its result is sealed, including unknown execution. Deletion renames the tree into `trash/` and a background `rm -rf` removes it, so cleanup never blocks the worker tick. GC preserves active jobs and unacknowledged results. Acknowledged results and private logs have a default retention of seven days. The server applies GC hourly on worker heartbeat; `rexec gc` previews eligible cleanup and `rexec gc --apply` applies it now. Cleanup does not cancel work or scan unrelated home files.

The VPS also keeps a per-job history for 90 days, independent of the seven-day cleanup: submission channel state, phase timings, outcome, reason, CLI usage counts, and a 12-character keyed command fingerprint that groups repeats of one command without storing it in an exportable form. The fingerprint key stays in `/var/lib/rexec`. Worker failure counts, CLI error codes, and agent feedback share the same 90-day history. Feedback notes are sanitized like output, refused above 280 characters (`FEEDBACK_TOO_LONG`) or with an unknown category (`FEEDBACK_CATEGORY`), and never appear in receipts or traces. `rexec feedback --close ID` marks a note handled; closing twice is a no-op and an unknown ID exits 66 with `FEEDBACK_NOT_FOUND`.

`rexec report [--since Nh|Nd]` (default `7d`, at most `90d`) aggregates jobs submitted in the window into one JSON object:

- `window`: job and failure counts. A failure is any finished job whose outcome is not `completed` or whose exit code is nonzero.
- `outcomes`: counts by `outcome:reason`.
- `timing`: `count`, `p50`, and `p95` per phase.
- `health`: worker failure counts by reason.
- `usage`: jobs submitted while the channel was not `READY`, results unread and artifacts unfetched a day after completion, wait timeouts, status/wait/trace call totals and per-job maximum, and CLI errors by `subcommand:reason`.
- `failing_commands`: the ten command fingerprints with the most failures, with run counts and last reason.
- `feedback`: open notes counted by category, the number closed, and the 20 most recent open notes with their `id`.
