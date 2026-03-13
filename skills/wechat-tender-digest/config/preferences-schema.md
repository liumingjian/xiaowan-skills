---
name: preferences-schema
description: EXTEND.md 偏好字段的完整文档
---

# EXTEND.md Preferences Schema

EXTEND.md 文件使用 Markdown 列表格式存储用户偏好。

## 文件位置

唯一配置文件位置：`.wechat-bid-digest/EXTEND.md`（当前工作目录下）

环境变量始终优先于 EXTEND.md 中的值。

## 格式

```markdown
# User Preferences

## SMTP
- smtp_host: smtp.163.com
- smtp_port: 465
- smtp_username: user@163.com
- smtp_password: your_app_password
- smtp_from: user@163.com

## Defaults
- default_accounts: 七小服, 天下观查, 银标Daily, A信创圈俱乐部
- default_keywords: 信创, 国产化, 自主可控, 操作系统, 数据库
- default_layout: hybrid
- default_window_days: 3
```

## SMTP 字段

| 字段 | 环境变量覆盖 | 说明 | 示例 |
|------|-------------|------|------|
| `smtp_host` | `SMTP_HOST` | SMTP 服务器地址 | `smtp.163.com` |
| `smtp_port` | `SMTP_PORT` | SMTP 端口 | `465` |
| `smtp_username` | `SMTP_USERNAME` | 登录用户名 | `user@163.com` |
| `smtp_password` | `SMTP_PASSWORD` | 登录密码或授权码 | `your_app_password` |
| `smtp_from` | `SMTP_FROM` | 发件人地址（默认同 username） | `user@163.com` |
| `smtp_ssl` | `SMTP_SSL` | 是否使用 SSL（默认 true） | `true` |
| `smtp_starttls` | `SMTP_STARTTLS` | 是否使用 STARTTLS | `false` |
| `smtp_use_default_config` | `SMTP_USE_DEFAULT_CONFIG` | 是否尝试读取“默认 SMTP 配置文件”（默认 true） | `false` |
| `smtp_default_env_path` | `SMTP_DEFAULT_ENV_PATH` | 默认 SMTP 配置文件路径（KEY=VALUE 格式） | `.wechat-bid-digest/smtp-default.env` |

### 默认 SMTP 配置文件（内部场景）

当 `smtp_use_default_config=true` 时，脚本会优先尝试读取默认配置文件（不覆盖已存在的环境变量），用于内部“开箱即用”的发件箱设置。

默认路径：
`.wechat-bid-digest/smtp-default.env`

示例（请自行替换为你的账号信息，并确保文件权限为 600）：

```env
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_SECURE=true
SMTP_USER=your_sender@163.com
SMTP_PASS=your_app_password
SMTP_FROM=your_sender@163.com
SMTP_CONNECTION_TIMEOUT_MS=10000
SMTP_GREETING_TIMEOUT_MS=10000
SMTP_SOCKET_TIMEOUT_MS=15000
```

推广/公开发布建议：
- 在 EXTEND.md 中设置 `smtp_use_default_config: false`
- 并移除/不分发上述默认配置文件

## Default 字段

| 字段 | 说明 | 示例 |
|------|------|------|
| `default_accounts` | 默认公众号列表（逗号分隔） | `七小服, 天下观查` |
| `default_keywords` | 默认关键词（逗号分隔） | `信创, 国产化, 数据库` |
| `default_layout` | 默认邮件布局 | `hybrid` / `table` / `card` |
| `default_window_days` | 默认回溯天数 | `3` |

## 企业微信（WeCom）提醒字段

用于“授权巡检”场景：当微信 MP 授权失效或不可达时，通过企业微信机器人 Webhook 推送提醒。

