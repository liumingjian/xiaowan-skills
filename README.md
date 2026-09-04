# Xiaowan Skills

Small, composable agent skills for practical engineering work. Each skill is an ordinary directory with a `SKILL.md`, so you can install it into Codex, Claude Code, or another compatible agent without wrapping it in an application package.

## Installation

The canonical installer is the Skills CLI. From the repository root of the project where you want the skills:

```bash
npx skills@latest add liumingjian/xiaowan-skills
```

Install one skill at a time with:

```bash
npx skills@latest add liumingjian/xiaowan-skills --skill delegate-to-cc
```

The installer discovers `SKILL.md` files under `skills/<bucket>/<skill>/`. Use `-g` for a global install or `--list` to inspect the catalog before installing. The repository itself is not an npm runtime package; `npx skills` is the distribution and installation path.

## Skills

These skills are public beta releases. They stay in `skills/in-progress/` until their behavior and interfaces are stable.

- **[accept-milestone](./skills/in-progress/accept-milestone/SKILL.md)** - Run a clean-room, end-to-end acceptance pass and produce a plain-language verdict.
- **[delegate-to-cc](./skills/in-progress/delegate-to-cc/SKILL.md)** - Send a Git or non-Git project snapshot to Claude Code on `vps-2g` for a second opinion or patch.
- **[delegate-to-codex](./skills/in-progress/delegate-to-codex/SKILL.md)** - Send the current project to the Codex CLI on the user's Mac for a second opinion or patch.
- **[readme-designer](./skills/in-progress/readme-designer/SKILL.md)** - Review or rewrite a repository README around real facts, navigation, and a verifiable first run.

`delegate-to-cc` requires the local `ssh`, `scp`, `tar`, and `find` commands plus the `vps-2g` SSH alias. The remote host provides Claude Code and its own disposable Git metadata for patch generation.

`delegate-to-codex` runs the mirror trip and requires the `rexec` skill, which is the only channel from the server to the Mac and also selects the target Mac. The Mac provides the Codex CLI; disposable Git metadata for patch generation is created in the synced workspace.

## Repository layout

```text
skills/
  engineering/       stable engineering skills
  productivity/      stable workflow skills
  misc/              useful skills not promoted to the main catalog
  in-progress/       public beta skills
  deprecated/        retired skills
```

Every skill keeps its supporting scripts, references, and Codex metadata beside `SKILL.md`. Maintainer helpers live under `scripts/`; run `npm run list-skills` to print the installable catalog and `./scripts/link-skills.sh` to link the catalog into local agent directories.

## Contributing

Keep a skill self-contained, give it a discriminating frontmatter description, and put only behavior-changing guidance in `SKILL.md`. Run the repository checks before opening a pull request:

```bash
npm run list-skills
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/in-progress/<skill-name>
```
