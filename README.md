# xiaowan-skills

一组我在打磨中的 Codex skills——把已经跑通的工作流固化下来，随用随取。

这些 skill 刻意做得**小、可改、可组合**：每个就是一个自包含目录，克隆下来拷进 `~/.codex/skills/` 即可用，不引入整套模板工程，也不需要 npm/PyPI 安装。

> **注意**：目前仓库里的 skill 都还没经过我正式验证，统一放在 `skills/in-progress/` 下。欢迎试用，但请自行判断是否适合你的场景。验证稳定后会迁出到正式分类目录。

## 这些 skill 解决什么问题

每个 skill 都对应一个具体的失败场景，按"问题 → 对策"列出。

### #1 做完一个里程碑，不知道到底成没成

**问题**：一个 Milestone 版本开发完，想验收，却发现"验收"这件事本身依赖对系统的熟悉——只有作者本人跑得动，换个人根本无从下手，也容易漏测还自以为测完了。

**对策**：[`accept-milestone`](./skills/in-progress/accept-milestone/SKILL.md)。它把验收固化成一条洁净室生命周期：`teardown → precheck → init → step test → destroy`，首尾各清一次场，保证第一次跑和第五次跑结果一致。它要求 agent 只用"新人能读到的资料 + 刚观察到的输出"下结论——于是**连没接触过该系统的人也能照着跑并签收**，最后产出一份白话的 ACCEPTED / REJECTED 结论。

### #2 README 像给维护者看的笔记

**问题**：仓库首页要么是一长段项目背景，要么功能列表直接等于源码模块，第一次进来的人读完仍不知道该干什么。

**对策**：[`readme-designer`](./skills/in-progress/readme-designer/SKILL.md)。面向首次读者重写 README：导航型结构、真实命令、可验证的首个成功路径，并带一套自检 quality-bar，明确禁止无证据的营销形容词。

## 快速开始（30 秒上手）

### 1. 克隆仓库

```bash
git clone https://github.com/liumingjian/xiaowan-skills.git
cd xiaowan-skills
```

### 2. 把需要的 skill 拷进 Codex 技能目录

两个 skill 都是纯提示词，拷完即用，无额外依赖：

```bash
mkdir -p ~/.codex/skills
cp -R skills/in-progress/accept-milestone ~/.codex/skills/
cp -R skills/in-progress/readme-designer  ~/.codex/skills/
```

### 3. 完成第一次成功结果

在 Codex 中直接用 `$` 触发，例如：

- `使用 $accept-milestone 验收当前仓库的 v0.3 里程碑`
- `使用 $readme-designer 重写当前仓库 README`

**可观察的成功标志**：`~/.codex/skills/` 下出现对应目录；`accept-milestone` 跑完给出一份带 ACCEPTED/REJECTED 结论的验收报告；`readme-designer` 先产出重写大纲、确认后再改写 README。

## Skills 一览

### 进行中（in-progress）

> 以下 skill 尚未正式验证，接口与行为可能变动。

#### `accept-milestone`

对一个 milestone 版本做端到端验收，全程由 agent 驱动并产出小白也能据以签收的白话结论。纯提示词 skill，无脚本依赖。

```bash
cp -R skills/in-progress/accept-milestone ~/.codex/skills/
```

适合：

- 一个 Milestone / 版本开发完成后，想做一次全面、可重复的 E2E 验收
- 希望没接触过该系统的人也能照流程独立完成验收

不适合：

- 只想跑单元测试或某一个函数的局部验证
- 系统无法从零拉起、也无法干净拆除的环境（这类情况本身会被判为验收失败）

入口文件：[`skills/in-progress/accept-milestone/SKILL.md`](skills/in-progress/accept-milestone/SKILL.md)

#### `readme-designer`

重写或审阅仓库 `README.md`，强调中文导航结构、真实命令、首次上手路径与反营销表达。

```bash
cp -R skills/in-progress/readme-designer ~/.codex/skills/
```

入口文件：

- [`skills/in-progress/readme-designer/SKILL.md`](skills/in-progress/readme-designer/SKILL.md)
- [`skills/in-progress/readme-designer/references/quality-bar.md`](skills/in-progress/readme-designer/references/quality-bar.md)
- [`skills/in-progress/readme-designer/references/repo-type-patterns.md`](skills/in-progress/readme-designer/references/repo-type-patterns.md)

## 前置条件

- 已安装并可使用 Codex
- 可访问本地 skill 目录，例如 `~/.codex/skills/`

两个 skill 均为纯提示词，拷贝即用，无额外运行时配置。

## 仓库结构

```text
xiaowan-skills/
├── README.md
└── skills/
    └── in-progress/
        ├── accept-milestone/
        └── readme-designer/
```

参照 [mattpocock/skills](https://github.com/mattpocock/skills) 的分目录约定：`skills/` 下按状态或类别分子目录。当前只有一个 `in-progress/` 分类，验证稳定的 skill 会迁到正式分类下。

每个 skill 目录尽量自包含，常见组成：`SKILL.md`（触发描述与工作流规则）、`references/`（补充规则与模板）、`agents/`（展示名称与默认 prompt）。

## 文档导航

- 里程碑验收流程：[`skills/in-progress/accept-milestone/SKILL.md`](skills/in-progress/accept-milestone/SKILL.md)
- README 重写规则与质量门槛：[`skills/in-progress/readme-designer/SKILL.md`](skills/in-progress/readme-designer/SKILL.md) · [`quality-bar.md`](skills/in-progress/readme-designer/references/quality-bar.md)

## 贡献与许可

仓库按目录增量收纳新 skill。目前尚无 `CONTRIBUTING.md` 与 `LICENSE`——如果准备对外分发或接受外部贡献，建议补上这两个文件，并为每个新 skill 保持统一的目录约定。
