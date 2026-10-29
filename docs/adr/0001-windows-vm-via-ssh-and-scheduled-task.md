# Reach the Windows VM over SSH from rexec jobs, with a scheduled task for desktop runs

Windows compatibility is verified on the Windows VM, which only the paired Mac can reach. Each verification is one rexec job whose Mac-side helper connects to the VM over OpenSSH, copies the snapshot into a per-job directory, runs it, and returns the evidence as `result.tgz`; rexec itself does not learn about the VM. A desktop run cannot start from SSH, because SSH sessions never reach the logged-in desktop, so SSH triggers one pre-registered "run only when the user is logged on" scheduled task that runs the job's script on that desktop.

## Considered Options

- **`utmctl exec` through the QEMU guest agent**: needs no network setup, but returned no output when probed and runs as SYSTEM, so it cannot reach the desktop either.
- **A `--target windows` option in rexec**: would spread one machine's details through the rexec runtime. Following the intranet-rexec precedent, a thin skill keeps rexec unchanged until a third target appears.
- **WinRM / PowerShell Remoting**: no ready client on the Mac, and more setup than OpenSSH for the same reach.
