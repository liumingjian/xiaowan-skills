---
name: wechat-tender-digest
description: WeChat bid/tender information digest and monitoring tool. Use this skill whenever the user wants to track, monitor, or subscribe to tender/bid announcements ("招标") or award results ("中标") from WeChat official accounts; collect procurement information ("采购") from specific WeChat accounts like 七小服, 天下观查, 银标Daily, A信创圈俱乐部; set up automated daily/weekly digests of bid information with keyword filtering; generate HTML reports of tender/award data and send via email; or query historical bid/tender announcements from WeChat public accounts. Trigger even if the user doesn't explicitly say "bid digest" - if they mention monitoring WeChat accounts for procurement/tender/award information, collecting bid data, or want automated reports of government/enterprise purchasing announcements, use this skill. Preset scenarios include IT infrastructure (xinc), hardware equipment, software procurement, and engineering projects.
version: 2.0.0
---

# WeChat Tender Digest

Extract tender and award information from WeChat official account articles, generate HTML reports, and deliver via email. Self-contained — no Docker or external gateway required.

## Language

**IMPORTANT**: Communicate with the user in Chinese (中文) unless explicitly requested otherwise.

## Prerequisites

- Python 3.9+
- 依赖会在首次运行时自动安装（requests, qrcode, Pillow, pyzbar）

## Script Directory

**Important**: All scripts are located in the `scripts/` subdirectory of this skill.

**Agent Execution Instructions**:
1. Determine this `SKILL.md` file's directory path as `{baseDir}`
2. Script path = `{baseDir}/scripts/run_job.py`
3. Replace all `{baseDir}` in this document with the actual path

## Script Execution

使用 `{baseDir}` 绝对路径执行脚本（不依赖当前工作目录）：

```bash
python3 "{baseDir}/scripts/run_job.py" --doctor
```

输出目录：当前工作目录下的 `wechat-bid-digest/<job.name>/<YYYY-MM-DD>/`（可通过环境变量 `WECHAT_BID_OUTPUT_DIR` 自定义根目录）

## Quick Start

### First-time: Login

```bash
python3 "{baseDir}/scripts/run_job.py" --login
```

扫描二维码登录微信。认证有效期约4小时。详见 [first-time-setup](./config/first-time-setup.md)。

### Run a digest

```bash
python3 "{baseDir}/scripts/run_job.py" --accounts "七小服" --until parse
```

### Auth Health Check Automation (Recommended)

当你选择了邮件推送并且本次发送成功后，推荐开启“授权巡检自动化”：

- 定时运行 `$wechat-tender-auth`
- 在 `expired/unreachable` 时通过企业微信机器人 Webhook 推送提醒（提醒式，不承诺无人值守自动续期成功）
- 默认模式下：续期仍需你回到 Codex 执行 `--login` 扫码并确认登录（平台限制）
- 可选 Spike（实验）：配置 `mobile_renewal_mode=spike` + 部署 Worker + 本机常驻代理后，提醒链接可在手机端完成续期（仍需手机微信确认登录）

企业微信提醒需要在 EXTEND.md 配置以下字段（手机端可点开链接）：
- `wechat_work_webhook`
- 默认模式下还需要 `wechat_work_action_url`（推荐先用 `https://developers.openai.com/codex/app/automations` 作为入口）

说明：
- 巡检提醒发送前会校验 `wechat_work_action_url` 是否可达，并把结果写入提醒内容
- 该链接只是“处理入口”，不是直接触发本机扫码续期的深链；真正续期仍需回到当前电脑执行 `--login`

可选（降低重复提醒频率 / 逾期更醒目）：
- `wechat_work_notify_cooldown_seconds`（默认 21600，即 6 小时）
- `wechat_work_escalate_after_seconds`（默认 86400，即 24 小时）

默认推荐频率：每 3 小时（也可选每 6 小时 / 每天一次）。

如何修改调度时间：
- 在 Codex Automations 页面编辑该自动化的运行频率
- 或对 Codex 说“把微信授权巡检改成每 6 小时/每天一次”

### Auth Daemon (Debug)

如需本地调试 auth 健康检查循环，可使用 `--auth-daemon`（不作为主推荐路径）：

```bash
python3 "{baseDir}/scripts/run_job.py" --auth-daemon --auth-check-interval-seconds 600
```

## Interaction UX (Numbered Options)

对固定选项问题，统一使用 `baoyu-skills` 风格的“编号选项 + 推荐项 + 直接回复编号”。

