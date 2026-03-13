---
name: first-time-setup
description: 自包含模式的首次设置指南
---

# 首次设置指南

## 前提条件

- Python 3.9+
- `requests` 库（`pip install requests`）
- `qrcode` + `Pillow`（可选，用于终端显示二维码）

```bash
pip install requests qrcode Pillow
```

## 步骤 1: 扫码登录

运行登录命令，使用微信扫描二维码：

```bash
python3 "{baseDir}/scripts/run_job.py" --login
```

- 默认直接在终端显示二维码
- 仅在当前环境无法终端渲染时，才会额外保存 `~/.wechat-bid-digest/auth/qrcode.png`
- 使用微信扫码并确认登录
- 认证信息保存在 `~/.wechat-bid-digest/auth/state.json`
- 认证有效期约 4 小时，过期后需重新扫码

## 步骤 2: 配置 SMTP（可选，仅发邮件需要）

创建 `~/.wechat-bid-digest/EXTEND.md`：

```markdown
# User Preferences

## SMTP
- smtp_host: smtp.163.com
- smtp_port: 465
- smtp_username: your@163.com
- smtp_password: your_app_password
- smtp_from: your@163.com
```

或者使用环境变量 / `.env` 文件配置。

## 步骤 3: 运行诊断

```bash
python3 "{baseDir}/scripts/run_job.py" --doctor
```

检查输出确认：
- `auth.status` = `valid`（认证有效）
- `smtp.healthy` = `true`（SMTP 可用，仅当需要发邮件时）

## 步骤 4: 首次运行

```bash
# 仅获取和解析（不发邮件）
python3 "{baseDir}/scripts/run_job.py" --accounts "七小服" --until parse

# 完整流程（含邮件发送）
python3 "{baseDir}/scripts/run_job.py" --accounts "七小服" --to "user@example.com"
```

## 常见问题

### 二维码无法显示
安装 `qrcode` 和 `Pillow`：`pip install qrcode Pillow`。
如果当前环境仍无法终端渲染，脚本会明确提示并保存 `~/.wechat-bid-digest/auth/qrcode.png` 供手动扫码。

### 认证频繁过期
WeChat MP 认证有效期较短（约 4 小时）。建议在需要时运行 `--login` 重新扫码。

### SMTP 发送失败
1. 确认 SMTP 配置正确（运行 `--doctor` 检查）
2. 163 邮箱需要开启「授权码」而非使用登录密码
3. QQ 邮箱需要在设置中开启 SMTP 服务
