# 多设备多Agent系统架构评估报告

## 总体结论：高度可行，但需分阶段实施

这套架构设计在技术上是**完全可行**的，且契合 2026 年 VibeCoding 的工具生态。核心思路——用 `ductor` 做远程异步编排中枢、`Agent Deck` 做本地状态仪表盘、Tailscale 做零信任网络——这是当前最优解。

但设计中有几个**关键摩擦点**需要提前规避，否则会在实际运行中变成持续痛点。

---

## 一、架构优势（为什么这个设计 make sense）

### 1. 网络层：Tailscale 是最正确的选择
三设备（Android/Mac/Win）通过 TailNet 组网，避免了公网 IP、端口映射、防火墙穿透的所有麻烦。GitHub-hosted 的 Tailscale 团队计划也支持 ACL 规则，可以精确控制哪台设备能访问哪台。

- MacBook 作为 24/7 Agent Host，固定 Tailscale IP，Win 和 Android 随时可达
- Android 上 Tailscale 客户端 + Telegram，真正实现了「离开电脑也能监控项目」
- 即使你在咖啡厅用手机，也能通过 Tailscale IP 访问 Mac 上的 ductor WebSocket API

### 2. 编排层：ductor + Agent Deck 的组合填补了彼此的致命短板

| 单一工具 | 短板 | 组合后 |
|---------|------|-------|
| 只用 Agent Deck | 必须坐在电脑前；没有异步队列；没有移动端 | + ductor = 手机随时监控，AI 后台异步跑 |
| 只用 ductor | 没有本地 TUI 毫秒级状态看板；没有 MCP Socket Pooling | + Agent Deck = 本地秒级状态，多 Session 资源复用 |

ductor 的 Background tasks + Task priorities（interactive/background/batch）天然提供了 **60% 的 Queue 语义**，你只需要在上面叠加一个「时间优化大脑」。

### 3. 角色隔离：多 Hermes Agent 是正确方向
CTO / Engineer Director / Data Director / Marketing Director / Review Director 这种角色划分，本质上是**多 Agent 协作架构**（Multi-Agent Orchestration）。这比单一大而全的 Agent 要高效得多：

- 每个角色有独立的 memory/session，不会互相污染上下文
- 通过 Telegram Group/Topic 进行异步通信，符合人类工作习惯
- Review Director 可以独立运行代码审查，不阻塞 CTO 的架构决策

### 4. 人机时间交错：这是最大的差异化价值
现有工具（Agent Deck、ductor、Vibe Kanban）全部假设「人类随机切换，AI 被人类触发」。你的设计是**系统主动调度**：

> "系统知道人类 90 分钟深度工作块，也知道 AI 异步执行特性，主动建议：现在你去写设计文档，让 AI 同时重构项目 B 的测试；30 分钟后 AI 叫你回来 Review。"

这个方向没有任何现成工具覆盖，是**0 到 1 的蓝海**。

---

## 二、关键风险与摩擦点（必须提前解决）

### 风险 1：MacBook Air 作为 24/7 服务器的可靠性

**问题**：MacBook Air 不是为 24/7 设计的。

- 合盖后默认睡眠，即使插电也可能进入 Power Nap（有限制）
- 长期高负载跑多个 Hermes Agent 可能导致热节流（thermal throttling）
- 如果 Mac 是主力开发机，24/7 Agent 运行会抢占你日常工作的资源

**建议**：
- 方案 A（推荐）：Mac 上运行 `caffeinate` 或调整 `pmset` 防止合盖睡眠
  ```bash
  sudo pmset -b sleep 0; sudo pmset -b disablesleep 1
  ```
- 方案 B（长期）：在 Tailscale 网络中加入一台便宜的云服务器（Hetzner ARM ~3 EUR/月 或 Railway/Render），作为 Agent Host。Mac 只跑 ductor 控制面，实际 Agent 负载放在云端。
- 方案 C（折中）：只在 Mac 上跑 ductor 控制中枢和轻量级 Agent（如 Review Director），重负载 Agent（CTO 深度推理、Data Director 大数据处理）放到 Win 机器上按需启动。

### 风险 2：Windows 机器的 Tailscale 稳定性

从聊天记录看，你的 Win 机器曾经离线 9 小时。如果 Win 是主力工作机，Tailscale 离线意味着：

- Mac 上的 Agent 无法向你推送通知
- 你无法从 Win 通过 Tailscale IP 访问 Mac 的 ductor API
- Agent Deck 的远程 Session 管理失效