规则：
- 不使用按钮工具，不依赖 Plan mode。
- 不写开放式问句，例如“你想要我怎么做？”。
- 直接给出 2-5 个编号选项，每个选项一行，必要时补一句简短说明。
- 有默认建议时，在选项文案中直接标注 `（推荐）`。
- 结尾固定写：`直接回复 1`、`直接回复 1 或 2`、`直接回复 1、2 或 3`。
- 用户只回复编号时，直接按对应选项继续，不重复追问“你是指哪个选项？”。

标准模板：

```text
请选择输出方式：
1. 邮件报告（推荐）：生成 HTML 报告，可发送/保存/转发
2. 控制台查看：直接显示摘要与统计，不发送邮件

直接回复 1 或 2。
```

常见选项：
- 输出方式：`1. 邮件报告（推荐）` `2. 控制台查看`
- 预设：`1. xinc（推荐）` `2. hardware` `3. software` `4. engineering` `5. 自定义`
- 信息类型：`1. 招标+中标（推荐）` `2. 仅招标` `3. 仅中标`
- 时间范围：`1. 最近1天` `2. 最近3天（推荐）` `3. 最近7天` `4. 最近14天` `5. 自定义日期范围`
- 字段显示范围：`1. 核心字段（推荐）` `2. 全字段` `3. 极简字段`
- 邮件布局：`1. hybrid（推荐）` `2. table` `3. card`
- 是否发送空结果：`1. 是` `2. 否（推荐）`
- 是否保存为 job：`1. 保存(项目级)` `2. 保存(用户级)` `3. 不保存（推荐）`
- 确认类：`1. 确认（推荐）` `2. 取消`

## Interactive Start (No Parameters)

When the user invokes `/wechat-tender-digest` without any parameters or context:

### Step 1: Ask about output mode

Send this exact style of message:

```text
使用技能：wechat-tender-digest。

请选择输出方式：
1. 邮件报告（推荐）：生成 HTML 报告，可发送/保存/转发
2. 控制台查看：直接在终端显示结果，不发送邮件

直接回复 1 或 2。
```

### Step 2: Collect email (if option 1 selected)

If user chose email mode, ask for recipient email address (free text):

```
请提供收件邮箱地址：

示例：your-email@example.com
```

**Validation**: Check email format before proceeding.

### Step 3: Use default configuration

Apply these defaults automatically (no user input needed):
- **公众号**: 七小服, 天下观查, 银标Daily, A信创圈俱乐部
- **时间范围**: 最近3天
- **信息类型**: 招标 + 中标
- **关键词**: xinc预设（信创、国产化、自主可控、操作系统、数据库、中间件、云平台、服务器、存储、网络设备）
- **布局**: hybrid（混合布局）
- **SMTP**: 预置 163 SMTP host/port（仍需用户提供 SMTP 凭据）

### Step 4: Proceed to Workflow Step 2

Continue to "Step 2: Confirm Configuration" with collected parameters.

## Interactive Start (User Has Prompt Text)

当用户已经输入了需求描述（例如“帮我看最近一周信创/服务器相关招标”），即使你能从文本里提取到部分参数，也必须给小白用户一个“快速推荐/自定义偏好”的入口。

### Step A: Ask quick vs custom

在已知输出方式（邮件/控制台）后，先问一次：

```text
我已理解你的需求描述，但还可以选择一些偏好（日期范围/信息类型/字段显示范围等）。

请选择：
1. 快速推荐（推荐）：按智能预设 + 推荐默认偏好直接运行
2. 自定义偏好：逐项选择日期/类型/关键词/字段显示范围等

直接回复 1 或 2。
```

### Step B: Preference Wizard (only if user chose custom)

只问“缺失/不明确”的项，按顺序最多 4-5 个问题（仍用编号选项）：
- 时间范围（最近1/3/7/14天 或 自定义日期范围）
- 信息类型（招标+中标 / 仅招标 / 仅中标）
- 关键词来源（智能预设 / 自定义关键词）
- 字段显示范围（核心/全字段/极简）
- 邮件布局（仅邮件输出时询问：hybrid/table/card）

推荐使用以下固定模板（保证问题具体、可复制、可选项明确）：

```text
请选择时间范围：
1. 最近 1 天
2. 最近 3 天（推荐）
3. 最近 7 天
4. 最近 14 天
5. 自定义日期范围：我会再问你起止日期（YYYY-MM-DD）

直接回复 1、2、3、4 或 5。
```

```text
请选择信息类型：
1. 招标 + 中标（推荐）
2. 仅招标
3. 仅中标

直接回复 1、2 或 3。
```

```text
请选择关键词策略：
1. 智能预设（推荐）：根据你的描述自动选择 xinc/hardware/software/engineering，并补齐常用关键词
2. 自定义关键词：我会让你输入关键词列表（用逗号分隔）

直接回复 1 或 2。
```

