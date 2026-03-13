---
name: wechat-tender-digest
description: WeChat bid/tender information digest and monitoring tool. Use this skill whenever the user wants to track, monitor, or subscribe to tender/bid announcements ("招标") or award results ("中标") from WeChat official accounts; collect procurement information ("采购") from specific WeChat accounts like 七小服, 天下观查, 银标Daily, A信创圈俱乐部; set up automated daily/weekly digests of bid information with keyword filtering; generate HTML reports of tender/award data and send via email; or query historical bid/tender announcements from WeChat public accounts. Trigger even if the user doesn't explicitly say "bid digest" - if they mention monitoring WeChat accounts for procurement/tender/award information, collecting bid data, or want automated reports of government/enterprise purchasing announcements, use this skill. Preset scenarios include IT infrastructure (xinc), hardware equipment, software procurement, and engineering projects.
version: 2.0.0
---

# WeChat Tender Digest

Extract tender / award signals from WeChat official account articles, render HTML reports, and optionally deliver them by email.

## Usage

```bash
/wechat-tender-digest
/wechat-tender-digest --accounts "七小服" --until parse
/wechat-tender-digest --accounts "七小服,天下观查" --to "user@example.com"
```

## Options

### Core Run Options

| Option | Values | Description |
|--------|--------|-------------|
| `--accounts` | comma-separated names | Target WeChat official accounts |
| `--preset` | `xinc`, `hardware`, `software`, `engineering` | Load a keyword/category preset |
| `--keywords` | comma-separated keywords | Override preset/default keywords |
| `--categories` | `tender`, `award` | Filter bid / award records |
| `--window-days` | integer | Look-back window |
| `--from-date` / `--to-date` | `YYYY-MM-DD` | Explicit date range override |
| `--until` | `fetch`, `parse`, `render`, `send` | Stop at an intermediate stage |

### Report Options

| Option | Values | Description |
|--------|--------|-------------|
| `--layout` | `hybrid` (default), `table`, `card` | HTML report layout |
| `--field-set` | `core`, `full`, `minimal` | Visible field preset |
| `--visible-fields` | comma-separated field keys | Explicit field override |
| `--to` | comma-separated emails | Enable email delivery |
| `--create-job` | flag | Create a reusable job YAML |
| `--job` | YAML path | Load an existing job |

### Auth / Diagnostics Options

| Option | Description |
|--------|-------------|
| `--doctor` | Print auth + SMTP diagnostics |
| `--login` | Trigger QR login |
| `--auth-daemon` | Run auth daemon for local debugging only |
| `--auth-check-interval-seconds` | Auth daemon interval override |

### Presets

| Preset | Scenario | Typical Keywords |
|--------|----------|------------------|
| `xinc` | 信创 / IT infrastructure | 信创, 国产化, 自主可控, 操作系统, 数据库, 中间件 |
| `hardware` | Hardware / maintenance | 维保, 服务器, 存储, 网络设备, UPS, 机房 |
| `software` | Software procurement | 软件, 许可, License, OA, ERP, CRM |
| `engineering` | Construction / engineering | 工程, 施工, 基建, 装修, 弱电 |

## Auto Selection

Use the user's request to pick defaults before asking follow-up questions:

| Content Signals | Recommended Preset / Behavior |
|-----------------|-------------------------------|
| 信创, 国产化, 自主可控, 操作系统, 数据库 | `xinc` |
| 维保, 服务器, 存储, 网络设备 | `hardware` |
| 软件, OA, ERP, CRM, license | `software` |
| 工程, 施工, 弱电, 综合布线 | `engineering` |
| No clear signal | Use default accounts + `xinc`-leaning defaults, then ask preference options |

## Script Directory

All scripts live in the `scripts/` subdirectory of this skill.

**Agent Execution Instructions**:
1. Determine this `SKILL.md` file's directory as `{baseDir}`.
2. Main entry = `python3 "{baseDir}/scripts/run_job.py"`.
3. Resolve every relative path in this document from `{baseDir}` first.

**Script Reference**:

