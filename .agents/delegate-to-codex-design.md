# delegate-to-codex — 设计稿

`delegate-to-cc` 的镜像：那个是 Codex 把活派给 vps 上的 Claude Code，这个是 Claude Code 把活派给用户 macOS 本机的 Codex CLI。

## 已确认的环境事实

- 服务器在 NAT 外，**无法主动连到 Mac**。唯一通路是 rexec：Mac 上常驻 agent 轮询拉取。本 skill 不自建通路，全部经由 `rexec`。
- Mac 身份 = `<ComputerName 前12位>-<硬件UUID哈希4位>`，与 IP 无关；路由靠"本 session SSH 源 IP 最近 announce 的 mac"，每次 poll 重写 origin。同 NAT 下多台 → `AMBIGUOUS`，用 `--mac <前缀>` 指定。已注册：`lmj-mac-mini-269d`、`lmj-macbook--2e94`。
- Mac 上 `codex-cli 0.150.1`，路径 `/Users/lmj/.local/bin/codex`。有 `codex exec`（`-s/--sandbox`、`--approve-for-me`、`--dangerously-bypass-approvals-and-sandbox`、`-C/--cd`、`--skip-git-repo-check`、`--json`、`-o`、`resume`/`fork`）与 `codex exec review`（`--uncommitted`/`--base`/`--commit`）。**无 `--full-auto`**。
- rexec 同步：`rsync -az --delete --exclude '.git/' ... --filter=':- .gitignore'`（`agent.sh:116-120`）。因此 **Mac 工作区不是 git 仓库**，且**被 gitignore 的文件不同步**。但 `--exclude` 的路径在接收端受保护、不被 `--delete` 删除，所以在工作区本地 `git init` 出的 `.git` 可长期存活。
- 工作区路径：`~/rexec-workspace/<dirname>-<pathhash>/`。产物不回传，只有 stdout 回来。

## 设计决策

1. **通路**：薄封装，实质是 `rexec 'codex exec ...'`。队列/取消/超时/身份识别全部白嫖，不向用户暴露。
2. **目标 Mac**：默认跟随 session 源；先探测 `codex --version`，缺失或未认证则**直接报错**并提示用 `--mac <prefix>` 换机器，不静默改道。
3. **git 与 patch 回传**：跑 codex 前在 Mac 工作区做幂等 baseline（`git init -q` + `git add -A` + `git commit --allow-empty`），跑完 `git add -A && git diff HEAD` 出 patch。**不改 rexec**；`--with-git` 作为独立的后续改动，不与本 skill 绑定。
4. **模式**（沿用 delegate-to-cc 词汇）：
   - `consult`（默认）— `-s read-only`，出建议报告，patch 必须为空。
   - `implement` — `-s workspace-write`（无网络），出 patch。
   `--dangerously-bypass-approvals-and-sandbox` 仅在用户显式要求时使用。
5. **依赖与验证**：沙箱无网络，依赖必须**事先**用 `/rexec` 装好。codex 在 `implement` 下可跑命令（帮助它自我收敛），但**其测试主张不作为证据**；最终 pass/fail 以 patch 回服务器后用 `/rexec` 重跑为准。职责：**rexec 管跑，codex 管想和写**。
6. **handoff**：六标题 Markdown（Objective / Why delegated / Evidence / Relevant paths / Constraints / Deliverable），落盘在项目根 `.codex-handoff-<ts>.md`，**跑前用 `git check-ignore` 确认它没被 gitignore 吞掉**，rexec 带过去，跑完两边删除。
7. **产物**：Mac 上生成 `response.md`、`changes.patch`，经 stdout `cat` 回服务器，落盘到 `.codex-out/<ts>/`（加入 `.gitignore`，避免再被同步回 Mac）。
8. **子智能体**：用通用子智能体（不配专用 agent 定义，保持跨 harness 可装），只带回**收据** ≤50 行：结论 + 问题清单 + 产物路径 + codex session id。
9. **会话续接**：收据里带 session id，用户可显式 `--resume <id>`；不自动记忆。
10. **落地**：子智能体**绝不 apply**。主线先 `git apply --check`，把 diff 给用户看，用户点头才 apply。
11. **发布**：`skills/in-progress/delegate-to-codex/`，`agents/openai.yaml` 设 `policy.allow_implicit_invocation: false`（会烧 codex 额度、会改 Mac 上的文件，必须显式调用）。同步更新根 `README.md` 与 `skills/in-progress/README.md`。
