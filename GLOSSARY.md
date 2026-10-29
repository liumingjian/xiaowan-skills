# Xiaowan Skills

Agent skills for the maintainer's own machines and the company intranet they reach.

## Machines

**vps-cc**:
The memory-constrained server where the agent runs and submits work from.
_Avoid_: 本主机, the server, the host

**Paired Mac**:
The Mac mini that runs rexec jobs and holds the company intranet credentials, so it is the only machine that can reach intranet servers.
_Avoid_: macOS, jump host, 跳板机

**Windows VM**:
The `Windows 11 ARM64` guest that UTM runs on the paired Mac. It is where Windows compatibility is verified, and it keeps no project state between jobs.
_Avoid_: Windows 虚拟机, Windows box, the guest

**Background run**:
A Windows VM job whose programs run out of sight of the logged-in desktop, including headless browsers. The default.
_Avoid_: 无头档, SSH mode

**Desktop run**:
A Windows VM job whose programs open on the logged-in user's desktop, visible in the UTM window. Used only when the test needs the real desktop.
_Avoid_: 桌面档, GUI mode, interactive mode

**Intranet server**:
A company server in `192.168.0.0/16`, reachable only through the company SOCKS5 proxy.
_Avoid_: 内网机器, remote host, target

## Intranet access

**Intranet operation**:
One remote command or one single-file transfer against an intranet server; each runs over a fresh connection with no shell state carried between operations.
_Avoid_: session, login
