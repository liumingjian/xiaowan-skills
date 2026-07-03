# xiaowan-skills

一组我每天在用的 Codex skills——把已经验证过的工作流固化下来，随用随取。

这些 skill 刻意做得**小、可改、可组合**：每个就是一个自包含目录，克隆下来拷进 `~/.codex/skills/` 即可用，不引入整套模板工程，也不需要 npm/PyPI 安装。它们解决的是我在用 Codex 做真实工作时反复踩到的几个坑，而不是替你接管整个流程。

## 这些 skill 解决什么问题

每个 skill 都对应一个具体的失败场景。下面按"问题 → 对策"列出，你可以只挑自己需要的那一两个。

### #1 做完一个里程碑，不知道到底成没成

**问题**：一个 Milestone 版本开发完，想验收，却发现"验收"这件事本身依赖对系统的熟悉——只有作者本人跑得动，换个人根本无从下手，也容易漏测还自以为测完了。

**对策**：[`accept-milestone`](./skills/accept-milestone/SKILL.md)。它把验收固化成一条洁净室生命周期：`teardown → precheck → init → step test → destroy`，首尾各清一次场，保证第一次跑和第五次跑结果一致。它要求 agent 只用"新人能读到的资料 + 刚观察到的输出"下结论——于是**连没接触过该系统的人也能照着跑并签收**，最后产出一份白话的 ACCEPTED / REJECTED 结论。

### #2 方案还没问清就开工

**问题**：需求你以为讲明白了，agent 也以为听懂了，结果做出来完全不是你要的。多数返工都来自这一步的错位。

**对策**：[`grill-me`](./skills/grill-me/SKILL.md)。动手前先让 agent 逐层追问，把假设、依赖和每个决策分支问透，每个问题还附上它的推荐答案。

### #3 README 像给维护者看的笔记

**问题**：仓库首页要么是一长段项目背景，要么功能列表直接等于源码模块，第一次进来的人读完仍不知道该干什么。

**对策**：[`readme-designer`](./skills/readme-designer/SKILL.md)。面向首次读者重写 README：导航型结构、真实命令、可验证的首个成功路径，并带一套自检 quality-bar，明确禁止无证据的营销形容词。

### #4 招投标信息散落在公众号里

**问题**：招标、中标、采购公告分散在一堆微信公众号，人工盯很费时；而微信授权还会悄悄过期，让定时任务无声失败。

**对策**：一对 skill 配合使用——[`wechat-tender-digest`](./skills/wechat-tender-digest/SKILL.md) 从公众号文章里提取招投标信息、按关键词生成 HTML 日报并可邮件发送；[`wechat-tender-auth`](./skills/wechat-tender-auth/SKILL.md) 定时巡检授权状态，失效时用企业微信机器人推送提醒。

## 快速开始（30 秒上手）

### 1. 克隆仓库

```bash
git clone https://github.com/liumingjian/xiaowan-skills.git
cd xiaowan-skills
```

### 2. 把需要的 skill 拷进 Codex 技能目录

```bash
mkdir -p ~/.codex/skills

# 纯提示词类，拷完即用，无额外依赖
cp -R skills/accept-milestone ~/.codex/skills/
cp -R skills/grill-me         ~/.codex/skills/
cp -R skills/readme-designer  ~/.codex/skills/

# 微信类，需要 Python 3.9+ 与本机扫码授权
cp -R skills/wechat-tender-digest ~/.codex/skills/
cp -R skills/wechat-tender-auth   ~/.codex/skills/
```

### 3. 完成第一次成功结果

在 Codex 中直接用 `$` 触发，例如：

- `使用 $accept-milestone 验收当前仓库的 v0.3 里程碑`
- `使用 $grill-me 帮我把这个方案逐层问清楚`
- `使用 $readme-designer 重写当前仓库 README`

微信类可先跑自检脚本确认环境：

```bash
python3 "skills/wechat-tender-auth/scripts/run_check.py"
python3 "skills/wechat-tender-digest/scripts/run_job.py" --doctor
```

**可观察的成功标志**：`~/.codex/skills/` 下出现对应目录；`wechat-tender-auth` 输出含 `auth.authStatus` 的 JSON；`wechat-tender-digest --doctor` 返回鉴权与 SMTP 诊断结果。

## Skills 一览

### 工程与验收

#### `accept-milestone`

对一个 milestone 版本做端到端验收，全程由 agent 驱动并产出小白也能据以签收的白话结论。纯提示词 skill，无脚本依赖。

```bash
cp -R skills/accept-milestone ~/.codex/skills/
```

适合：

- 一个 Milestone / 版本开发完成后，想做一次全面、可重复的 E2E 验收
- 希望没接触过该系统的人也能照流程独立完成验收

不适合：

- 只想跑单元测试或某一个函数的局部验证
- 系统无法从零拉起、也无法干净拆除的环境（这类情况本身会被判为验收失败）

