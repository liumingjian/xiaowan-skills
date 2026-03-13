---
name: yaml-config
description: wechat-tender-digest YAML 任务配置约定与字段说明
---

# YAML 配置约定

任务配置使用受限 YAML 子集：

- 支持字典、标量、标量列表
- 缩进固定为 2 个空格
- 不支持注释、锚点、复杂对象列表
- 字符串如包含 `:`，请使用引号

## 必填块

### `job`

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 任务标识符 |
| `description` | string | 用于邮件标题和报告头 |
| `window_days` | int | 默认回溯天数 |

### `source`

| 字段 | 类型 | 说明 |
|------|------|------|
| `accounts` | list[string] | 公众号名称列表 |
| `limit_per_account` | int | 每个公众号最多抓取篇数 |

> 说明：旧版本 YAML 中的 `gateway_mode/base_url/...` 等网关字段仍可存在，但会被忽略并打印 deprecation 警告。

### `filters`

| 字段 | 类型 | 说明 |
|------|------|------|
| `keywords` | list[string] | 项目名匹配关键词 |
| `categories` | list[string] | 允许的分类（`招标`/`中标`） |
| `sort_by` | `publish_date_desc`/`publish_date_asc` | 排序方式 |

### `output`

| 字段 | 类型 | 说明 |
|------|------|------|
| `root_dir` | string | 输出根目录（实际运行输出到 `<root_dir>/<job.name>/<YYYY-MM-DD>/`） |
| `keep_raw` | bool | 保留原始 JSON |
| `keep_parsed` | bool | 保留解析结果 |
| `keep_report` | bool | 保留 HTML 报告 |
| `report_filename` | string | HTML 文件名 |

### `email`

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | bool | 是否发送邮件 |
| `send_on_empty` | bool | 无结果时是否发送 |
| `layout` | `table`/`hybrid`/`card` | 邮件正文布局 |
| `subject` | string | 邮件主题 |
| `to` | list[string] | 收件人列表 |
| `visible_fields` | list[string] (可选) | 显示哪些字段 |

#### `visible_fields` 可用值

`project_id`, `project_name`, `amount`, `procurer`, `winner`, `publish_date`, `deadline`, `source_name`, `source_url`

省略则显示全部字段。

## 示例

参考 [qixiaofu-daily.yaml](../jobs/qixiaofu-daily.yaml)
