# xiaowan-skills

面向 Codex 的个人技能仓库，收纳可直接复用的工作流型 skills。  
当前内容覆盖两类任务：微信招投标信息处理，以及方案澄清与 README 重写。

## 适用场景

- 你想把常用提示词和脚本打包成可复用 skill。
- 你希望在本地 `~/.codex/skills` 中按需安装单个 skill，而不是引入整套模板工程。
- 你需要一条已经落地的路径来处理微信公众号招投标摘要、微信授权巡检、README 改写或方案追问。

## 不适用场景

- 你需要的是 npm、PyPI 或 Homebrew 形式的安装包。
- 你希望所有 skill 都只有自然语言提示、完全不依赖本地脚本或 Python 环境。
- 你要的是完整产品文档站，而不是一个以 skill 目录为核心的仓库。

## 先决条件

通用要求：

- 已安装并可使用 Codex。
- 可访问本地 skill 目录，例如 `~/.codex/skills/`。

仅微信类 skills 需要：

- Python 3.9+
- 可在本机完成微信扫码授权
- 如需邮件发送或企业微信提醒，需要额外准备 SMTP 或企业微信机器人配置

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/liumingjian/xiaowan-skills.git
cd xiaowan-skills
```

### 2. 安装你需要的 skill

先创建本地 skill 目录：

```bash
mkdir -p ~/.codex/skills
```

如果你想先体验文档与方案类 skill：

```bash
cp -R skills/readme-designer ~/.codex/skills/
cp -R skills/grill-me ~/.codex/skills/
```

如果你想先体验微信类 skill：

```bash
cp -R skills/wechat-tender-digest ~/.codex/skills/
cp -R skills/wechat-tender-auth ~/.codex/skills/
```

### 3. 完成第一次成功结果

文档类：

- 在 Codex 中说：`使用 $readme-designer 重写当前仓库 README`
- 在 Codex 中说：`使用 $grill-me 帮我把这个方案逐层问清楚`

微信类：

```bash
python3 "skills/wechat-tender-auth/scripts/run_check.py"
python3 "skills/wechat-tender-digest/scripts/run_job.py" --doctor
```

可观察的成功标志：

- 本地出现 `~/.codex/skills/readme-designer`、`~/.codex/skills/grill-me` 等目录
- `wechat-tender-auth` 输出包含 `auth.authStatus` 的 JSON
- `wechat-tender-digest --doctor` 返回鉴权与 SMTP 诊断结果

## Skills

### 方案与文档

#### `readme-designer`

重写或审阅仓库 `README.md`。重点是中文导航结构、真实命令、首次上手路径，以及对 README 边界的控制。

```bash
cp -R skills/readme-designer ~/.codex/skills/
```

入口文件：

- [`skills/readme-designer/SKILL.md`](skills/readme-designer/SKILL.md)
- [`skills/readme-designer/references/repo-type-patterns.md`](skills/readme-designer/references/repo-type-patterns.md)
- [`skills/readme-designer/references/quality-bar.md`](skills/readme-designer/references/quality-bar.md)

#### `grill-me`

围绕一个方案或设计逐层追问。适合在动手前把假设、依赖和决策分支问透。

```bash
cp -R skills/grill-me ~/.codex/skills/
```

入口文件：

- [`skills/grill-me/SKILL.md`](skills/grill-me/SKILL.md)

### 微信招投标与巡检

#### `wechat-tender-digest`

从微信公众号文章中提取招标、中标、采购相关信息，生成 HTML 报告，并可选邮件发送。

```bash
cp -R skills/wechat-tender-digest ~/.codex/skills/
```

常用命令：

```bash
python3 "skills/wechat-tender-digest/scripts/run_job.py" --login
python3 "skills/wechat-tender-digest/scripts/run_job.py" --doctor
python3 "skills/wechat-tender-digest/scripts/run_job.py" --job "skills/wechat-tender-digest/config/jobs/default.job.yaml"
```

适合：

- 跟踪特定公众号的招标或中标信息
- 按关键词、分类和时间窗口生成日报
- 把结果输出为 HTML 并发送邮件

不适合：

- 无法在本机完成微信扫码授权的环境
- 只想抓取开放 API 数据、不需要公众号内容解析的场景

关键文件：

- [`skills/wechat-tender-digest/SKILL.md`](skills/wechat-tender-digest/SKILL.md)
- [`skills/wechat-tender-digest/config/first-time-setup.md`](skills/wechat-tender-digest/config/first-time-setup.md)
- [`skills/wechat-tender-digest/config/preferences-schema.md`](skills/wechat-tender-digest/config/preferences-schema.md)
- [`skills/wechat-tender-digest/references/yaml-config.md`](skills/wechat-tender-digest/references/yaml-config.md)

#### `wechat-tender-auth`

检查微信 MP 授权状态，并在授权失效或不可达时通过企业微信机器人发送提醒。适合配合 Codex automation 做定时巡检。

```bash
cp -R skills/wechat-tender-auth ~/.codex/skills/
```

常用命令：

```bash
python3 "skills/wechat-tender-auth/scripts/run_check.py"
python3 "skills/wechat-tender-auth/scripts/run_check.py" --notify
```

适合：

- 定时检测微信授权是否过期
- 在授权异常时触发企业微信提醒

不适合：

- 不具备企业微信机器人 Webhook 的提醒场景
- 期望在无本机参与前提下自动完成扫码续期的场景

关键文件：

- [`skills/wechat-tender-auth/SKILL.md`](skills/wechat-tender-auth/SKILL.md)
- [`skills/wechat-tender-auth/scripts/run_check.py`](skills/wechat-tender-auth/scripts/run_check.py)

## 配置说明

必需配置：

- `readme-designer` 与 `grill-me` 无额外运行时配置，复制到 skill 目录即可使用。
- `wechat-tender-digest` 至少需要可用的微信授权状态；如使用 `--job`，还需要有效的 job YAML。
- `wechat-tender-auth` 在仅检查模式下无额外必填项；如使用 `--notify`，需要企业微信机器人相关配置。

常用可选配置：

- 项目级或用户级 `.wechat-bid-digest/EXTEND.md`
- `skills/wechat-tender-digest/config/jobs/*.yaml`
- `~/.codex/skills/` 之外的项目级 `.codex/skills/`

## 仓库结构

```text
xiaowan-skills/
├── README.md
├── docs/
│   └── readme-backup-20260415.md
└── skills/
    ├── grill-me/
    ├── readme-designer/
    ├── wechat-tender-auth/
    └── wechat-tender-digest/
```

每个 skill 目录尽量保持自包含，常见组成如下：

- `SKILL.md`：触发描述与工作流规则
- `agents/openai.yaml`：展示名称与默认 prompt
- `references/`：补充规则、模板或参考资料
- `scripts/`：需要本地执行的脚本
- `config/`：示例配置与初始化说明

## 文档导航

- README 重写规则：[`skills/readme-designer/SKILL.md`](skills/readme-designer/SKILL.md)
- README 质量门槛：[`skills/readme-designer/references/quality-bar.md`](skills/readme-designer/references/quality-bar.md)
- 方案追问规则：[`skills/grill-me/SKILL.md`](skills/grill-me/SKILL.md)
- 微信摘要初始化：[`skills/wechat-tender-digest/config/first-time-setup.md`](skills/wechat-tender-digest/config/first-time-setup.md)
- 微信摘要配置结构：[`skills/wechat-tender-digest/config/preferences-schema.md`](skills/wechat-tender-digest/config/preferences-schema.md)

## 贡献与许可

当前仓库已经适合按目录增量收纳新 skill，但还没有看到 `CONTRIBUTING.md` 和 `LICENSE`。  
如果你准备对外分发或接受外部贡献，建议下一步补上这两个文件，并为每个新 skill 保持统一的目录约定。