| 字段 | 环境变量覆盖 | 说明 | 示例 |
|------|-------------|------|------|
| `wechat_work_webhook` | `WECHAT_WORK_WEBHOOK` | 企业微信机器人 Webhook URL | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...` |
| `wechat_work_action_url` | `WECHAT_WORK_ACTION_URL` | 提醒消息中的处理链接（手机端可点击打开） | `https://example.com/runbook/wechat-login` |
| `wechat_work_mentioned_list` | `WECHAT_WORK_MENTIONED_LIST` | 需要 @ 的成员 userId 列表（逗号分隔，可用 `@all`） | `@all` |
| `wechat_work_mentioned_mobile_list` | `WECHAT_WORK_MENTIONED_MOBILE_LIST` | 需要 @ 的手机号列表（逗号分隔） | `13800000000` |
| `wechat_work_notify_cooldown_seconds` | `WECHAT_WORK_NOTIFY_COOLDOWN_SECONDS` | 提醒冷却时间（秒）。当授权持续异常时，至少间隔该秒数才会再次推送 | `21600` |
| `wechat_work_escalate_after_seconds` | `WECHAT_WORK_ESCALATE_AFTER_SECONDS` | 异常持续超过该秒数后，在提醒内容中标记为“已持续较长时间未恢复” | `86400` |

### 关于 `wechat_work_action_url`（手机可点开）

- 这个链接必须是手机可以访问的 `http(s)` 地址。
- 当前实现会在发送提醒前校验该链接是否可达，并把结果写入巡检输出与提醒消息。
- **它不需要指向你的本机**：即使你的电脑没有公网 IP，也可以把它配置为一个公网可访问的操作说明页。
- **它不是本机扫码续期深链**：点击后不会直接在手机上触发本地 `--login`；真正续期仍需回到当前电脑执行扫码登录。
- 推荐做法：
  - 直接用 Codex Automations 页面作为入口：`https://developers.openai.com/codex/app/automations`
  - 或指向你们内部 Wiki/Runbook（手机可访问）
- 如果你希望手机直接打开本机报告/页面：需要手机与电脑在同一局域网或同一 VPN（如 Tailscale），并由你自行暴露一个可访问的地址（本项目不内置公网隧道或独立 Web 服务）。

## 手机端直完续期（Spike）字段

用于实验性的“手机点链接完成续期”链路：

`企业微信提醒 -> 手机点一次性链接 -> 手机页显示二维码 -> 手机在微信中确认登录 -> 本机 token 刷新`

该模式需要：
- 公网入口：Cloudflare Worker + KV（仅存短时请求状态，不存长期 token/cookies）
- 本机常驻：`mobile_renewal_agent.py` 负责生成二维码、等待确认、刷新本地 `state.json`

| 字段 | 环境变量覆盖 | 说明 | 示例 |
|------|-------------|------|------|
| `mobile_renewal_mode` | `MOBILE_RENEWAL_MODE` | `off` / `spike`（默认 `off`） | `spike` |
| `mobile_renewal_worker_url` | `MOBILE_RENEWAL_WORKER_URL` | Worker base URL（手机端可访问） | `https://<your-worker>.workers.dev` |
| `mobile_renewal_host_id` | `MOBILE_RENEWAL_HOST_ID` | Host 标识（用于 Worker 队列匹配） | `host-1` |
| `mobile_renewal_shared_secret` | `MOBILE_RENEWAL_SHARED_SECRET` | Worker API 共享密钥（不要写入代码仓库） | `...` |
| `mobile_renewal_request_ttl_seconds` | `MOBILE_RENEWAL_REQUEST_TTL_SECONDS` | 一次性链接有效期（秒，默认 600） | `600` |

说明：
- `mobile_renewal_mode=spike` 时，`$wechat-tender-auth --notify` 会优先生成动态一次性链接，此时 **不再强依赖** `wechat_work_action_url`。
- 该模式是可行性验证阶段，不承诺在所有手机/环境下都能稳定完成续期。

## 注意事项

- 所有字段均为可选，未配置时使用内置默认值
- SMTP 字段如缺少必要项（host/username/password），发送邮件时会报错并提示配置
- 环境变量优先级最高，适合 CI/CD 或容器环境
- 企业微信提醒字段仅在你启用巡检并使用 `--notify` 时才会强校验；缺失必要字段会明确报错提示补齐
