---
name: auth-management
description: Auth token 生命周期、重登录方式、故障排查
---

# 认证管理

## Auth Token 生命周期

```
扫码登录 → AuthState 写入 state.json → 有效期约 4h → 过期 → 重新扫码
```

### 状态文件

位置：`~/.wechat-bid-digest/auth/state.json`

```json
{
  "cookies": {"slave_sid": "...", "slave_user": "..."},
  "token": "123456",
  "login_time": "2026-03-12T10:00:00",
  "expires_at": "2026-03-12T14:00:00"
}
```

权限：`0600`（仅所有者可读写）

### 状态检查

```bash
python3 "{baseDir}/scripts/run_job.py" --doctor
```

输出的 `auth` 字段显示当前认证状态：
- `valid` — 认证有效
- `expired` — 已过期，需重新扫码
- `not_logged_in` — 尚未登录

## 重新登录

```bash
python3 "{baseDir}/scripts/run_job.py" --login
```

1. 默认在终端显示二维码
2. 使用微信扫码
3. 手机确认登录
4. `state.json` 自动更新

如果当前环境无法终端渲染二维码，脚本会明确提示并额外保存 `~/.wechat-bid-digest/auth/qrcode.png`。

## 故障排查

### 扫码超时

```
错误: 扫码超时（120秒），请重试
```

原因：120 秒内未完成扫码+确认。重新运行 `--login`。

### 登录失败

```
错误: 登录失败，无法获取 token
```

可能原因：
1. 微信帐号未绑定公众号管理权限
2. 网络问题导致回调失败
3. 微信 MP 接口临时异常

### Auth 过期后运行任务

任务脚本会自动检测 auth 过期并触发重新登录流程。
如果在非交互环境（如 cron）运行，建议提前手动 `--login`。

## 授权巡检自动化（推荐）

如果你使用“邮件推送”，推荐用 Codex automation 定时运行 `$wechat-tender-auth` 做健康检查：

- `healthy`：记录检查结果
- `expired/unreachable`：通过企业微信机器人 Webhook 推送提醒（提醒式，不承诺无人值守续期成功）

企业微信配置见 `preferences-schema.md` 中的 `wechat_work_*` 字段。

关于提醒里的“处理链接”（`wechat_work_action_url`）：
- 该链接需要手机可打开，因此必须是手机可访问的 `http(s)` 地址
- 你的电脑没有公网 IP 也不影响：建议直接配置为 Codex Automations 页面或你们内部 runbook 链接
- 当前实现会在发送提醒前校验该链接是否可达，并在提醒内容里显示校验结果
- 该链接只是“处理入口”，不是直接触发本机扫码续期的深链；真正续期仍需回到当前电脑运行 `--login`

## 手机端直完续期（Spike，可行性验证）

如果你希望“手机点企业微信消息里的链接后就能完成续期”，可以启用实验性的 spike 模式：

1. 部署 Cloudflare Worker（公网中继，一次性短链 + KV 状态机）
2. 在本机常驻运行 `mobile_renewal_agent.py`（生成二维码、等待确认、刷新本地 token）
3. `$wechat-tender-auth --notify` 在异常时生成动态一次性链接并推送到企业微信

该模式需要在 EXTEND.md 配置 `mobile_renewal_*` 字段（见 `preferences-schema.md`），并确保本机代理在线。

注意：
- spike 模式仍需要你在手机微信中扫码/识别二维码并确认登录（平台限制）。
- 本功能处于可行性验证阶段，不承诺在所有机型/网络环境下稳定可用；验证结论以真实设备测试为准。

## 守护进程模式（可选）

如需后台定期检测 token 是否可用，可运行：

```bash
python3 "{baseDir}/scripts/run_job.py" --auth-daemon --auth-check-interval-seconds 600
```

说明：当认证真正失效时仍可能需要你重新扫码确认登录，这是 WeChat MP 的限制。

### 频繁要求重新登录

WeChat MP 的会话有效期约 4 小时。这是平台限制，无法延长。
建议在使用前运行 `--login` 确保认证有效。
