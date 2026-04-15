# xiaowan-skills

一组面向 Codex 工作流的实用 Skills，聚焦微信公众号招投标信息抓取、邮件摘要和微信授权巡检。

## Installation

### Option 1: Clone this repository

```bash
git clone https://github.com/liumingjian/xiaowan-skills.git
```

### Option 2: Copy selected skills into Codex

将需要的 skill 目录复制到你的 Codex skills 目录中：

```bash
mkdir -p ~/.codex/skills
cp -R skills/wechat-tender-digest ~/.codex/skills/
cp -R skills/wechat-tender-auth ~/.codex/skills/
```

如果你只想在当前项目中使用，也可以复制到项目级 `.codex/skills/`。

## Available Skills

| Skill | Description | Main Use Cases |
|------|-------------|----------------|
| `wechat-tender-digest` | 从微信公众号文章中提取招标/中标/采购信息，生成 HTML 报告并可邮件发送 | 招标监控、日报订阅、关键词过滤、邮件摘要 |
| `wechat-tender-auth` | 定时检查微信 MP 授权状态，并在异常时通过企业微信机器人发送提醒 | 自动巡检、授权失效提醒、Codex automation 配套 |

## Quick Start

### wechat-tender-digest

首次登录微信：

```bash
python3 "{baseDir}/scripts/run_job.py" --login
```

运行一次摘要任务：

```bash
python3 "{baseDir}/scripts/run_job.py" --job "{baseDir}/config/jobs/default.job.yaml"
```

### wechat-tender-auth

执行一次授权健康检查：

```bash
python3 "{baseDir}/scripts/run_check.py"
```

异常时推送企业微信提醒：

```bash
python3 "{baseDir}/scripts/run_check.py" --notify
```

## Repository Structure

```text
xiaowan-skills/
├── README.md
└── skills/
    ├── wechat-tender-auth/
    └── wechat-tender-digest/
```

每个 skill 目录都保持自包含结构，包含：

- `SKILL.md`: 触发描述与使用说明
- `agents/openai.yaml`: UI 元信息
- `scripts/`: 可执行脚本
- `config/` / `references/`: 配置说明与参考资料
- `tests/`: 回归测试

## Notes

- `wechat-tender-digest` 默认输出目录为当前工作目录下的 `wechat-bid-digest/`
- 微信扫码授权通常约 4 小时有效，建议邮件推送场景搭配 `wechat-tender-auth` 做定时巡检
- 企业微信提醒采用机器人 Webhook；仓库中只保留占位示例，不包含真实密钥
