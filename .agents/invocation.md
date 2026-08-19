# Model-invoked vs user-invoked

Every skill is reachable by its name. The invocation axis decides whether the agent may also choose it automatically:

- **User-invoked** - set `policy.allow_implicit_invocation: false` in `agents/openai.yaml`. Use this for deliberate, side-effectful workflows. Claude Code-only frontmatter may add `disable-model-invocation: true` when the target harness supports it.
- **Model-invoked** - omit both controls. Write a trigger-rich `description` so the agent can reach it when the task fits.

Keep the two harnesses aligned. A skill that is user-invoked in one must be user-invoked in the other.

Skills may refer to another skill by name when the host provides a Skill tool. A bucket README is a human catalog, not an invocation instruction.
