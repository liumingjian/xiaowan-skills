---
name: output-format
description: wechat-tender-digest 输出目录结构与文件格式说明
---

# 输出格式

实际运行输出到 `<root_dir>/<job.name>/<YYYY-MM-DD>/`。

默认 `root_dir` 为当前工作目录下的 `wechat-bid-digest/`（可用环境变量 `WECHAT_BID_OUTPUT_DIR` 覆盖）。

## 目录结构

```
wechat-bid-digest/qixiaofu-daily/2026-03-12/
├── raw/
│   ├── summary.json          # 抓取汇总（公众号、文章数、错误数）
│   └── <account>/
│       └── <title>.json      # 单篇原始文章（含 HTML 和纯文本）
├── parsed/
│   └── records.json          # 解析后的招中标记录列表
├── <report>.html             # HTML 邮件报告
└── send-result.json          # 发送结果（含事件类型和邮件 ID）
```

## JSON 事件类型

`send-result.json` 中的 `event` 字段可能值：

| event | 含义 |
|-------|------|
| `fetch_completed` | 仅完成抓取阶段 |
| `parse_completed` | 仅完成解析阶段 |
| `render_completed` | 仅完成渲染阶段 |
| `no_matching_records` | 无匹配记录，跳过发送 |
| `send_skipped` | 邮件发送被禁用 |
| `email_sent` | 邮件发送成功 |
| `smtp_failed` | SMTP 发送失败（报告已保存） |

## 错误事件

stderr 输出的错误 JSON 中 `event` 字段：

| event | 含义 |
|-------|------|
| `auth_unhealthy` | 无法连接到微信接口（网络或平台异常） |
| `auth_expired` | 登录已过期，需要重新扫码 |
| `auth_unknown` | 认证状态未知（接口返回非预期） |
| `fetch_failed` | 文章抓取失败 |
| `runtime_invalid` | 参数或配置错误 |
| `runtime_failed` | 未预期的运行时错误 |