```text
请选择字段显示范围：
1. 核心字段（推荐）：项目名/金额/招标单位/发布时间/截止时间/中标单位/原文链接
2. 全字段：在核心字段基础上增加 项目编号/来源渠道 等
3. 极简字段：项目名/金额/发布时间/截止时间/原文链接

直接回复 1、2 或 3。
```

## Workflow (7 Steps)

### Step 1: Parse Input & Collect Parameters

Extract from user message:
- **Account names**: Names in quotes or defaults (七小服, 天下观查, 银标Daily, A信创圈俱乐部)
- **Preset**: xinc / hardware / software / engineering
- **Time range**: Natural language or default 3 days
- **Keywords**: Explicit terms or defaults
- **Recipients**: Email addresses (only if user wants email)
- **Layout**: table / card / hybrid (default: hybrid)

Load additional defaults from EXTEND.md preferences. See [preferences-schema](./config/preferences-schema.md).

如果用户的输入没有明确给出“时间范围/信息类型/关键词策略/字段显示范围”等关键偏好，必须走上面的 `Interactive Start (User Has Prompt Text)`：
- 先提供 `快速推荐/自定义偏好` 二选一
- 若选自定义，再逐项补齐缺失偏好
- 最终仍进入 Step 2 做配置摘要确认

### Step 2: Confirm Configuration

Display summary and wait for user confirmation:

```
📋 配置摘要
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 公众号: 七小服, 天下观查, 银标Daily, A信创圈俱乐部
📅 时间范围: 最近 3 天
🎯 信息类型: 招标 + 中标
🔍 关键词: 信创,国产化,自主可控,...（匹配任一）
📧 收件人: (控制台输出)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
确认执行？
```

Then ask:

```text
请选择：
1. 确认（推荐）：开始抓取文章并生成报告
2. 取消：结束本次运行

直接回复 1 或 2。
```

### Step 3: Check Auth & Fetch Articles

1. Ensure auth is valid (auto-triggers `--login` if expired)
2. Build CLI command and execute:

**Console mode** (no `--to`):
```bash
python3 "{baseDir}/scripts/run_job.py" \
  --accounts "七小服,天下观查,银标Daily,A信创圈俱乐部" \
  --keywords "信创,国产化,自主可控,操作系统,数据库,中间件,云平台,服务器,存储,网络设备,软件,硬件" \
  --categories "tender,award" \
  --window-days 3
```

**Email mode** (with `--to`):
```bash
python3 "{baseDir}/scripts/run_job.py" \
  --accounts "七小服,天下观查,银标Daily,A信创圈俱乐部" \
  --keywords "信创,国产化,自主可控,..." \
  --categories "tender,award" \
  --window-days 3 \
  --layout hybrid \
  --to "user@example.com"
```

### Step 4: Display Results

**Console mode**: Show statistics and record summary directly.

**Email mode**: Show statistics, ask for send confirmation via options.

Then ask:

```text
请选择：
1. 确认发送（推荐）：发送邮件到收件人列表
2. 取消：不发送邮件，结束本次发送步骤

直接回复 1 或 2。
```

```
📊 招投标信息汇总
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 获取文章: 28
📌 招标信息: 15
🎯 中标信息: 8
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 5: Generate Report & Send Email

After confirmation, script generates HTML report and sends email (if configured).

### Step 6: Setup Auth Check Automation (Optional, Recommended for Email Mode)

仅在 `email_sent` 成功后询问用户是否配置自动化（选项式问题）：

问题 1：

```text
邮件已发送成功。

是否开启授权巡检自动化？
1. 开启授权巡检（推荐）：定期检查微信授权状态，异常时企业微信提醒
2. 暂不配置：本次不设置巡检自动化

直接回复 1 或 2。
```

问题 2（仅当用户选择开启时）：

```text
请选择巡检频率：
1. 每 3 小时（推荐）：更及时发现授权过期
2. 每 6 小时：降低提醒频率
3. 每天一次：只做日常巡检

直接回复 1、2 或 3。
```

自动化的目标是“健康检查 + 提醒”，不承诺无人值守续期成功。异常提醒建议落到企业微信机器人 Webhook（见 `preferences-schema.md` 的 `wechat_work_*` 字段）。

Codex automation 创建指引参考：`https://developers.openai.com/codex/app/automations`

建议自动化配置（若已存在同名自动化则更新，否则创建）：
- 名称：`微信授权巡检`
- 频率映射：
  - 每 3 小时 → 每 3 小时运行一次
  - 每 6 小时 → 每 6 小时运行一次
  - 每天一次 → 固定每天一次
