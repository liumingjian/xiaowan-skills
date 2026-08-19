---
name: delegate-to-cc
description: 把当前仓库的疑难问题或品味判断委托给 vps-2g 上的 Claude Code，在远端临时副本中分析或实现，并将结论或补丁带回本地。
---

# Delegate to CC

把 Claude 当作二审，不当作最终裁决。Codex 负责准备可复现的上下文、审查 Claude 的结论或补丁，并在本地完成验证。

## 1. 选择模式

- `consult`：用于架构取舍、疑难诊断、UI / 文案 / 命名等品味判断。Claude 只能读取远端副本；这是默认模式。
- `implement`：用于用户明确要 Claude 给出可应用实现的任务。Claude 可以编辑远端副本，但不能执行 shell；测试仍由 Codex 在本地运行。

完成标准：在执行前明确选定一种模式，并能用一句话说明需要 Claude 裁决或完成什么。

## 2. 写交接单

创建一个临时 Markdown 文件，依次写入：

1. **Objective**：一个可判定完成与否的目标。
2. **Why delegated**：Codex 卡住的位置、已经排除的方向，或需要独立品味判断的原因。
3. **Evidence**：原样保留的错误、失败命令或可观察现象。
4. **Relevant paths**：Claude 应优先读取的相对路径。
5. **Constraints**：兼容性、范围、不可改变的行为和用户偏好。
6. **Deliverable**：要求明确推荐与备选，或要求直接修改远端副本。

交接单只写任务事实，不粘贴仓库文件；脚本会传输仓库快照。未知信息标为未知，不用猜测补齐。

完成标准：Claude 不需要读取本次 Codex 对话，也能从交接单和仓库中重建问题。

## 3. 审核传输边界

在当前仓库根目录运行。脚本默认只传输 Git tracked 文件的当前内容，因此会包含 tracked 的本地修改，但不会包含 `.git`、ignored 文件或 untracked 文件。

若相关实现只存在于 untracked 文件中，先运行 `git ls-files --others --exclude-standard`，逐项确认没有凭据、密钥、私有数据或无关构建产物，再使用 `--include-untracked`。始终以脱敏后的现象代替凭据内容。

完成标准：任务所需文件都在快照中，且传输清单不包含秘密或无关数据。

## 4. 执行远端二审

确认本地存在 `git`、`ssh`、`scp` 和支持 NUL 清单的 `tar`，SSH 别名 `vps-2g` 可用；服务器需提供 Bash、Git、tar、GNU `timeout` 和已登录的 Claude Code。

将包含本 `SKILL.md` 的目录记为 `SKILL_DIR`，保持工作目录在目标仓库，然后运行：

```bash
"$SKILL_DIR/scripts/delegate.sh" \
  --mode consult \
  --prompt-file /absolute/path/to/handoff.md
```

实现型任务将模式改为 `implement`。仅在已完成上一节审核时追加 `--include-untracked`。需要指定 Claude 模型时追加 `--model <alias-or-model-id>`；否则沿用服务器默认值。Claude 默认最多运行 900 秒；确有需要时用 `--timeout-seconds <1-86400>` 调整。

脚本通过 SSH 别名 `vps-2g` 连接服务器，在 `/tmp` 创建临时仓库，完成后回收远端目录。它输出以下本地文件路径：

- `response.md`：Claude 的结论和说明。
- `changes.patch`：相对传输快照的完整 Git patch；`consult` 模式通常为空。
- `claude.stderr`：CLI 诊断信息。
- `status`：Claude CLI 的退出码。

完成标准：`status` 为 `0`，`response.md` 非空；实现型任务还要确认 `changes.patch` 与目标一致。

## 5. 本地裁决

读取 Claude 的答复和完整补丁，再回到本地仓库事实逐项核对：

- 对 `consult`：比较推荐、备选和证据，明确说明 Codex 接受或拒绝了哪些判断。
- 对 `implement`：先运行 `git apply --check <changes.patch>` 作为可应用性预检，再逐个 hunk 审查；只用宿主 agent 的正常编辑机制落下已接受的修改。
- 对所有模式：运行与改动风险相称的本地测试、类型检查或视觉验证。Claude 没有执行 shell，不能把它声称的测试结果当作证据。

补丁冲突时，以当前本地工作区为准，重新整合需要的 hunk；不要覆盖用户在委托期间产生的修改。

完成标准：每个采纳的判断都有仓库证据，每个采纳的改动都经过本地验证；最终答复区分 Claude 的建议、Codex 的裁决和实测结果。
