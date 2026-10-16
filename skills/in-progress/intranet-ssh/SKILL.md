---
name: intranet-ssh
description: Log in, execute commands, and upload or download files on company intranet servers through the saved SOCKS5 proxy.
---

# Intranet SSH

Use the bundled `scripts/intranet` executable for root SSH access to `192.168.0.0/16`. Resolve its path relative to this skill directory. Run it directly with macOS Ruby, OpenSSH, and the installed `sshpass`. Transfers use the macOS OpenSSH 10.3 `scp` default SFTP protocol.

## Complete the requested operation

1. Extract the target IP and the requested operation. For a command, obtain the shell command. For a transfer, obtain the source and destination paths. Ask for any missing value before connecting.
2. Run the matching form below. Quote local shell arguments. Pass a remote command as one argument for the remote shell to interpret.

   ```sh
   "<skill-dir>/scripts/intranet" 192.168.1.116
   "<skill-dir>/scripts/intranet" exec 192.168.1.116 'id -un'
   "<skill-dir>/scripts/intranet" upload 192.168.1.116 './report.txt' '/tmp/report.txt'
   "<skill-dir>/scripts/intranet" download 192.168.1.116 '/tmp/report.txt' './report.txt'
   ```

3. For login, use a persistent terminal session with a PTY. For command execution, preserve stdin, stdout, stderr, and exit status. If a command is still running, retain the session and wait on it rather than submitting it again.
4. Verify the requested result. For a command, inspect its output and exit status. For a transfer, check the destination file and compare size or checksum when correctness matters. Report the target, completed action, and any failure. If a mutation loses its connection, inspect its effects before retrying.

## Connection and files

The existing private `~/.config/company-intranet/config.json` supplies proxy and root credentials. Keep credentials in that file. If it is missing or rejected, report the error and stop before changing connection settings. Installing this skill does not provision credentials.

The tool records new host keys in private `known_hosts` beside the configuration. If a host key changes, stop and report the mismatch for investigation.

Transfers copy one file at a time. Supply an absolute remote path. An existing destination directory receives the source basename. An existing destination file may be overwritten, and an interrupted transfer may leave a partial file. Use the requested paths literally. If SFTP is unavailable, report the transfer error.