- prompt（不包含调度信息）：
  - 使用 `$wechat-tender-auth` 检查微信 MP 授权状态；若状态不是 healthy，则通过企业微信机器人 Webhook 推送提醒，并在 inbox 中保留本次检查结果。

### Step 7: Save as Job (Optional)

Ask user if they want to save configuration as YAML:

Then ask:

```text
是否将本次配置保存为 job？
1. 保存(项目级)：保存到当前项目，适合团队复用
2. 保存(用户级)：保存到当前用户目录，仅本机使用
3. 不保存（推荐）：本次运行结束，不写 job 文件

直接回复 1、2 或 3。
```

```bash
python3 "{baseDir}/scripts/run_job.py" --create-job \
  --accounts "七小服" --keywords "服务器,存储" --to "user@example.com"
```

## Default Configuration

| Config | Default | Notes |
|--------|---------|-------|
| Accounts | 七小服, 天下观查, 银标Daily, A信创圈俱乐部 | Mainstream sources |
| Time Range | 3 days | |
| Keywords | 信创,国产化,自主可控,操作系统,数据库,中间件,云平台,服务器,存储,网络设备,软件,硬件 | IT+hardware |
| Match Logic | OR | |
| Layout | hybrid | |

**Email rules**: Never send email without explicit user-provided recipients.

## Presets

| Preset | Scenario | Keywords |
|--------|----------|----------|
| `xinc` | IT Infrastructure | 信创, 国产化, 自主可控, 操作系统, 数据库, 中间件, 云平台 |
| `hardware` | Hardware Equipment | 维保, 服务器, 存储, 网络设备, UPS, 硬件, 机房 |
| `software` | Software Procurement | 软件, 许可, License, OA, ERP, CRM, 办公软件 |
| `engineering` | Engineering Projects | 工程, 施工, 基建, 装修, 弱电, 综合布线 |

## CLI Reference

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--accounts` | Account names | `--accounts "七小服,天下观查"` |
| `--keywords` | Keywords | `--keywords "服务器,存储"` |
| `--categories` | Info types | `--categories "tender,award"` |
| `--window-days` | Days back | `--window-days 3` |
| `--layout` | HTML layout | `--layout hybrid` |
| `--field-set` | Visible field preset | `--field-set core` |
| `--visible-fields` | Explicit visible fields (override) | `--visible-fields "project_name,amount,deadline"` |
| `--to` | Recipients | `--to "user@example.com"` |
| `--until` | Stop at stage | `--until parse` |
| `--login` | QR code login | `--login` |
| `--doctor` | Diagnostics | `--doctor` |
| `--create-job` | Save config | `--create-job` |
| `--job` | Load config | `--job "{baseDir}/jobs/qixiaofu-daily.yaml"` |
| `--auth-daemon` | Auth daemon | `--auth-daemon` |
| `--auth-check-interval-seconds` | Auth daemon interval | `--auth-check-interval-seconds 600` |

## SMTP Configuration

Configure via EXTEND.md (`~/.wechat-bid-digest/EXTEND.md`) or environment variables:

```markdown
## SMTP
- smtp_host: smtp.163.com
- smtp_port: 465
- smtp_username: user@163.com
- smtp_password: your_app_password
```

### 内部默认发件箱（可选）

为了内部“开箱即用”，SMTP 也支持读取一个用户级默认配置文件（不会覆盖已存在的环境变量）：

- 开关：`smtp_use_default_config`（默认 `true`）
- 默认文件：`~/.wechat-bid-digest/smtp-default.env`（KEY=VALUE 格式，建议 `chmod 600`）
- 推广/公开发布：把 `smtp_use_default_config` 配为 `false`，并移除/不分发该默认配置文件

See [preferences-schema](./config/preferences-schema.md) for all fields.

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `auth_expired` | WeChat login expired | Run `--login` to re-scan QR code |
| `login_failed` | QR scan timeout/cancelled | Retry `--login` |
| `smtp_failed` | Email sending failed | Check SMTP config via `--doctor` |
| `fetch_failed` | Article download failed | Check network; error logged in output |
| `auth_unhealthy` | WeChat interface unreachable | Check network and retry |
| `no_matching_records` | No matching records | Relax keywords or expand time range |

## Reference Documentation

- [preferences-schema.md](./config/preferences-schema.md) — EXTEND.md field documentation
- [first-time-setup.md](./config/first-time-setup.md) — First-time setup guide
- [auth-management.md](./references/auth-management.md) — Auth token lifecycle
- [presets.md](./references/presets.md) — Preset definitions
- [yaml-config.md](./references/yaml-config.md) — YAML configuration format
- [output-format.md](./references/output-format.md) — Output directory structure
