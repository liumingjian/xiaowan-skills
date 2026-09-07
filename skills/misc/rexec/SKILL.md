---
name: rexec
description: Dispatch work that has to actually run — and that eats memory or time — to the user's mac, bypassing this memory-starved server. Covers compiling and building, installing dependencies, creating virtualenvs, running test suites, starting services for end-to-end checks, and docker containers or image builds. Also takes `/rexec queue` to see the queue, `/rexec cancel <ID>` to cancel a job, and `/rexec macs` to see which macs are online.
---

# rexec

This server is memory-starved; tests and builds routinely fail on it. `rexec` **dispatches** that work to
the user's mac (8 cores / 16GB): the server writes a job into a queue, a resident agent on the mac polls
for it, rsyncs the code over, runs it locally, and ships back the output and exit code.
Pull-based rather than reverse SSH because the user's home connection sits behind NAT — the server
cannot reach the mac.

The environment is fixed: SSH alias `vps-2g` (defined in the mac's `~/.ssh/config`, key
`~/.ssh/my-vps_ed25519`; override with `REXEC_HOST`); mac workspace
`~/rexec-workspace/<project>-<pathhash>/`.

**Multiple macs are first-class.** Each mac's agent has its own identity and its own queue on the server.
**A job goes to the mac this session ssh'd in from**, matched on source IP — a different mac having an agent
up is never a substitute, and rexec asks you to start the agent on the right one instead of quietly using it.
**Jobs from different projects run in parallel; jobs from the same project run serially** (they share one
workspace), counted per mac.
The caller blocks until the result arrives, and gets a bill of queue time and run time at the end.

## Sub-commands

When the user types `/rexec queue` or `/rexec cancel ...`, run the matching command and hand them the
output — do not dispatch a job:

```bash
rexec --queue          # every mac's queue: what's running, what's waiting, what blocks it, and this session's default target
rexec --cancel <ID>    # cancel one job (IDs look like myproj-0041; globally unique, found across all macs)
rexec --cancel         # no ID: list the queue first, let the user pick
rexec --macs           # which macs are registered, who is online, this session's default target
```

Cancelling kills only that job's process group; other running jobs and the agent itself are untouched.

## Step 1: bring the channel online

```bash
bash /home/agent/.claude/skills/rexec/status.sh
```

The first line is the state of **this session's mac**, and the table below it marks that mac with `->`.
`ONLINE` means go to step 2. Handle the other states below, then re-run this command to confirm.

**`NOT_INSTALLED`** — the server side is not deployed. Install it yourself; do not bother the user:

```bash
bash /home/agent/.claude/skills/rexec/install.sh
```

Then handle it as `OFFLINE`.

**`OFFLINE`** — no agent is running on this session's mac. Some *other* mac may well show `ONLINE` in the
table; it is a different machine, so it is not the target — do not reach for `--mac` to route around this.
Hand the user this command verbatim, ask them to run it **in a terminal on the mac they are ssh'd in from**,
then **stop and wait for their reply** before continuing:

```bash
ssh vps-2g 'cat /var/lib/rexec/agent.sh' > ~/rexec-agent.sh && bash ~/rexec-agent.sh
```

That one command installs and starts the agent, pulling the latest version each time. Tell the user two
things: the agent occupies a terminal tab for as long as it runs, and it is only up once
`polling every 2s, ctrl-c to stop` appears; Ctrl-C stops it. Its first line prints its identity, e.g.
`rexec-agent  macbook-pro-3f9a  ->  vps-2g  ~/rexec-workspace`.

**`AMBIGUOUS`** — two or more macs announced from this session's source IP (both behind one home NAT), so the
IP no longer picks one out. Show the user the table, ask which mac this session is on, then pass
`--mac <name>` on **every** rexec call for the rest of the session — the flag does not persist between calls.

**The agent is single-instance, per mac.** Starting a second one is blocked, and the existing pid is
printed. This is deliberate: two agents fight over the queue, each claiming half the jobs, which is
brutal to diagnose. To restart, Ctrl-C the original terminal first.

