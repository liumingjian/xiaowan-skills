# Xiaowan Skills

This repository is a catalog of self-contained agent skills, not an application.

## Vocabulary

- **Skill** - one directory with a `SKILL.md` entrypoint and optional supporting files.
- **Bucket** - one of the five directories under `skills/` that communicates release status and audience.
- **Beta** - a skill in `skills/in-progress/`; it is installable through the Skills CLI but not treated as stable.
- **Harness** - an agent host such as Codex or Claude Code that can load `SKILL.md`.
- **Skills CLI** - the `npx skills@latest` installer that discovers and installs this repository's skills.

The user-facing installation path is the Skills CLI. Local linking is a maintainer convenience, not a second distribution format.
