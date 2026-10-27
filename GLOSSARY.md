# Xiaowan Skills

Agent skills for the maintainer's own machines and the company intranet they reach.

## Machines

**vps-cc**:
The memory-constrained server where the agent runs and submits work from.
_Avoid_: 本主机, the server, the host

**Paired Mac**:
The Mac mini that runs rexec jobs and holds the company intranet credentials, so it is the only machine that can reach intranet servers.
_Avoid_: macOS, jump host, 跳板机

**Intranet server**:
A company server in `192.168.0.0/16`, reachable only through the company SOCKS5 proxy.
_Avoid_: 内网机器, remote host, target

## Intranet access

**Intranet operation**:
One remote command or one single-file transfer against an intranet server; each runs over a fresh connection with no shell state carried between operations.
_Avoid_: session, login
