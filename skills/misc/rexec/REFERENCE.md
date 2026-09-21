# rexec troubleshooting reference

The normal dispatch path never needs this file. Read it when the target mac cannot be resolved, when the
load gate will not release, when you need an exit code's meaning, or when tuning the agent's environment
variables.

## Choosing the target mac

One VPS can have several macs attached. Machines are told apart by **ssh key, never by IP**: home IPs
rotate, and a proxy can give one mac several addresses at once. Each mac logs in with its own key
(`~/.ssh/vps-2g-rexec`), whose line in the server's `~agent/.ssh/authorized_keys` ends with the comment
`rexec-mac=<MACID>`. sshd runs with `ExposeAuthInfo yes` (`/etc/ssh/sshd_config.d/50-rexec.conf`), so each
login gets `$SSH_USER_AUTH`, a file naming the key it used, which sshd deletes when the login ends.

Resolution order:

1. `--mac <name or prefix>` (or the `REXEC_MAC` environment variable) — explicit; any unique prefix works,
   e.g. `--mac studio`.
2. **Login key** — the mac whose key this session's live ssh login used, taken **whether or not its agent is
   currently up**. If it is down, that is exit **69** and a prompt to start the agent *on that mac*: a
   different mac being online does not make it the target, and silently borrowing it runs the job on a
   machine that has neither the user's attention nor the files they expect.
3. **Exactly one mac online** — use it. An agent only runs where the user started it.
4. **Several online** — the default set with `rexec --use <name>` (stored in `/var/lib/rexec/default`), if
   it is one of them.
5. Otherwise exit **3** and list the candidates. Set a default or re-run with `--mac`; do not guess.

Step 2 only trusts a **live** login. A long-lived process such as a Claude daemon keeps the
`SSH_USER_AUTH` of the login that started it, but sshd deleted that file when the login ended, so its
background jobs skip step 2 instead of inheriting a stale mac.

The agent's own logins are checked as well: `rexec-announce` and `rexec-claim` refuse a MACID other than the
one the login key is tagged with. An untagged key (the old shared key) is let through.

**Adding a mac.** On the mac, generate its own key, tagged with the identity the agent prints on its first
line, and point the `vps-2g` alias at it:

```bash
ssh-keygen -t ed25519 -N "" -C rexec-mac=<MACID> -f ~/.ssh/vps-2g-rexec
```

Then append `~/.ssh/vps-2g-rexec.pub` to the server's `~agent/.ssh/authorized_keys`, set
`IdentityFile ~/.ssh/vps-2g-rexec` under `Host vps-2g` in the mac's `~/.ssh/config`, and restart the agent.

The `origin` file under each mac is only the last IP it called from, shown in `rexec --macs`; routing never
reads it.

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

## Detached jobs

`--detach` runs a job on the mac and returns as soon as it is launched. It exists because the alternative
for a long build — a bigger `--timeout` — makes the job's survival depend on the caller's, and a session
that is compacted or killed takes a two-hour build with it.

What it escapes, and how:

- **`perl setpgrp` puts it in a process group of its own.** Every implicit kill in rexec is aimed at a
  process group: cancel, timeout, and the sweep a new agent does over its predecessor's leftovers. None of
  them can name this one. `nohup` on top of that makes closing the agent's terminal harmless.
- **It reports its own result.** When the command exits, the detached process ssh's back to the server
  itself, over its own connection rather than the agent's multiplexed one, and records the exit code and
  log tail under `macs/<id>/detached/<ID>`. A detached job therefore finishes correctly on a mac whose
  agent stopped hours ago. The agent is only the backstop, for a process killed before it could report.
- **`--cancel` still reaches it**, because the agent records its process group id. Surviving every
  *implicit* death is the goal; being unkillable is not.

What it does not escape:

- **The project's workspace slot.** A detached job left `running/` the moment it was launched, but it is
  still building in that directory, so the scheduler keeps it counted: a later job from the same project
  waits, exactly as it would for a foreground one. Other projects are unaffected. It also counts toward
  the "nothing is running, let one job through regardless" escape hatch in the load gate, so three
  detached builds cannot make the mac look idle.
- **A mac reboot.** Process group ids mean nothing across a boot, so the record carries the boot time too.

Collecting it:

- `rexec --wait <ID>` blocks until it finishes, then prints the same receipt a foreground job would have:
  log tail, bill line, exit code. Waiting twice is fine, and a job that finished before anyone waited is
  collected just the same — its record is kept for a week.
- `rexec --tail <ID> [-n N]` reads a snapshot of the log that the agent pushes to the server every
  `REXEC_TAIL` seconds (default 15). It never touches the mac, so it is free, and at most that stale. The
  full log lives on the mac at `~/.rexec/detached/<ID>.log` for a week.
- **When the agent is offline, nothing judges a detached job.** The process reports itself; the agent is
  what notices when it never got the chance. With the agent down, `--wait` says so on stderr and keeps
  waiting rather than declaring a job dead because the user closed a terminal. Once the agent is back, a
  process group that is gone is reported as **exit 129** on its first poll.
- Like `--with-git`, an agent that predates `--detach` makes `rexec` refuse the job with **exit 2** and ask
  for a restart on that mac. Running it as a normal job instead would give the caller a receipt for
  something it believes is detached, which would then die at the 900s timeout.

## Parallelism and queueing

- **Parallel across projects, serial within a project.** Two commands from one project share a workspace
  directory, and running them together would shred each other's files.
- **First-come, first-served, but a blocked job is stepped over.** Each poll claims the earliest job that
  can actually run. Only same-project jobs queue behind each other; work from other projects flows past.
  Execution order is therefore no longer globally predictable — project B can overtake project A — which is
  the price of the property that matters more: one long build can no longer stop the whole mac. It used to.
  `--queue` states what each job is blocked by.
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
    the queue forever). Detached jobs count as running for that second exemption.
- Queue time does **not** count against `--timeout`, which measures run time only, so yielding for a long
  while never causes a false timeout.

## When the caller dies without saying so

The mirror image of the section below, and the other half of a queue that stops moving. Pressing ESC is a
clean stop: `rexec` traps it and cancels the job properly. A session that is killed outright is not — it is
compacted away, OOM-killed on a small VPS, or loses its ssh link — and it leaves behind a job that nobody
will ever collect.

Every `rexec` client therefore writes the current time into `macs/<id>/alive/<ID>`, once before it submits
and again on every second of its wait loop. `rexec-claim` reads it on each poll:

- a **queued** job whose heartbeat stopped more than `REXEC_CALLER_GRACE` (default 90s) ago is dropped;
- a **running** one gets a cancel marker, and the agent terminates it like any other cancel.

This closes the gap that made a restart useless. Nothing else expires a *queued* job — `rexec-announce`
only ever reaped running ones — so an abandoned job kept its place in the queue across every agent restart,
and while it sat there its project-mates sat behind it. Restarting the agent was the one action that could
not fix it, which is exactly the action a stuck queue invites.

A job carrying **no** heartbeat file at all is left alone: it came from a client that predates this, and
grandfathering costs one stale job that finishes by itself, where the opposite default would reap every
in-flight job the moment the server is upgraded.

## When the agent dies without saying so

Ctrl-C is a clean stop: the agent kills every job it is running and reports each one, so no caller is left
waiting. `kill -9`, a closed terminal, a lost ssh session or a sleeping mac are not, and they used to leave
two kinds of wreckage that **restarting the agent did not clear** — which is a trap, because restarting is
the one thing a user reaches for when the queue stops moving:

- **On the mac**, the job's process group kept running. A build can burn cores for days, and the load gate
  reads that CPU and refuses to claim anything new.
- **On the server**, the job stayed listed as running, so every later job from the same project queued
  behind a job that had already died, and nothing ever timed it out: `--timeout` is enforced by the agent,
  and that agent is gone.

Three mechanisms now clear it, and none of them needs the user to do anything beyond restarting the agent:

1. **The agent, at startup**, kills the process groups its predecessor left behind, before wiping the job
   records that name them. Process group IDs mean nothing across a reboot, so they are only killed when the
   boot time recorded with them still matches — after a reboot the processes are gone anyway.
2. **`rexec-announce`, at startup**, finishes every job the server still has marked running for that mac. A
   freshly started agent runs nothing by definition, so all of them are stale.