| Script | Purpose |
|--------|---------|
| `scripts/run_job.py` | Main entry for doctor/login/job execution |
| `scripts/run_job.py --doctor` | Structured diagnostics |
| `scripts/run_job.py --login` | QR login flow |

## File Structure

Project-local state lives under `.wechat-bid-digest/`. Run outputs live under `wechat-bid-digest/`.

### Project State

| Path | Description |
|------|-------------|
| `.wechat-bid-digest/EXTEND.md` | Project preferences |
| `.wechat-bid-digest/jobs/default.yaml` | Default reusable job |
| `.wechat-bid-digest/auth/state.json` | Saved WeChat auth state |
| `.wechat-bid-digest/auth/qrcode.png` | Login QR image |
| `.wechat-bid-digest/smtp-default.env` | Project-local default SMTP config |
| `.wechat-bid-digest/wecom/notify_state.json` | WeCom notification state |

### Run Output

Output directory: `wechat-bid-digest/{job-name}/{YYYY-MM-DD}/`

| File | Description |
|------|-------------|
| `raw/summary.json` | Fetched article summary |
| `parsed/records.json` | Parsed tender / award records |
| `{report_filename}.html` | HTML report |
| `send-result.json` | Final status payload |

## Language Handling

### Detection Priority

1. User-facing interaction language is always `中文`, unless the user explicitly asks for another language.
2. Agent-facing structure, section titles, workflow rules, and prompt scaffolding should default to English.
3. Domain nouns may remain in Chinese when they are part of the source ecosystem: `招标`, `中标`, `信创`, `公众号`.

### Rule

Use English for internal procedural guidance:
- section headers
- option descriptions
- workflow rules
- validation and blocking conditions

Use Chinese for all user-facing interaction:
- numbered options
- confirmations
- progress explanations
- error summaries
- result summaries

Technical identifiers stay in English: `--doctor`, `send-result.json`, `qrcode.png`, `smtp.ready`.

## Workflow

### Progress Checklist

```text
Digest Progress:
- [ ] Step 1: Load context & defaults
- [ ] Step 2: Ask user-facing options (required if preferences are incomplete)
- [ ] Step 3: Confirm configuration
- [ ] Step 4: Preflight checks
  - [ ] 4.1 Email mode -> run --doctor first
  - [ ] 4.2 Auth invalid -> run --login
- [ ] Step 5: Run pipeline (fetch -> parse -> render -> send)
- [ ] Step 6: Review result and optional auth automation
- [ ] Step 7: Save job (optional)
- [ ] Step 8: Completion summary
```

### Flow

```text
Input
  -> Load defaults / job / preferences
  -> [Missing preferences?] -> Ask numbered options in 中文
  -> Confirm summary
  -> [Email mode?] -> MUST run --doctor first
  -> [Auth invalid?] -> MUST run --login
  -> Run pipeline
  -> Review result
  -> [Email sent?] -> Offer auth automation setup
  -> [Save job?] -> Write YAML
  -> Complete
```

### Step Summary

| Step | Action | Key Output |
|------|--------|------------|
| 1 | Load defaults / job / preferences | Resolved config |
| 2 | Ask numbered options in 中文 | User choices |
| 3 | Confirm run summary | Approval / cancel |
| 4 | Run `--doctor` / `--login` as needed | Ready preflight state |
| 5 | Execute `run_job.py` | report HTML / `send-result.json` |
| 6 | Review result and optional auth automation | Final delivery decision |
| 7 | Save reusable job (optional) | `.wechat-bid-digest/jobs/*.yaml` |
| 8 | Completion summary | User-facing summary in 中文 |

### Step 2: Numbered Option Rules

Always use numbered options for constrained choices. Do not ask open-ended preference questions when a finite list exists.

**User-facing template**:

```text
请选择输出方式：
1. 邮件报告（推荐）：生成 HTML 报告，可发送/保存/转发
2. 控制台查看：直接在终端显示结果，不发送邮件

直接回复 1 或 2。
```

