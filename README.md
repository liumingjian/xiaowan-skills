# xiaowan-skills

一组可复用的 agent skills——把跑通过的工作流固化成自包含的 `SKILL.md`，克隆下来拷进任意编程智能体的 skills 目录即可用，不绑定特定工具，也无需 npm/PyPI 安装。目前 skill 均在验证中，统一置于 `skills/in-progress/`，接口可能变动。

## 快速上手

```bash
git clone https://github.com/liumingjian/xiaowan-skills.git

# 拷进你所用智能体的 skills 目录（如 Codex 的 ~/.codex/skills/、Claude Code 的 ~/.claude/skills/）
cp -R xiaowan-skills/skills/in-progress/accept-milestone ~/.codex/skills/
```

拷贝后在智能体中用 skill 名触发即可（例如 Codex 用 `$accept-milestone`）。需要外部工具的 skill 会在下方注明依赖。

## 使用场景

- **做完一个里程碑想验收** — 说「验收当前仓库的 v0.3 里程碑」，`accept-milestone` 从零拉起系统、逐条跑验收场景、再干净拆除，产出连没接触过系统的人也能据以签收的 ACCEPTED / REJECTED 结论。
- **README 像给维护者的笔记** — 说「重写这个仓库的 README」，`readme-designer` 先给重写大纲，确认后按导航结构与真实命令重写，并用自检 quality-bar 挡掉营销话术。
- **Codex 遇到疑难或需要第二品味判断** — 显式调用 `$delegate-to-cc`，把当前仓库快照交给 `vps-2g` 上的 Claude Code 分析或实现，再由 Codex 在本地审查、应用和验证。

## Reference

按状态分类，验证稳定后迁入正式类别。

**In-progress**

- **[accept-milestone](./skills/in-progress/accept-milestone/SKILL.md)** — 对 milestone 版本做端到端验收：洁净室生命周期 teardown → precheck → init → step test → destroy，输出白话验收结论。
- **[readme-designer](./skills/in-progress/readme-designer/SKILL.md)** — 面向首次读者重写 / 审阅仓库 README，附反营销的自检 quality-bar。
- **[delegate-to-cc](./skills/in-progress/delegate-to-cc/SKILL.md)** — 通过 SSH 别名 `vps-2g` 将 tracked 仓库快照交给远端 Claude Code 做二审，返回答复与补丁；依赖本地 `git` / `ssh` / `scp` / `tar`，以及服务器上的 Bash / Git / tar / GNU `timeout` / Claude Code。
