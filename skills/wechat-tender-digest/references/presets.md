---
name: presets
description: wechat-tender-digest 预设定义与使用说明
---

# 预设 (Presets)

预设包含预定义的关键词、分类和布局配置，让你一句话启动任务。

预设 **不包含** 公众号名称和收件人——这些来自 `--accounts` 和 `--to` 参数。

## 可用预设

### `xinc` (别名: `it-xinc`) — 信创招标

- **关键词**: 信创, 国产化, 自主可控, 操作系统, 数据库, 中间件, 云平台
- **分类**: 招标, 中标
- **布局**: hybrid
- **回溯**: 3 天

### `hardware` (别名: `hardware-device`) — 硬件维保

- **关键词**: 维保, 服务器, 存储, 网络设备, UPS, 硬件, 机房
- **分类**: 招标, 中标
- **布局**: table
- **回溯**: 3 天

### `software` (别名: `software-purchase`) — 软件采购

- **关键词**: 软件, 许可, License, OA, ERP, CRM, 办公软件
- **分类**: 招标, 中标
- **布局**: table
- **回溯**: 3 天

### `engineering` — 工程基建

- **关键词**: 工程, 施工, 基建, 装修, 弱电, 综合布线
- **分类**: 招标, 中标
- **布局**: hybrid
- **回溯**: 5 天

## 使用方式

### 直接运行

```bash
python3 "{baseDir}/scripts/run_job.py" --preset xinc --accounts "七小服" --to "user@example.com"
```

### 创建持久化配置

```bash
python3 "{baseDir}/scripts/run_job.py" --create-job --preset xinc --accounts "七小服" --to "user@example.com"
```

### 仅解析不发送

```bash
python3 "{baseDir}/scripts/run_job.py" --preset hardware --accounts "七小服" --until render
```

### 覆盖布局

```bash
python3 "{baseDir}/scripts/run_job.py" --preset xinc --accounts "七小服" --to "user@example.com" --layout card
```