**Completion criterion: `status.sh` prints `ONLINE`, or `AMBIGUOUS` with a mac the user named.** Re-run it
once the user replies, and only enter step 2 once you have seen it.

## Step 2: dispatch the verification work

**Exit codes pass through verbatim, so judging pass/fail needs no full output.**
What comes back from rexec should be a **receipt** — the minimum evidence needed to judge pass/fail,
not a log. The full log stays on the mac; go get it separately if you actually need it.

**Completion criterion: every rexec call narrows its output, and every receipt fits in a few dozen lines.**

```bash
rexec 'set -o pipefail; pytest -q 2>&1 | tail -30'
rexec 'set -o pipefail; npm ci --silent && npm test 2>&1 | tail -40'
rexec 'set -o pipefail; cargo test --release 2>&1 | tail -40'
rexec --no-sync 'node -v; python3 -V; docker ps'        # already short, leave it alone
rexec --timeout 1800 'set -o pipefail; cargo build --release 2>&1 | tail -20'
# to do more work after the pipe, save the exit code explicitly with ec=$?
rexec --sync /home/agent/repo/myproj --cwd frontend \
      'npm run build > /tmp/b.log 2>&1; ec=$?; tail -40 /tmp/b.log; exit $ec'
```

**`set -o pipefail` is mandatory.** `| tail` replaces the exit code with `tail`'s, which is always 0, and
exit-code passthrough is what this whole thing rests on — without it, narrowing the output silently
destroys the pass/fail signal, which is worse than not narrowing at all.

**Why narrow:** output above roughly 30KB gets persisted to a file, leaving only a **2KB preview** in
context; output below 30KB lands in context **in full**, so a single 28KB result costs ~7000 tokens.
Test and build output sits right in that band, which makes not narrowing far more expensive than it looks.

**If it overflows anyway and gets persisted:** the preview shows the **start**, while build and test
verdicts live at the **end** — `tail -50 <persisted file path>` rather than reading the whole thing.

Leave the light, static work on the server: reading and writing code, grep, type checking.

## Usage notes

- Syncs the **current working directory** by default (rsync, honours `.gitignore`) to
  `~/rexec-workspace/<dirname>-<pathhash>/` on the mac, then runs there. The path hash gives
  **same-named but different projects** their own directories, so they never `rsync --delete` each other's
  files; one project always reuses one directory, so dependencies still install only once.
- stderr carries one bill line at the end:
  `--- [macbook-pro-3f9a] exit=0 | queued 4m12s | ran 6m03s | total 10m15s ---` (the mac that ran it is in brackets).
- **Dependencies install once.** `.venv/ node_modules/ target/ dist/ build/ .next/` are protected on the
  mac and survive `rsync --delete`. Run
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` once and it holds; after that
  `rexec '.venv/bin/pytest -q'` reuses it and the round trip takes seconds.
- **`.git` is not synced**, so the workspace is not a repo and history-based commands fail there. Pass
  `--with-git` when the command needs real history (`git log`, `git diff main`, a review against a base
  branch); it costs the transfer of the whole history, so leave it off for builds and tests.
- **Files in `.gitignore` are not synced** (`.env`, keys, and so on stay on the server). If a test needs
  them, ask the user to drop a copy into the matching workspace directory on the mac: filtered files are
  protected too, so one drop lasts.
- Syncing is one-way (server → mac). Build artifacts do not come back; `cat` them in the command if needed.
- Commands must run unattended (`vim` and installers that want keystrokes cannot work).
- `--no-sync` and `--light` declare a **light job**, exempt from the mac's load gate — good for zero-cost probing.
- **Interrupt means cancel.** Pressing ESC on a `rexec` call in the session terminates the job on the mac
  too, so nothing is orphaned.

## Troubleshooting

How the target mac is resolved, load gate not releasing, exit code meanings, agent environment variables —
read `REFERENCE.md` in this directory.
