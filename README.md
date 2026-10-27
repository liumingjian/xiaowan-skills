# Xiaowan Skills

Small, composable agent skills for practical engineering work. Each skill is an ordinary directory with a `SKILL.md`, so you can install it into Codex, Claude Code, or another compatible agent without wrapping it in an application package.

## Installation

For Codex, add the marketplace and install the plugin:

```bash
codex plugin marketplace add liumingjian/xiaowan-skills
codex plugin add xiaowan-skills@xiaowan
```

Start a new Codex session after installation. Use `/skills` to find the installed skills. To invoke a skill, type `$` and select it, or use its full name, such as `$xiaowan-skills:readme-designer`.

For Claude Code or another compatible agent, use the Skills CLI from your project root:

```bash
npx skills@latest add liumingjian/xiaowan-skills
```

Install one skill at a time with:

```bash
npx skills@latest add liumingjian/xiaowan-skills --skill delegate-to-cc
```

The Skills CLI discovers `SKILL.md` files under `skills/<bucket>/<skill>/`. Use `-g` for a global install or `--list` to inspect the catalog before installing.

## Skills

Most skills here are public beta releases. They stay in `skills/in-progress/` until their behavior and interfaces are stable. Stable engineering workflows live in `skills/engineering/`; `skills/misc/` holds useful skills not promoted to the main catalog.

- **[accept-milestone](./skills/in-progress/accept-milestone/SKILL.md)** - Run a clean-room, end-to-end acceptance pass and produce a plain-language verdict.
- **[delegate-to-cc](./skills/in-progress/delegate-to-cc/SKILL.md)** - Send a Git or non-Git project snapshot to Claude Code on `vps-2g` for a second opinion or patch.
- **[delegate-to-codex](./skills/in-progress/delegate-to-codex/SKILL.md)** - Send the current project through rexec to Codex on the paired Mac mini for a second opinion or patch.
- **[intranet-rexec](./skills/in-progress/intranet-rexec/SKILL.md)** - Run commands and transfer files on company intranet servers from `vps-cc` through rexec and the paired Mac mini.
- **[intranet-ssh](./skills/in-progress/intranet-ssh/SKILL.md)** - Log in, run commands, and transfer files on company intranet servers through the saved SOCKS5 proxy.
- **[readme-designer](./skills/in-progress/readme-designer/SKILL.md)** - Review or rewrite a repository README around real facts, navigation, and a verifiable first run.
- **[rexec](./skills/engineering/rexec/SKILL.md)** - Run durable builds, tests, and other heavy work from `vps-cc` on the paired Mac mini.
- **[size-tickets](./skills/engineering/size-tickets/SKILL.md)** - Estimate each ticket's implementer context peak and tier before a spec's slicing is final.

`delegate-to-cc` requires the local `ssh`, `scp`, `tar`, and `find` commands plus the `vps-2g` SSH alias. The remote host provides Claude Code and its own disposable Git metadata for patch generation.

`rexec` in `skills/engineering/` uses the fixed `vps-cc` channel and one Mac mini. A user background service pulls jobs, and independent supervisors keep them running across closed viewers and interrupted waits. Setup and deployment tooling is provided separately; installing the skill does not install a live service. See its [reference](./skills/engineering/rexec/REFERENCE.md) for setup and privacy limits.

`delegate-to-codex` requires the `rexec` skill and the Codex CLI on the paired Mac mini. It submits durable background work and collects validated response, patch, and status text artifacts. Raw Codex logs remain private on the Mac. Implement mode creates a disposable Git baseline in the synced workspace; applying the returned patch is a separate reviewed step.

`size-tickets` needs `python3` and `git` and runs anywhere the repository is checked out. Its coefficients are calibrated from the implemented tickets in its `calibration.tsv`; each `learn` run adds rows, refits behind a regression guard, and ships the change through a reviewed PR.

`intranet-ssh` uses macOS OpenSSH, Ruby, `sshpass`, and an existing private company connection configuration. Installing the skill does not provision credentials. It supports root SSH access to `192.168.0.0/16` without changing system routes or proxy settings.

`intranet-rexec` requires the `rexec` skill and intranet-ssh installed under `~/.agents/skills` on the paired Mac mini, which holds the company configuration. It runs one-shot commands and single-file transfers without an interactive login, and rexec output filtering shows intranet addresses as `[private]`.

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

To test the Codex plugin from a local checkout, use a temporary Codex home:

```bash
xiaowan_codex_home="$(mktemp -d)"
CODEX_HOME="$xiaowan_codex_home" codex plugin marketplace add "$PWD"
CODEX_HOME="$xiaowan_codex_home" codex plugin list --available --json
CODEX_HOME="$xiaowan_codex_home" codex plugin add xiaowan-skills@xiaowan
```

When you add, move, or retire a skill, update the explicit `skills` list in `.codex-plugin/plugin.json`. Include every active skill and preserve its bucket path. Keep the plugin version in sync with `package.json`.