**建议**：
- 设置 Tailscale 为 Windows 开机自启，并在任务计划程序中增加守护：如果 Tailscale 进程退出，30 秒后自动重启
- 配置 Tailscale 的 `--accept-routes` 和 `--advertise-routes`，确保内网路由稳定
- 考虑在 Mac 上部署一个「心跳检测」Agent：每 5 分钟 ping Win 的 Tailscale IP，如果连续 3 次失败，通过 Telegram 通知你 "Win 机器离线，部分 Agent 无法推送"

### 风险 3：跨设备项目状态一致性

你在 Win 上跑 KimiCode CLI，Mac 上跑 Hermes Agent，两者可能同时操作同一个 Git 仓库。

**问题场景**：
1. Win 上 KimiCode 正在修改 `api/routes.py`
2. Mac 上的 Engineer Director Agent 同时也在修改同一文件
3. Git 冲突，或者更糟——一个 Agent 覆盖另一个 Agent 的代码

**建议**：
- **严格使用 Git Worktree 隔离**：每个 Agent / 每个项目分支有独立的工作目录
  ```bash
  git worktree add ../project-cto-feature auth-refactor
  git worktree add ../project-eng-bugfix hotfix-login
  ```
- **Agent Deck 的 Worktree 管理**：Agent Deck 原生支持 Git Worktree 隔离，每个 Session 独立分支，这是必须启用的功能
- **共享存储层**：不要用 SMB/NFS 跨设备共享同一个工作目录。Tailscale 的 `tailscale serve` 或 `tailscale funnel` 更适合做 API 暴露，而不是文件同步。代码通过 Git 同步，状态通过 SQLite/Redis 同步。

### 风险 4：多 Agent 内存与上下文爆炸

5 个 Hermes Agent 同时运行，每个都有自己的上下文窗口（Claude 4 200K / Kimi 200K）。如果不对 Token 使用做预算管理，很快会：

- MacBook Air 内存吃紧（尤其是如果每个 Agent 都维护一个长上下文）
- API 账单失控（5 个 Agent 同时深度推理，每分钟可能消耗 $1-3）
- Agent 之间上下文重复（CTO 和 Engineer Director 可能同时读取同一批代码文件）

**建议**：
- **MCP Socket Pooling**：Agent Deck 支持多 Session 共享 MCP 进程，内存占用降低 85-90%。必须启用
- **上下文分级策略**：
  - CTO Agent：全量代码库上下文（架构级）
  - Engineer Director：当前 Worktree 上下文（实现级）
  - Review Director：Diff-only 上下文（最小化）
  - Data Director：数据目录 + schema 上下文
  - Marketing Director：几乎不需要代码上下文，只需要 `README.md` + `docs/`
- **Token 预算熔断**：在调度大脑层设置每小时 Token 上限，超过时自动降级（从 Claude 4 降到 Gemini Flash）

### 风险 5：ductor 与 Agent Deck 的状态同步缺口

ductor 管理 Telegram 侧的任务状态（background/interactive/batch），Agent Deck 管理本地 TUI 的 Session 状态（Running/Waiting/Idle）。如果两者不同步，你会看到：

- Telegram 上显示 "Task A running"，但 Agent Deck 显示 "Idle"
- 人类在 Win 上通过 Agent Deck 切换 Session，但 ductor 不知道，Telegram 上继续推送旧任务的通知

**建议**：
- **统一状态总线**：让 ductor 的 `tasks.json` / `sessions.json` 成为唯一状态源。Agent Deck 通过 WebSocket 或轮询读取 ductor 状态，而不是维护独立状态
- 或者反过来：Agent Deck 作为状态源，ductor 通过 Agent Deck 的 API（如果有）或 JSON 状态文件读取
- 最简单的兜底方案：定时 rsync / 共享一个 SQLite 文件在两台机器之间同步状态

---

## 三、实施路径建议（分 3 个 Phase）

### Phase 1：基础设施（1-2 天）
目标：让三设备网络互通，ductor 跑起来，至少 1 个 Hermes Agent 能 24/7 工作

1. **Tailscale 稳定化**
   - Mac：brew 重装 Tailscale（避免 App Store 版本的 SSH 限制）
   - Win：设置开机自启 + 进程守护
   - Android：安装 Tailscale App，保持后台运行
   - 测试：三设备互相 `ping <tailscale-ip>` 稳定

2. **ductor 部署（Mac）**
   ```bash
   pipx install ductor
   # 配置 Telegram Bot（@BotFather 获取 token）
   ductor config --bot-token <token>
   # 创建第一个 Group Topic 测试
   ```

