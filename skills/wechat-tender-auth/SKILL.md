---
name: wechat-tender-auth
description: WeChat MP 授权健康检查（用于 Codex automation 定时巡检）并在异常时通过企业微信机器人 Webhook 推送提醒。
version: 1.0.0
---

# WeChat Tender Auth

用于“授权巡检 + 提醒式续期”场景：定时检查微信 MP 授权状态，发现 `expired/unreachable` 时发送企业微信提醒。

两种提醒入口：
1. 默认（reminder-only）：提醒里给一个公网可访问的处理入口（runbook/Codex 页面），续期仍需你回到电脑执行 `--login`
2. Spike（实验）：提醒里给一次性动态链接，手机打开后显示二维码，手机在微信确认后由本机常驻代理刷新 token

## Prerequisites

- Python 3.9+
- 依赖与主 skill 复用（`requests`）

## Script Directory

1. 以本 `SKILL.md` 所在目录为 `{baseDir}`
2. 脚本入口为 `{baseDir}/scripts/run_check.py`

## Options

| Option | Description |
|--------|-------------|
| `--notify` | 当状态不是 `healthy` 时，通过企业微信机器人 Webhook 推送提醒 |
| `--service-name` | 出现在输出与提醒里的服务名（默认：`微信授权巡检`） |

## Workflow

Auth Check Flow：
1. 读取偏好配置（EXTEND.md + 环境变量覆盖）
2. 调用微信 MP health 检查，输出 JSON（含 `auth.authStatus`）
3. 若使用 `--notify` 且状态为 `expired/unreachable`：按模式发送企业微信提醒
   - reminder-only：提醒里放静态处理入口（`wechat_work_action_url`）
   - spike：提醒里放一次性动态链接（手机打开显示二维码，本机常驻代理完成 token 刷新）

## One-shot Check

仅检查状态（不发企业微信提醒）：

```bash
python3 "{baseDir}/scripts/run_check.py"
```

输出为 JSON（stdout），包含 `auth.authStatus`:
- `healthy`
- `expired`
- `unreachable`

## Notify via WeCom (企业微信)

当状态非 `healthy` 时，发送企业微信机器人提醒：

```bash
python3 "{baseDir}/scripts/run_check.py" --notify
```

### 配置项（EXTEND.md）

### 默认模式（reminder-only）配置

在 `~/.wechat-bid-digest/EXTEND.md`（或项目级 `.wechat-bid-digest/EXTEND.md`）中添加：

```markdown
## WeCom
- wechat_work_webhook: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
- wechat_work_action_url: https://example.com/runbook/wechat-login
- wechat_work_mentioned_list: @all
```

说明：
- `wechat_work_action_url` 是提醒消息里的“处理链接”，**手机端会点击打开**，必须是手机能访问到的 `http(s)` 地址。
  - 当前实现会在发送提醒前校验该链接是否可达，并把校验结果写入输出与提醒内容。
  - 该链接是“处理入口”，不是“直接触发本机扫码续期”的深链；真正续期仍需你回到当前电脑运行 `wechat-tender-digest` 的 `--login`。
  - 推荐先用 Codex Automations 页面作为入口：`https://developers.openai.com/codex/app/automations`
  - 或指向你们内部 Wiki/Runbook（手机可访问）

可选（降低重复提醒频率）：
```markdown
- wechat_work_notify_cooldown_seconds: 21600
- wechat_work_escalate_after_seconds: 86400
```

### Spike（实验）：手机端直完续期

目标链路：
`企业微信提醒 -> 手机点一次性链接 -> 手机页显示二维码 -> 手机在微信中确认登录 -> 本机 token 刷新`

需要额外配置（见 `preferences-schema.md`）：

```markdown
## Mobile Renewal Spike
- mobile_renewal_mode: spike
- mobile_renewal_worker_url: https://<your-worker>.workers.dev
- mobile_renewal_host_id: host-1
- mobile_renewal_shared_secret: <same-as-worker-secret>
- mobile_renewal_request_ttl_seconds: 600
```

并在本机常驻运行续期代理（必需，否则手机端链接会一直等待直到过期）：

```bash
python3 ".agents/skills/wechat-tender-digest/scripts/mobile_renewal_agent.py"
```

#### 让续期代理“无感知”后台运行（macOS 推荐）

把续期代理托管为 `launchd` 的 LaunchAgent（开机/登录后自动运行，不需要打开一个终端窗口）。

1. 准备日志目录：
```bash
mkdir -p "$HOME/.wechat-bid-digest/logs"
```

2. 生成并写入 plist（自动填好绝对路径，不需要手工编辑）：
```bash
SCRIPT_PATH="$(python3 - <<'PY'
from pathlib import Path
print((Path.cwd()/".agents/skills/wechat-tender-digest/scripts/mobile_renewal_agent.py").resolve())
PY
)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.wechatbid.mobile-renewal-agent.plist"
mkdir -p "$(dirname "$PLIST_PATH")"
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.wechatbid.mobile-renewal-agent</string>

    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/python3</string>
      <string>${SCRIPT_PATH}</string>
      <string>--poll-interval-seconds</string>
      <string>5</string>
    </array>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>WorkingDirectory</key>
    <string>${HOME}</string>

    <key>StandardOutPath</key>
    <string>${HOME}/.wechat-bid-digest/logs/mobile-renewal-agent.out.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/.wechat-bid-digest/logs/mobile-renewal-agent.err.log</string>
  </dict>
</plist>
PLIST
echo "wrote: $PLIST_PATH"
```

3. 启用并立即启动：
```bash
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.wechatbid.mobile-renewal-agent.plist"
launchctl enable "gui/$(id -u)/com.wechatbid.mobile-renewal-agent"
launchctl kickstart -k "gui/$(id -u)/com.wechatbid.mobile-renewal-agent"
```

4. 验证与查看日志：
```bash
launchctl print "gui/$(id -u)/com.wechatbid.mobile-renewal-agent" | head
tail -f "$HOME/.wechat-bid-digest/logs/mobile-renewal-agent.out.log"
```

5. 停用/卸载：
```bash
launchctl disable "gui/$(id -u)/com.wechatbid.mobile-renewal-agent"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.wechatbid.mobile-renewal-agent.plist"
```

说明：
- spike 模式下，提醒消息会优先使用动态一次性链接，此时 **不再强依赖** `wechat_work_action_url`。
- 仍需你在手机微信中扫码/识别二维码并确认登录（平台限制）。

## Codex Automation（推荐）

在 Codex 的 Automations 中创建一个自动化任务，按以下频率之一定时运行本 skill：
- 每 3 小时（推荐）
- 每 6 小时
- 每天一次

自动化 prompt 示例（不包含调度信息）：

> 使用 `$wechat-tender-auth` 检查微信 MP 授权状态；若状态不是 healthy，则通过企业微信机器人 Webhook 推送提醒，并在 inbox 中保留本次检查结果。

### 修改调度时间

后续需要修改巡检频率时：
- 在 Codex 的 Automations 页面直接编辑该自动化的运行频率
- 或对 Codex 说“把微信授权巡检改成每 6 小时/每天一次”
