# Delegate to Codex contract

`delegate-to-codex` sends a project snapshot from `vps-cc` to the Codex CLI on the paired Mac mini through `rexec`. It creates no independent transport and exposes no machine-selection controls. `rexec` owns durable submission, source freezing, queueing, cancellation, execution deadlines, recovery, privacy export, and artifact acknowledgments.

The skill is user-invoked because it spends Codex quota and can edit the Mac workspace. `consult` uses a read-only sandbox and returns an empty patch. `implement` uses a workspace-write sandbox and returns edits against a disposable baseline. Real history is transferred only with `--with-git`. Keep model, reasoning effort, explicit thread resume, and finite timeout options.

The caller writes a handoff inside the source project and outside fixed snapshot exclusions. The wrapper embeds its runner with safely quoted arguments, submits `rexec --background --timeout SECONDS`, parses the acceptance JSON's opaque `job_id`, waits for the result, and fetches validated artifacts with `rexec artifacts JOB --into DIR`. Interrupted waits leave the durable job running and report its job ID for recovery. Unknown execution never triggers an automatic second submission.

The runner writes `response.md`, `changes.patch`, and `status.json` containing numeric `status` and opaque `thread_id` under `$REXEC_ARTIFACTS`. Codex JSONL and stderr remain private files in the Mac job's scratch directory. Artifact transfer uses dedicated manifests and validated text files, never a stdout tarball. Privacy filtering can refuse a patch; the wrapper reports that failure without retrieving raw logs or another unfiltered copy.

The parent reads the response, validates and reviews every patch hunk, obtains acceptance before applying changes, and reruns relevant checks on the accepted result. A delegated test claim is not independent acceptance evidence. The subagent returns a bounded receipt with verdict, findings, artifact paths, job ID, and thread ID; it never applies a patch.

Service/setup tooling is provided separately by `rexec`. Updating this repository installs no service, deploys nothing, and executes no Codex session.