3. **Agent Deck 部署（Win）**
   ```bash
   # Agent Deck 是 Go 写的，直接下载 release
   # 配置 KimiCode CLI 接入
   agent-deck add-session --tool kimicode --project <path>
   ```

4. **第一个 24/7 Agent**：Review Director
   - 职责最简单（定时扫描 GitHub PR，给出 review 意见）
   - 风险最低（只读为主，不修改代码）
   - 通过 ductor background task 启动

### Phase 2：多 Agent 编排（1 周内）
目标：5 个角色 Agent 全部跑通，能互相通信，人类能通过 Telegram 随时介入

1. **Agent 角色定义**：为每个 Agent 写 `AGENTS.md`
   ```markdown
   # CTO Agent
   - Scope: Architecture decisions, tech stack choices, cross-cutting concerns
   - Memory: ~/.muon/agents/cto/memory/
   - Context: Full codebase + PRD docs
   - Tools: GitHub API, KimiCode CLI (read-only mode)
   ```

2. **Telegram Group/Topic 架构**：
   - 主 Group：MUON Command Center
   - Topic 1：CTO Decisions（CTO Agent 发言）
   - Topic 2：Code Reviews（Review Director + Engineer Director 协作）
   - Topic 3：Data Pipeline（Data Director 专属）
   - Topic 4：Marketing Ops（Marketing Director 专属）
   - Topic 5：Human Queue（需要你人工处理的事项）

3. **跨 Agent 通信机制**：
   - 简单版：Agent A 完成任务后，通过 Telegram @ 提及 Agent B
   - 进阶版：共享 SQLite 消息总线，Agent 轮询新消息
   - 推荐：ductor 的 `SHAREDMEMORY.md` + Telegram 通知结合

4. **Agent Deck 与 ductor 状态同步**：
   - 选择状态源（推荐 ductor 的 JSON 文件）
   - 写一个小型同步脚本（Python/Node），每分钟同步一次

### Phase 3：调度大脑（2-4 周，核心差异化）
目标：实现「人机时间交错调度」，这是没有任何现成工具覆盖的部分

1. **人类注意力检测**：
   - Win 上检测当前窗口焦点（Python `pygetwindow` 或 PowerShell）
   - 键盘输入频率（空闲检测）
   - 日历 API 集成（会议时间 = 不可打扰）

2. **AI 执行时间画像**：
   - 记录每个 Agent 每次任务的耗时
   - 建立简单模型："React 组件生成平均 3 分钟"、"全库重构平均 25 分钟"

3. **调度算法（v1 简单有效）**：
   ```python
   if human_in_deep_work_block(90_min):
       start_all_background_ai_tasks()
       mark_human_required_tasks_as_blocked()
   
   if ai_task_completed and needs_human_review:
       if human_interruptible():
           telegram_notify("Project A ready for review")
       else:
           add_to_human_review_queue()
   
   if urgent_bug_entered_queue:
       pause_lowest_priority_background_task()
       telegram_notify("Emergency task escalated")
   ```

4. **可视化 Queue（Web Dashboard）**：
   - fork Vibe Kanban 前端 或自建简单 React 页面
   - 对接 ductor API（sessions.json, tasks.json）
   - Kanban 列：Backlog | AI Running | Human Review | Human Focus | Done

---

## 四、总体评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 技术可行性 | 9/10 | 所有组件都有成熟方案，只需组合 |
| 网络可靠性 | 7/10 | Tailscale 稳定，但 Win 曾离线需加固 |
| 扩展性 | 8/10 | 加新 Agent / 新设备很容易 |
| 人机协同效率 | 6/10 | 现成工具只能做到这里，调度大脑是增量价值 |
| 运维复杂度 | 5/10 | 5 个 Agent + 3 设备 + 2 编排工具，需要 careful 维护 |
| **综合** | **7.5/10** | 设计方向完全正确，执行层面需要规避 Mac 24/7 风险和状态同步问题 |

---

## 五、一句话总结

> **用 ductor 做远程异步中枢，Agent Deck 做本地状态仪表盘，Tailscale 做零信任血管，自建调度大脑做人机时间互补——这是 2026 年 VibeCoding 多项目多 Agent 协作的最短可行路径。**

最大的风险不是技术，而是**运维复杂度**：5 个 Agent × 3 设备 × 多个项目，状态管理会快速变成「分布式系统的噩梦」。建议在 Phase 2 就建立统一的状态总线和监控告警，不要等出问题再补。