3. **`rexec-claim`, on every poll**, compares the running list the agent reports with the server's own. A job
   only the server still holds is stranded and gets finished, after a grace period (`REXEC_STRAND_GRACE`,
   default 120s) that covers the gap between claiming a job and the agent's next poll. This catches an agent
   that is alive but lost track of a job, and needs no restart at all. The agent keeps a finished job on
   that list until its result has actually reached the server, retrying the report on every poll (the
   terminal shows `WARN ... retrying every poll`). Otherwise one report lost to a flaky link turned a job
   that finished fine into a 129. Detached jobs get the same grace, because the first poll after a launch
   can go out before the launch is registered.
4. **`rexec-claim`, by age**, is what reaches a mac whose agent predates mechanism 3 and therefore sends no
   list. With nothing to compare against it goes by age alone: the agent is what enforces `--timeout`, so an
   entry outliving its own timeout by a wide margin (`REXEC_STRAND_SLACK`, default 300s) proves no agent is
   there to enforce anything. A job the agent does report as running is never reaped by age, however long it
   has been going.

Stranded jobs finish with **exit 129** and an explanation in their output, so whoever was blocked on them is
released instead of waiting forever. An agent older than this reports no running list, which limits it to
mechanism 4 until it restarts.

## Blast radius of a cancel

`--cancel` kills **only that job's process group**. Other running jobs and the agent itself are untouched.
A job still waiting in the queue is simply removed without touching the mac at all. Cancelled jobs exit
with **125**. IDs are globally unique and searched across every mac, so you never need to know which mac a
job is on.

## Exit codes

- `3` — several macs are online, and neither a live login nor the `rexec --use` default picks one; or a
  `--mac` name matches no mac or several. Set a default or re-run with `--mac`.
- `69` — the agent on **this session's mac** is offline or has never been started there, or no agent is
  online at all. Go back to the `OFFLINE` branch of step 1 in SKILL.md to walk the user through starting
  it, then re-run the command. Not a cue to retarget another mac with `--mac`.
- `90` — rsync failed. `91` — target directory does not exist.
- `124` — run timed out (exceeded `--timeout`; queue time excluded).
- `125` — job cancelled (`--cancel`, or the caller pressed ESC). For a detached job `--cancel` is the only
  thing that produces it.
- `129` — the job was stranded: the agent that was running it died without reporting (kill -9, closed
  terminal, mac asleep), so the server finished it on the agent's behalf. For a detached job it means the
  process group is gone without a result — killed from outside, or the mac rebooted. Re-run the command.
- `130` — the agent on the mac was stopped with Ctrl-C, taking the job with it.
- `70` — no such job on any mac: it vanished from the queue without producing a result (someone cleaned
  the state tree by hand), or a `--wait` / `--tail` names an ID that never existed or has aged out of the
  week-long detached history. Re-run the command.
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
| `REXEC_TAIL` | how often a detached job's log tail is pushed to the server, seconds | 15 |
| `REXEC_LOG` | write the agent log to this file | no log file |

Server side: `REXEC_CALLER_GRACE` (default 90s) is how long a job may go without a caller heartbeat before
the server treats it as abandoned, `REXEC_STRAND_GRACE` (default 120s) is how long a job may be missing from the agent's reported
running list before the server treats it as stranded, `REXEC_STRAND_SLACK` (default 300s) is how far past its
own `--timeout` a job may sit in the running list before the same happens, and `REXEC_ROOT` relocates the
state tree (tests only).

The agent sends everything through one multiplexed ssh connection (ControlMaster) and rebuilds it on
the next poll whenever it is gone. sshd drops it when the home link stalls (`Timeout, client not
responding` in the server's auth log). The agent used to build it only once, at startup, so after the
first stall every poll, sync and report opened a fresh login, and those are the connections a flaky link
cuts before the handshake (`Connection closed by <vps> port <port>`, `connection lost, retrying in 5s`).

`tests/queue-test.sh` covers the server side and runs anywhere. `tests/agent-test.sh` runs the real agent
against the real server scripts through a fake `ssh` that can drop reports or kill the master, and needs a
mac: `rexec 'bash skills/misc/rexec/tests/agent-test.sh'`. Neither touches the live queue or agent.

To get the agent log on disk use `REXEC_LOG`, not a shell `>` redirect — bash's block buffering holds log
lines in the buffer instead of writing them out.
