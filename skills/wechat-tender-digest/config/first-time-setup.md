---
name: first-time-setup
description: Project-local setup guide for auth, SMTP, and first run
---

# First-Time Setup

## Language Rule

- Agent-facing setup notes may stay in English.
- All user-facing explanations and confirmations should remain in 中文.

## Prerequisites

- Python 3.9+
- `requests` 库（`pip install requests`）
- `qrcode` + `Pillow`（可选，用于终端显示二维码）

```bash
pip install requests qrcode Pillow
```

## Step 1: QR Login

Run the login command:

```bash
python3 "{baseDir}/scripts/run_job.py" --login
```

- The script always writes `.wechat-bid-digest/auth/qrcode.png` first.
- The script then renders the same QR in the terminal.
- user-facing 提示请用中文告知二维码路径，并提示用户扫码确认。
- Auth state is saved to `.wechat-bid-digest/auth/state.json`.
- Auth usually expires in about 4 hours and must be refreshed with another QR login.

## Step 2: Configure SMTP (Optional, Email Only)

Preferred project-local options:

1. Use `.wechat-bid-digest/smtp-default.env` for the default sender mailbox.
2. Or set SMTP fields in `.wechat-bid-digest/EXTEND.md`.
3. Or use environment variables / `.env`.

Example EXTEND.md:

```markdown
# User Preferences

## SMTP
- smtp_host: smtp.163.com
- smtp_port: 465
- smtp_username: your@163.com
- smtp_password: your_app_password
- smtp_from: your@163.com
```

## Step 3: Run Diagnostics

```bash
python3 "{baseDir}/scripts/run_job.py" --doctor
```

Check:
- `auth.ready = true`
- `smtp.ready = true`
- `smtp.connection.healthy = true` when email delivery is needed

`--doctor` is the required preflight for email mode.

## Step 4: First Run

```bash
# 仅获取和解析（不发邮件）
python3 "{baseDir}/scripts/run_job.py" --accounts "七小服" --until parse

# 完整流程（含邮件发送）
python3 "{baseDir}/scripts/run_job.py" --accounts "七小服" --to "user@example.com"
```

## Troubleshooting

### QR code not visible
安装 `qrcode` 和 `Pillow`：`pip install qrcode Pillow`。
即使终端渲染失败，`.wechat-bid-digest/auth/qrcode.png` 也会保留，可直接扫码。

### Auth expires frequently
WeChat MP 认证有效期较短（约 4 小时）。建议在需要时运行 `--login` 重新扫码。

### SMTP send failure
1. 确认 SMTP 配置正确（运行 `--doctor` 检查）
2. 163 邮箱需要开启「授权码」而非使用登录密码
3. QQ 邮箱需要在设置中开启 SMTP 服务
