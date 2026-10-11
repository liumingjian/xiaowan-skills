# rexec reference

Read this file for initial setup, service management, interrupted work, output filtering, or artifact publication. The normal dispatch workflow is in [SKILL.md](SKILL.md).

## Fixed channel

The only pair is `vps-cc` and one Mac mini. The Mac uses the existing SSH alias with its proxy, host-key policy, and 120-second connection timeout. That alias uses Cloudflare Access/Tunnel and local SOCKS; public SSH is closed. The runtime does not discover machines, select a host, or fail over.

A private dedicated worker credential binds the pair. Setup never prints it. Routing and receipts use opaque identifiers, not ComputerName, hostname, hardware UUID, source IP, or SSH fingerprints. Legacy machine flags and `REXEC_HOST`/`REXEC_MAC` overrides are rejected.

## Setup and service

The repository provides deployment and user-service tooling; changing the checkout does not deploy the VPS or install the Mac service. Live setup needs the user's instruction.

After the VPS installation is available, use the Mac wrapper:

The VPS requires Python 3. Run `sudo bash install.sh` from this skill directory as the SSH account that will submit jobs. The installer preserves that initiating account as the owner of `/var/lib/rexec`, installs the three fixed endpoints under `/usr/local/bin`, and refuses an ambiguous direct-root installation. It does not provision a credential or start a service. On the Mac, `agent.sh` uses `uv` to locate Python; install the worker from a stable copy of the skill so its executable and package paths remain available.

```bash
bash agent.sh setup
bash agent.sh service install
bash agent.sh service start
bash agent.sh service status
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
rexec [--background] [--timeout SECONDS] [--sync DIR | --no-sync] [--cwd RELATIVE] [--with-git] [--request-id ID] 'shell command'
rexec status [JOB]
rexec queue
rexec wait JOB [--wait-timeout SECONDS]
rexec trace JOB [--after SEQUENCE]
rexec cancel JOB
rexec artifacts JOB --into DIR
rexec gc [--apply]
```

Default submission durably enqueues, then waits. `--background` returns acceptance JSON immediately. Retrying a submission with the same `--request-id` is idempotent; retain that ID when recovering a lost acceptance response. Execution deadlines are finite, default 1800 seconds and range 1 to 86400. Wait timeout is separate from execution timeout.

`--no-sync` supplies an empty snapshot, not a previous project checkout. Submission freezes the input snapshot. The worker verifies its digest before extraction; rejected sync does not execute stale files. Sync excludes fixed secret paths, dependency caches, `.codex-out/`, and `.git` by default. Explicit history transfer excludes Git hooks and local credential configuration. Snapshot validation rejects unsafe paths, links, special files, and excessive file counts or bytes. Snapshot exclusions are fixed; do not infer them from `.gitignore`. Keep handoffs outside excluded secret and dependency paths.

Commands sharing a source workspace execute serially. Other workspaces can execute up to the configured concurrency bound. Tool-native dependency caches can persist, but cache reuse must respect ownership and prevent concurrent unsafe mutation. For Python work, use `uv` and reuse a suitable environment. Dependencies needed inside a network-restricted tool must be prepared before delegation.

## Recovery and results

The VPS owns durable submission, claims, cancellation intent, safe events, and committed results. The Mac owns the execution journal, supervisors, private raw logs, and durable result outbox. SQLite transactions and fsynced immutable blobs preserve these records.

A claim request is durable before transport, so losing its response can be retried without claiming another job. Execution starts only after a durable launch record and gated supervisor agreement. Once start is reserved, arbitrary commands are never replayed automatically. Supervisors own the process group, finite deadline, and bounded log draining independently of SSH, the worker, or the caller.

Lost contact, expired authorization, and sleep are connectivity conditions. Inspect status and trace after contact returns. Missing execution evidence produces an unknown outcome and keeps its workspace reserved. A reboot or unverifiable reused PID is not permission to rerun a command or signal that PID.

The Mac seals a result before publication and retains its outbox until the VPS returns a matching job/digest acknowledgment after durable commit. Identical publication retries return the same acknowledgment; conflicting publications fail. Result completion and receipt acknowledgment are separate events. Repeated `wait` remains readable. Consumer and artifact acknowledgments follow validation and successful local writes.

| Result | Exit behavior |
|---|---|
| Command completed | Actual command exit code |
| Execution deadline expired | 124 |
| Explicitly cancelled | 125 |
| Wait deadline expired | 75, still pending |
| Unknown execution | Distinct nonzero status with a fixed reason code |

Use the receipt's outcome to distinguish an infrastructure state from a program that returns the same numeric code. Wait interruption and viewer closure never cancel execution.

## Output and artifacts

One export implementation produces all outbound receipts, safe events, result summaries, manifests, and artifact contents. Receipts/status/trace are bounded JSON. Safe events correlate by opaque `job_id` and sequence, and contain phase, elapsed time or duration, attempt, outcome, and fixed reason codes. Command text, private absolute paths, raw SSH stderr, credentials, and physical machine identifiers are private.

Necessary command output is capped. Filtering strips terminal controls and redacts known private home/workspace paths, addresses, fingerprint patterns, credentials, and configured private literals. A filtering failure returns empty output with `OUTPUT_BLOCKED`; it never substitutes raw output. This protects known data in constrained publication. It cannot prevent an arbitrary program from intentionally encoding hidden data and does not sandbox execution.

Raw logs stay owner-only on the Mac and are capped while pipes continue draining. Truncation is explicit. Diagnose from safe receipts and trace first; inspect local private logs only when the user explicitly requests it. The runtime does not enumerate unrelated home files.

To publish results, write only the requested regular UTF-8 text files beneath `$REXEC_ARTIFACTS`, using safe relative names. Artifacts have file/count/byte bounds. Links, traversal, binary content, secrets, configuration files, and raw logs are refused. Prose is sanitized before hashing. A patch that needs sanitization is refused rather than modified, because rewriting a patch can corrupt it. Artifact refusal has no raw fallback.

`rexec artifacts JOB --into DIR` validates paths and hashes before atomic destination writes and acknowledgment. Artifact bytes never travel as base64 stdout. `delegate-to-codex` publishes only `response.md`, `changes.patch`, and `status.json`; its Codex JSONL and stderr stay on the Mac.

## Retention

Low disk space pauses claims and spawn. GC preserves active jobs, unknown execution, and unacknowledged results. Acknowledged results have a default retention of seven days. `rexec gc` previews eligible cleanup; `rexec gc --apply` applies it. Cleanup does not cancel work or scan unrelated home files.
