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
- **[delegate-to-codex](./delegate-to-codex/SKILL.md)** - Send the current project to the Codex CLI on the user's Mac for a second opinion or patch. User-invoked.
- **[readme-designer](./readme-designer/SKILL.md)** - Review or rewrite a repository README around real facts, navigation, and a verifiable first run. Model-invoked.
