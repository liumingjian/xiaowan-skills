---
name: windows-rexec
description: Verify and adapt the current project on Windows from vps-cc, through rexec and the paired Mac's Windows VM.
disable-model-invocation: true
---

# Windows via rexec

Only the paired Mac reaches the Windows VM (`Windows 11 ARM64` in UTM), so each Windows job is one rexec job that runs the Mac's installed helper:

```text
~/.agents/skills/windows-rexec/scripts/winvm
```

`winvm` starts the VM when it is stopped, copies the synced project into a fresh job directory, runs a PowerShell 7 script there, returns `result.tgz`, and deletes the job directory. The VM keeps no project state: edit code on `vps-cc`, then submit it again. Follow the [rexec skill](../../engineering/rexec/SKILL.md) for channel checks, waiting, and recovery.

## Adapt the project

1. Pick the run. A **background run** (`winvm exec`) suits builds, tests, CLI checks, and headless browsers; it is the default. A **desktop run** (`winvm desktop`) opens programs on the logged-in Windows desktop, visible in the UTM window. Use it only when the test needs the real desktop: headed browser rendering, system dialogs, or the user watching.
2. Write the script in PowerShell 7. It starts in the copied project with `$env:WINVM_OUT` pointing at an empty directory. Write screenshots, Playwright traces and reports, and logs there; they return as `result.tgz`, capped at 64 MiB, so keep the reports and failure screenshots. The script stops at its first failing command, cmdlet or native, and that exit status becomes the job's. Install project dependencies inside the script (`npm ci`, `pip install`): rexec leaves dependency caches out of the sync.
3. Submit from the project root. The command line below suits a one-line script. Put a longer script in `.winvm-run.ps1` at the project root (rexec syncs untracked files) and feed it on stdin, then delete the file after the job.

   ```bash
   rexec --background --timeout 1800 --label 'windows tests' \
     '~/.agents/skills/windows-rexec/scripts/winvm exec "npm ci; npx playwright test"'
   rexec --background --timeout 1800 --label 'windows tests' \
     '~/.agents/skills/windows-rexec/scripts/winvm exec - < .winvm-run.ps1'
   rexec --background --timeout 1800 --label 'windows desktop' \
     '~/.agents/skills/windows-rexec/scripts/winvm desktop --timeout 1500 - < .winvm-run.ps1'
   ```

   Single-quote the rexec payload and double-quote the script inside it; the Mac shell expands `$` there, so a script that uses `$` goes through `.winvm-run.ps1`. Allow about three minutes for boot and transfer: a desktop run's own `--timeout` (default 1500 seconds) stays that far below rexec's. Submit Windows jobs one at a time and wait for each result, since every job clears the VM's job directory first.
4. Read the receipt. The script's exit status passes through, and a background run streams its output. A desktop run prints its console log when it ends, and exit 124 means it passed its own timeout and the task was ended. `winvm` exits 69 when the VM, SSH, or the desktop is unavailable, and 77 when the VM rejects the key or its host key changed: report both to the user and stop.
5. Collect `result.tgz` with `rexec artifacts JOB --into /tmp/winvm-result.XXXX` and unpack it there. Fix the project on `vps-cc`, then submit again until the Windows run passes.
6. Report what ran, the result, and any tool you installed, and say it was verified on Windows 11 ARM64. x64 binaries run there under emulation, so the run does not vouch for native x64 behaviour.

## The Windows VM

Git, Node LTS, Python 3, PowerShell 7, Edge, and Playwright Chromium come preinstalled. Install a missing tool in the script with `winget install --id ID -e --silent --accept-package-agreements --accept-source-agreements`, then refresh `$env:Path` from the registry, and name it in the report. The SSH account is a local administrator. When the Mac's proxy answers on port 7897 of the UTM gateway, each job gets `HTTP_PROXY` and `HTTPS_PROXY` pointing at it, with `localhost` exempt; pass `--proxy $env:HTTPS_PROXY` to `winget`, which ignores those variables.

Files arrive byte for byte, so line endings stay LF: unlike a Windows `git clone` with `core.autocrlf=true`. Convert files in the script when the test concerns CRLF. Run the whole stack in the VM and point the browser at `localhost`. GUI automation of native desktop apps is out of scope; build, launch, and command-line tests are in.

A desktop run needs the account signed in and the screen unlocked. When `winvm` reports that the desktop is unavailable, ask the user to sign in to Windows in UTM.

## Setup

Run `winvm init` on the Mac through rexec (`rexec --no-sync --timeout 300 '~/.agents/skills/windows-rexec/scripts/winvm init'`). The first run creates the Mac key and pushes `setup.ps1` into the VM, then prints one line for the user to run in an administrator PowerShell in Windows. A second run, after the user has run that line, adds `Host windows-vm` to the Mac's `~/.ssh/config` and checks the connection; from then on `init` only checks the connection. The UTM guest agent that carries the setup files sometimes stops answering (`Timed out waiting for RPC`) for minutes: wait and retry. Desktop runs also need automatic sign-in for that account, which the user turns on in Windows.

When `winvm` is missing or behaves unlike this file, report that the Mac's `~/repos/xiaowan-skills` needs a `git pull` and `scripts/link-skills.sh`.