Common user-facing options:
- 输出方式：`1. 邮件报告（推荐）` / `2. 控制台查看`
- 偏好模式：`1. 快速推荐（推荐）` / `2. 自定义偏好`
- 时间范围：`最近 1 / 3 / 7 / 14 天`
- 信息类型：`招标 + 中标 / 仅招标 / 仅中标`
- 字段范围：`核心 / 全字段 / 极简`
- 邮件布局：`hybrid / table / card`
- 保存 job：`保存 / 不保存`

### Step 4: Preflight Rules ⛔ BLOCKING

#### Email Mode

Email mode is blocking on diagnostics:
- 邮件模式必须先运行 --doctor
- Continue only when `auth.ready=true` and `smtp.ready=true`
- Read `smtp.use_default_config`, `smtp.default_env_path`, `smtp.default_env_exists`, `smtp.missing_fields`, `smtp.source`

#### Login Mode

The QR flow is fixed:
- Generate `.wechat-bid-digest/auth/qrcode.png` first
- Render the same QR in the terminal
- Tell the user the QR image path in Chinese
- Do not try alternative QR display strategies

#### Long-Running Fetches

If fetching takes time:
- Prefer business-level JSON progress events such as `resolve_accounts_started`, `list_articles_completed`, `download_article_started`, `parse_started`, `render_started`
- Do not default to `ps`, `lsof`, `sample`, or other system-level debugging unless the user explicitly asks for low-level diagnostics

### Step 5: Pipeline Commands

Console mode example:

```bash
python3 "{baseDir}/scripts/run_job.py" \
  --accounts "七小服,天下观查,银标Daily,A信创圈俱乐部" \
  --keywords "信创,国产化,自主可控,操作系统,数据库,中间件,云平台,服务器,存储,网络设备" \
  --categories "tender,award" \
  --window-days 3
```

Email mode example:

```bash
python3 "{baseDir}/scripts/run_job.py" \
  --accounts "七小服,天下观查,银标Daily,A信创圈俱乐部" \
  --keywords "信创,国产化,自主可控,操作系统,数据库,中间件,云平台,服务器,存储,网络设备" \
  --categories "tender,award" \
  --window-days 3 \
  --layout hybrid \
  --to "user@example.com"
```

### Step 6: Optional Auth Automation

Only after `email_sent` succeeds, offer auth health automation:

```text
邮件已发送成功。

是否开启授权巡检自动化？
1. 开启授权巡检（推荐）：定期检查微信授权状态，异常时企业微信提醒
2. 暂不配置：本次不设置巡检自动化

直接回复 1 或 2。
```

If the user enables it, ask frequency with numbered options:
- `每 3 小时（推荐）`
- `每 6 小时`
- `每天一次`

Use [$wechat-tender-auth](/Users/lmj/Documents/ai-projects/skill-creator-wechatBid/.agents/skills/wechat-tender-auth/SKILL.md) for the health-check workflow.

## First-Time Setup

Read [first-time-setup.md](./config/first-time-setup.md) when:
- auth is missing
- the user wants email delivery
- the user asks how to configure SMTP / EXTEND.md / default job

Read [preferences-schema.md](./config/preferences-schema.md) when:
- editing `EXTEND.md`
- explaining `smtp_use_default_config`
- mapping CLI behavior to persistent preferences

## References

- [preferences-schema.md](./config/preferences-schema.md) - Preference schema and SMTP defaults
- [first-time-setup.md](./config/first-time-setup.md) - Setup guide
- [auth-management.md](./references/auth-management.md) - Auth lifecycle and renewal
- [presets.md](./references/presets.md) - Preset definitions
- [yaml-config.md](./references/yaml-config.md) - Job YAML format
- [output-format.md](./references/output-format.md) - Output directory contract

## Notes

- Keep user-facing interaction in 中文.
- Keep internal structure and execution rules in English by default.
- Prefer tables, fixed sections, and blocking rules over long prose.
- Do not send email without explicit recipients.
- Do not invent alternate flows when `--doctor` / `--login` / numbered options already define the expected path.
