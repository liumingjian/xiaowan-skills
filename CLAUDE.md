# Xiaowan Skills

Skills are organized into bucket folders under `skills/`:

- `engineering/` - stable engineering workflows
- `productivity/` - stable non-code workflows
- `misc/` - useful skills not promoted to the main catalog
- `in-progress/` - public beta skills
- `deprecated/` - retired skills

The installable contract is a directory containing `SKILL.md`. The Skills CLI discovers both `skills/<skill>/SKILL.md` and `skills/<bucket>/<skill>/SKILL.md`, so keep the bucket level exactly one directory deep.

Every skill also carries `agents/openai.yaml` for Codex UI metadata. For a user-invoked skill, set `policy.allow_implicit_invocation: false`; keep the policy in sync with the intended invocation boundary.

Keep `README.md` and each bucket `README.md` in sync with the catalog. Use `scripts/list-skills.sh` to inspect every skill and `scripts/link-skills.sh` to link the repository into local harness directories. The supported user installation path is:

```bash
npx skills@latest add liumingjian/xiaowan-skills
```

Read `.agents/invocation.md` before changing skill invocation behavior and `.agents/install-block.md` before changing installation wording.
