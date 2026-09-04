# rexec troubleshooting reference

The normal dispatch path never needs this file. Read it when the target mac cannot be resolved, when the
load gate will not release, when you need an exit code's meaning, or when tuning the agent's environment
variables.

## Choosing the target mac

One VPS can have several macs attached. **The mac this session ssh'd in from is the target**; `rexec` only
departs from that when you say so explicitly. Resolution order:

1. `--mac <name or prefix>` (or the `REXEC_MAC` environment variable) — explicit; any unique prefix works,
   e.g. `--mac studio`.
2. **Source-IP claim** — the mac whose agent announced from the same IP this session ssh'd in from, taken
   **whether or not its agent is currently up**. If it is down, that is exit **69** and a prompt to start the
   agent *on that mac*: a different mac being online does not make it the target, and silently borrowing it
   runs the job on a machine that has neither the user's attention nor the files they expect.
3. Source IP **unknown** (not an ssh session at all — cron, tty1) and exactly one mac online — use it.
4. Otherwise exit **3** and list the candidates: several macs share one source IP (two machines behind one
   home NAT), or there is no source IP and several macs are online. Re-run with `--mac`; do not guess.

`origin` is rewritten on every agent poll, so a mac that changes network or Wi-Fi re-routes itself within
one poll. A mac the user has never started the agent on has no `origin` at all, which lands on the exit-69
branch: start the agent there once and it registers.

The agent derives its own identity name: `<first 12 chars of ComputerName>-<hardware UUID hash4>`, e.g.
`macbook-pro-3f9a`. The hash suffix keeps two identically named machines from colliding. To rename, use
`REXEC_MAC=custom-name bash ~/rexec-agent.sh`.

Each mac has its own queue, gate, and workspace, fully independent — including the same-project-serial
rule, which is counted per mac: two commands from one project can run on macA and macB simultaneously,
because each has its own workspace directory.

## Syncing `.git`

The sync excludes `.git` by default: history is dead weight for a build, and on a long-lived repo it is the
single largest thing in the tree. `--with-git` includes it.

Two consequences worth knowing:

- rsync leaves excluded paths on the receiver untouched, so a `.git` created **inside** the workspace (a
  disposable baseline, say) survives every default sync — and is overwritten by the server's history the
  first time `--with-git` runs.
- The agent advertises its capabilities at announce time (`macs/<id>/caps`). An agent that predates
  `--with-git` ignores the flag rather than failing, which would sync without history while the caller
  believes otherwise, so `rexec` refuses the job up front with **exit 2** and asks for an agent restart on
  that mac. Restarting the agent re-announces and clears it.

## Parallelism and queueing

- **Parallel across projects, serial within a project.** Two commands from one project share a workspace
  directory, and running them together would shred each other's files.
- **Strict first-come, first-served.** If the head of the queue cannot run (waiting on an earlier job from
  the same project), everything behind it waits too, even when it could run. Execution order is therefore
  fully predictable, and `--queue` states what each job is blocked by.
- **Load gate, three bands.** The agent samples the mac's CPU and memory pressure every few seconds and
  decides whether to accept another **heavy** job:
  - CPU below `REXEC_CPU_RELAX` (default 40%) — take it immediately, no cooldown. This is the normal path
    for cross-project parallelism.
  - 40% to 80% — take at most one job per `REXEC_COOLDOWN` (default 15s), damping the overshoot that comes
    from CPU readings lagging reality.
  - Above `REXEC_CPU_MAX` (default 80%), or free memory below 20% — close the gate and leave the machine to
    whatever the user is doing; it reopens on its own once things settle.
  - Two exemptions: **light jobs** (`--no-sync` / `--light`) ignore the gate entirely, and when nothing at
    all is running one job is claimed regardless of the gate (otherwise a persistently busy mac would stall
    the queue forever).
- Queue time does **not** count against `--timeout`, which measures run time only, so yielding for a long
  while never causes a false timeout.

## Blast radius of a cancel

`--cancel` kills **only that job's process group**. Other running jobs and the agent itself are untouched.
A job still waiting in the queue is simply removed without touching the mac at all. Cancelled jobs exit
with **125**. IDs are globally unique and searched across every mac, so you never need to know which mac a
job is on.

## Exit codes

- `3` — several macs share this session's source IP, or there is no source IP and several are online.
  Re-run with `--mac`.
- `69` — the agent on **this session's mac** is offline, or has never been started there. Go back to the
  `OFFLINE` branch of step 1 in SKILL.md to walk the user through starting it, then re-run the command.
  Not a cue to retarget another mac with `--mac`.
- `90` — rsync failed. `91` — target directory does not exist.
- `124` — run timed out (exceeded `--timeout`; queue time excluded).
- `125` — job cancelled (`--cancel`, or the caller pressed ESC).
- `130` — the agent on the mac was stopped with Ctrl-C, taking the job with it.
- anything else — the real exit code of the command itself on the mac.

On failure `rexec` writes the reason and the next step to stderr itself; this table is only a quick lookup.

## Agent environment variables (rarely worth changing)

| Variable | Purpose | Default |
|---|---|---|
| `REXEC_MAC` | this machine's identity name | derived automatically |
| `REXEC_HOST` | ssh target | `vps-2g` |
| `REXEC_WS` | workspace | `~/rexec-workspace` |
| `REXEC_POLL` | poll interval | 2s |
| `REXEC_CPU_MAX` | CPU ceiling % that closes the gate | 80 |
| `REXEC_CPU_RELAX` | CPU floor % below which cooldown is ignored | 40 |
| `REXEC_MEM_MIN` | free memory floor % | 20 |
| `REXEC_COOLDOWN` | claim cooldown, seconds | 15 |
| `REXEC_LOG` | write the agent log to this file | no log file |

To get the agent log on disk use `REXEC_LOG`, not a shell `>` redirect — bash's block buffering holds log
lines in the buffer instead of writing them out.
