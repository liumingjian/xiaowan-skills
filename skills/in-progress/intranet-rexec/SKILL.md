---
name: intranet-rexec
description: Run commands and transfer files on company intranet servers from vps-cc, through rexec and the paired Mac's intranet-ssh.
disable-model-invocation: true
---

# Intranet via rexec

Only the paired Mac reaches the intranet, so every intranet operation runs as one rexec job that calls the Mac's installed intranet-ssh:

```text
~/.agents/skills/intranet-ssh/scripts/intranet
```

Follow the [rexec skill](../../engineering/rexec/SKILL.md) for channel checks, waiting, and recovery, and [intranet-ssh](../intranet-ssh/SKILL.md) for the tool's own rules: one file per transfer, absolute remote paths, credentials and host keys on the Mac. Each operation opens a fresh root connection; `cd`, variables, and other shell state end with it. There is no interactive login.

## Complete the requested operation

1. Extract the target IP and the operation: a command, an upload (local source, absolute remote destination), or a download (absolute remote source, local destination). Ask for any missing value before submitting. When the user asks to log in to a server, make it the target for the following requests and confirm reach with the probe `id -un; hostname; uptime`.
2. Submit the matching form below from `vps-cc`, in the foreground with `--timeout 300`. For a command or transfer that may outlast that, submit with `--background` and a fitting `--timeout`, then wait as the rexec skill describes.
3. Read the receipt. The command's own exit status passes through; intranet-ssh errors arrive on stderr. A changed host key or rejected credentials end the work: report them. Outcome `unknown` means a mutation may have partly run: inspect the server with a read-only command before any resubmission.
4. Verify the result (output and exit status, or the destination file's size or checksum) and report the target, the completed operation, and any failure.

### Command

```bash
rexec --no-sync --label 'intranet exec' --timeout 300 \
  '~/.agents/skills/intranet-ssh/scripts/intranet exec 192.168.1.116 "df -h /"'
```

Single-quote the rexec payload and double-quote the remote command inside it. When the remote command carries its own quotes or spans lines, write it to `cmd.sh` in a new temporary directory and feed it on stdin, so no quoting is nested:

```bash
rexec --sync /tmp/intranet-cmd.XXXX --label 'intranet exec' --timeout 300 \
  '~/.agents/skills/intranet-ssh/scripts/intranet exec 192.168.1.116 "sh -s" < cmd.sh'
```

### Upload

Sync the directory holding the file and name it relative to that directory:

```bash
rexec --sync ./dist --label 'intranet upload' --timeout 300 \
  '~/.agents/skills/intranet-ssh/scripts/intranet upload 192.168.1.116 ./app.tar.gz /tmp/app.tar.gz'
```

Inside a Git repository rexec syncs only tracked files. When the file is untracked or ignored, copy it alone into a new temporary directory and sync that.

### Download

Download into the job's `$TMPDIR`, pack it as `download.tgz`, then collect and unpack it on `vps-cc`:

```bash
rexec --no-sync --label 'intranet download' --timeout 300 \
  'cd "$TMPDIR" && ~/.agents/skills/intranet-ssh/scripts/intranet download 192.168.1.116 /var/log/app.log ./app.log && tar czf "$REXEC_ARTIFACTS/download.tgz" app.log'
rexec artifacts JOB --into /tmp/intranet-dl.XXXX
tar xzf /tmp/intranet-dl.XXXX/download.tgz -C ./logs
```

The archive must expand to at most 64 MiB. rexec refuses archives holding secret-looking names (`.env*`, `*.key`, `credentials`) or the Mac's home path and lists them in `artifacts_refused`; report a refusal as the result. GNU tar notes that it ignores the Mac's `LIBARCHIVE.xattr` headers while unpacking; the files are intact.

## Limits

rexec redacts intranet addresses in output, so `192.168.x.x` reads `[private]` in stdout, logs, and command results. Name the target from the request when reporting. The Mac's OpenSSH warns on stderr about a missing post-quantum key exchange; that warning is informational.

The Mac runs its own checkout of intranet-ssh. When the tool behaves unlike its `SKILL.md`, report that the Mac's `~/repos/xiaowan-skills` may need a `git pull`.
