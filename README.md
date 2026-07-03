# xiaowan-skills

一组可复用的 agent skills——把跑通过的工作流固化成自包含的 `SKILL.md`，克隆下来拷进任意编程智能体的 skills 目录即可用，不绑定特定工具，也无需 npm/PyPI 安装。目前 skill 均在验证中，统一置于 `skills/in-progress/`，接口可能变动。

## 快速上手

```bash
git clone https://github.com/liumingjian/xiaowan-skills.git

# 拷进你所用智能体的 skills 目录（如 Codex 的 ~/.codex/skills/、Claude Code 的 ~/.claude/skills/）
cp -R xiaowan-skills/skills/in-progress/accept-milestone ~/.codex/skills/
```

拷贝后在智能体中用 skill 名触发即可（例如 Codex 用 `$accept-milestone`）。两个 skill 均为纯提示词，无额外依赖。

## 使用场景

- **做完一个里程碑想验收** — 说「验收当前仓库的 v0.3 里程碑」，`accept-milestone` 从零拉起系统、逐条跑验收场景、再干净拆除，产出连没接触过系统的人也能据以签收的 ACCEPTED / REJECTED 结论。
- **README 像给维护者的笔记** — 说「重写这个仓库的 README」，`readme-designer` 先给重写大纲，确认后按导航结构与真实命令重写，并用自检 quality-bar 挡掉营销话术。

## Reference

按状态分类，验证稳定后迁入正式类别。

**In-progress**

- **[accept-milestone](./skills/in-progress/accept-milestone/SKILL.md)** — 对 milestone 版本做端到端验收：洁净室生命周期 teardown → precheck → init → step test → destroy，输出白话验收结论。
- **[readme-designer](./skills/in-progress/readme-designer/SKILL.md)** — 面向首次读者重写 / 审阅仓库 README，附反营销的自检 quality-bar。
