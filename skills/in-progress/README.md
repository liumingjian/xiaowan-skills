# In Progress

Public beta skills. They are installable through the Skills CLI, but their behavior and interfaces may change before graduation to a stable bucket.

Install the whole catalog:

```bash
npx skills@latest add liumingjian/xiaowan-skills
```

Install one beta skill directly:

```bash
npx skills@latest add liumingjian/xiaowan-skills --skill <name>
```

- **[accept-milestone](./accept-milestone/SKILL.md)** - Run a clean-room, end-to-end acceptance pass and produce a plain-language verdict. Model-invoked.
- **[delegate-to-cc](./delegate-to-cc/SKILL.md)** - Send a Git or non-Git project snapshot to Claude Code on `vps-2g` for a second opinion or patch. User-invoked.
- **[delegate-to-codex](./delegate-to-codex/SKILL.md)** - Send the current project through rexec to Codex on the paired Mac mini for a second opinion or patch. User-invoked.
- **[intranet-rexec](./intranet-rexec/SKILL.md)** - Run commands and transfer files on company intranet servers from `vps-cc` through rexec and the paired Mac mini. User-invoked.
- **[intranet-ssh](./intranet-ssh/SKILL.md)** - Log in, run commands, and transfer files on company intranet servers through the saved SOCKS5 proxy. User-invoked.
- **[readme-designer](./readme-designer/SKILL.md)** - Review or rewrite a repository README around real facts, navigation, and a verifiable first run. Model-invoked.