入口文件：[`skills/accept-milestone/SKILL.md`](skills/accept-milestone/SKILL.md)

### 方案与文档

#### `grill-me`

围绕一个方案或设计逐层追问，适合在动手前把假设、依赖和决策分支问透。

```bash
cp -R skills/grill-me ~/.codex/skills/
```

入口文件：[`skills/grill-me/SKILL.md`](skills/grill-me/SKILL.md)

#### `readme-designer`

重写或审阅仓库 `README.md`，强调中文导航结构、真实命令、首次上手路径与反营销表达。

```bash
cp -R skills/readme-designer ~/.codex/skills/
```

入口文件：

- [`skills/readme-designer/SKILL.md`](skills/readme-designer/SKILL.md)
- [`skills/readme-designer/references/quality-bar.md`](skills/readme-designer/references/quality-bar.md)
- [`skills/readme-designer/references/repo-type-patterns.md`](skills/readme-designer/references/repo-type-patterns.md)

### 微信招投标与巡检

#### `wechat-tender-digest`

从微信公众号文章中提取招标、中标、采购信息，生成 HTML 报告并可选邮件发送。

```bash
cp -R skills/wechat-tender-digest ~/.codex/skills/
```

常用命令：

```bash
python3 "skills/wechat-tender-digest/scripts/run_job.py" --login
python3 "skills/wechat-tender-digest/scripts/run_job.py" --doctor
python3 "skills/wechat-tender-digest/scripts/run_job.py" --job "skills/wechat-tender-digest/config/jobs/default.job.yaml"
```

适合：跟踪特定公众号的招投标信息、按关键词与时间窗口生成日报、输出 HTML 并发邮件。
不适合：无法在本机完成扫码授权，或只想抓开放 API、不需要公众号内容解析的场景。

关键文件：

- [`skills/wechat-tender-digest/SKILL.md`](skills/wechat-tender-digest/SKILL.md)
- [`skills/wechat-tender-digest/config/first-time-setup.md`](skills/wechat-tender-digest/config/first-time-setup.md)
- [`skills/wechat-tender-digest/references/yaml-config.md`](skills/wechat-tender-digest/references/yaml-config.md)

#### `wechat-tender-auth`

检查微信 MP 授权状态，失效或不可达时通过企业微信机器人推送提醒，适合配合定时巡检。

```bash
cp -R skills/wechat-tender-auth ~/.codex/skills/
```

常用命令：

```bash
python3 "skills/wechat-tender-auth/scripts/run_check.py"
python3 "skills/wechat-tender-auth/scripts/run_check.py" --notify
```

适合：定时检测授权是否过期、异常时触发企业微信提醒。
不适合：没有企业微信机器人 Webhook，或期望无人参与自动完成扫码续期的场景。

关键文件：

- [`skills/wechat-tender-auth/SKILL.md`](skills/wechat-tender-auth/SKILL.md)
- [`skills/wechat-tender-auth/scripts/run_check.py`](skills/wechat-tender-auth/scripts/run_check.py)

## 前置条件

通用：

- 已安装并可使用 Codex
- 可访问本地 skill 目录，例如 `~/.codex/skills/`

仅微信类需要：

- Python 3.9+
- 可在本机完成微信扫码授权
- 如需邮件发送或企业微信提醒，另需 SMTP 或企业微信机器人配置

`accept-milestone`、`grill-me`、`readme-designer` 拷贝即用，无额外运行时配置。

## 仓库结构

```text
xiaowan-skills/
├── README.md
├── docs/
│   └── readme-backup-*.md
└── skills/
    ├── accept-milestone/
    ├── grill-me/
    ├── readme-designer/
    ├── wechat-tender-auth/
    └── wechat-tender-digest/
```

每个 skill 目录尽量自包含，常见组成：`SKILL.md`（触发描述与工作流规则）、`references/`（补充规则与模板）、`scripts/`（本地脚本）、`config/`（示例配置与初始化说明）。

## 文档导航

- 里程碑验收流程：[`skills/accept-milestone/SKILL.md`](skills/accept-milestone/SKILL.md)
- README 重写规则与质量门槛：[`skills/readme-designer/SKILL.md`](skills/readme-designer/SKILL.md) · [`quality-bar.md`](skills/readme-designer/references/quality-bar.md)
- 方案追问规则：[`skills/grill-me/SKILL.md`](skills/grill-me/SKILL.md)
- 微信摘要初始化与配置：[`first-time-setup.md`](skills/wechat-tender-digest/config/first-time-setup.md) · [`preferences-schema.md`](skills/wechat-tender-digest/config/preferences-schema.md)

## 贡献与许可

仓库按目录增量收纳新 skill。目前尚无 `CONTRIBUTING.md` 与 `LICENSE`——如果准备对外分发或接受外部贡献，建议补上这两个文件，并为每个新 skill 保持统一的目录约定。
