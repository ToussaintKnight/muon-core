# Agent 协作瓶颈与 OOO 远程控制深度分析

## 一、hermes-workspace 评估：不只是 Dashboard

**结论：这个项目远超 Dashboard，是一个完整的多 Agent 控制平面。**

### 核心能力

| 模块 | 能力 | 对你的价值 |
|------|------|-----------|
| Swarm Mode | 无限 Hermes Agent + 1 Orchestrator + 零手动调度 | 你的 CTO/Eng/Data/Marketing/Review 五角色天然适配 |
| Role-based dispatch | Builder/Reviewer/Docs/Research/Ops/Triage/QA/Lab 自动路由 | 避免重复推理——任务按角色分发给 specialist |
| Persistent tmux workers | Agent 上下文跨任务保持，安全轮换 | 24/7 运行不丢上下文 |
| Byte-verified review gate | PR 合并前自动审查 | Review Director 的自动化实现 |
| Kanban TaskBoard | Backlog/Ready/Running/Review/Blocked/Done | 可视化 Queue 的现成方案 |
| PWA + Tailscale | 手机浏览器直接访问，无需端口暴露 | Android 上也能看 Agent 状态 |

### 关于「避免重复推理」
hermes-workspace 通过 **Role-based dispatch** 解决：Orchestrator 会将任务按类型自动路由到 specialist agent（builder 写代码、reviewer 审代码、research 做调研），而不是每个 agent 都做一遍完整推理。

**但有一个关键缺口**：当前自托管版本 **没有跨 Agent 共享内存**（Team shared memory 在 Cloud 版 roadmap 上）。这意味着 CTO Agent 做的架构决策，Engineer Director 不会自动知道——需要靠 AGENTS.md 或外部消息总线同步。

### 与你的架构关系
hermes-workspace 可以**替换或增强**你当前的手动 Hermes 部署：
- 如果你现在纯用命令行跑 Hermes → hermes-workspace 给你 Web UI + Swarm 编排
- 如果你已经在用 ductor → 两者可以共存：ductor 负责 Telegram/Matrix 远程入口，hermes-workspace 负责 Mac 上的 Swarm 调度

---

## 二、Telegram 群组多 Agent 协作瓶颈：这是 Telegram 的平台限制，**无解**

### 根本问题
你把 Hermes Bot 和 OC Bot 拉到一个 Telegram 群组，但它们**看不到彼此的消息**——这不是配置问题，而是 **Telegram Bot API 的硬编码限制**：

> "Bots talking to each other could potentially get stuck in unwelcome loops. To avoid this, we decided that **bots will not be able to see messages from other bots regardless of mode**."
> —— Telegram 官方设计决策

无论你怎么设置 privacy mode、管理员权限、还是用什么框架，**Bot API 级别的 bot-to-bot 消息隔离是不可绕过的**。

### 现有 GitHub 工具能否解决？
**不能。** 这不是工具的缺口，是平台的限制。任何基于 Telegram Bot API 的项目（ductor、hermes-workspace、你自己写的 bot）都受同样的约束。

### 可行的 3 种替代方案

#### 方案 A：Shared Message Bus（推荐，最灵活）
不依赖 Telegram 做 Agent 间通信，而是建立一个**外部共享消息总线**：

```
Hermes Bot ──&gt; 读取/写入 ──&gt; SQLite/Redis 消息总线 &lt;── 读取/写入 &lt;── OC Bot
```

- 每个 Agent 轮询（或 WebSocket 订阅）消息总线
- Telegram 只作为「人类界面」，Agent 间的对话在共享总线进行
- 人类可以在 Telegram 看到 Agent 对话的摘要（由一个 Agent 转发）

**实现**：一个简单的 SQLite 数据库放在 Mac 上，所有 Agent 通过本地 API 读写：
```sql
CREATE TABLE agent_messages (
  id INTEGER PRIMARY KEY,
  from_agent TEXT,      -- 'CTO', 'EngDirector', etc.
  to_agent TEXT,        -- 'ALL' 或特定角色
  content TEXT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
  read_by TEXT          -- JSON array
);
```

#### 方案 B：切换到 Matrix（原生支持 Bot 互看）
Matrix 协议**没有** bot-to-bot 消息隔离。ductors 的 Matrix transport 支持 E2EE、room topics、并行运行。

**优势**：
- 同一个 room 里，所有 Agent 能看到彼此发言
- Room-based 隔离：一个 room = 一个项目/话题
- E2EE 加密

**劣势**：
- Matrix 客户端体验不如 Telegram
- 需要自建 homeserver 或用公共服务器（matrix.org 有时不稳定）

#### 方案 C：ductor 的 Sub-agent Delegation（最简单，但非对等）
利用 ductor 已有的主-从 Agent 架构：

```
你 (Telegram) ──&gt; Main Agent (Hermes)
                        │
                        ├─delegate─&gt; Sub-agent 1 (Codex/OC)
                        ├─delegate─&gt; Sub-agent 2 (Kimi)
                        └─delegate─&gt; Sub-agent 3 (Claude)
```

- 主 Agent 接收你的指令，决定派发给哪个 sub-agent
- sub-agent 在隔离 workspace 中工作，结果返回主 Agent
- 主 Agent 汇总后回复你

**局限**：这是「星型」拓扑，不是 Agent 间自由对话。CTO Agent 不能直接@Engineer Director 讨论架构——必须通过主 Agent 中转。

---

## 三、远程控制 CLI 与 OOO 需求

### 现状分析
ductor 是**本地运行**工具：它在你机器的终端里执行 `claude`、`codex`、`kimicode` 等命令。Bot 本身不离开本机。

这意味着：
- Mac 上跑的 ductor → 只能控制 Mac 上的 CLI
- Win 上如果没有 ductor → 手机无法通过 Telegram 控制 Win 上的 KimiCode

### 满足 OOO 的 3 条路径

#### 路径 A：每台机器都跑 ductor（最简单）
Mac 和 Win 各自运行独立的 ductor 实例，各自连接同一个 Telegram Bot（或不同 Bot）。

```
手机 Telegram
    ├─&gt; @MUON_Mac_Bot ──&gt; Mac ductor ──&gt; Hermes / OC / KimiCode
    └─&gt; @MUON_Win_Bot ──&gt; Win ductor ──&gt; KimiCode / WorkBuddy
```

- 你在 Telegram 里选择跟哪个 Bot 对话，就控制哪台机器
- 不需要 SSH，不需要开端口，Tailscale 甚至不是必须的（只要机器能联网）

#### 路径 B：SSH + tmux + Tailscale（最强大）
手机上通过 Tailscale 直连 Mac/Win，进入 tmux session，获得**完整终端权限**。

**Android 方案（Termux）**：
```bash
# 在 Android 上安装 Termux + Tailscale
pkg install termux-api openssh
# 连接 Tailscale
tailscale up
# SSH 到 Mac
ssh knight@100.91.29.68
# 进入 tmux 选择界面（自动弹出的 fzf）
# 选择 "kimi-dev" session，直接接管 KimiCode CLI
```

**iOS 方案（Termius）**：
- 安装 Termius App
- 配置 Tailscale 主机名作为 SSH 目标
- 保存密钥，一键连接

**tmux 自动 session 管理**（参考 elliotbonneville 的方案）：
```zsh
# ~/.zshrc 中自动检测 SSH
if [[ -n "$SSH_CONNECTION" ]]; then
    # SSH 连接：显示 fzf session 选择器
    selection=$(tmux ls | fzf --prompt="session> ")
    [[ -n "$selection" ]] && exec tmux attach -t "$(echo $selection | cut -d: -f1)"
fi
```

**优势**：
- 不只是控制 CLI——可以运行任何命令、查看任何文件、修改配置
- 系统级操作（窗口切换、截图、启动 App）都可以做
- 连接断开后重新 attach，session 不丢

#### 路径 C：hermes-workspace Web UI（最舒适）
hermes-workspace 是 PWA，支持 Tailscale 内网访问。你在 Android 浏览器打开：
```
http://100.91.29.68:3000
```

- 完整聊天界面、文件浏览器、终端、Agent 状态面板
- 不需要装任何 App，浏览器即开即用

**局限**：只能控制 Mac 上的 Agent，无法控制 Win 上的 KimiCode。

---

## 四、系统级操作（窗口切换、测试执行）

你的需求是「让 Agent 帮我 switch 到某个窗口，测试什么东西」。这需要**系统级自动化**。

### Mac 上（AppleScript + osascript）
```bash
# 切换到特定 App 窗口
osascript -e 'tell application "Terminal" to activate'
osascript -e 'tell application "System Events" to keystroke "2" using command down'

# 截图
screencapture -x /tmp/screen.png

# 运行测试
osascript -e 'tell application "Terminal" to do script "cd /project && npm test"'
```

ductor 可以配置自定义 tool/script，让 Agent 能调用这些 AppleScript 命令。

### Win 上（PowerShell + AutoHotkey）
```powershell
# 切换窗口
Add-Type @"
  using System; using System.Runtime.InteropServices;
  public class WinAPI { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); }
"@
$proc = Get-Process | Where-Object { $_.MainWindowTitle -like "*KimiCode*" }
[WinAPI]::SetForegroundWindow($proc.MainWindowHandle)

# 截图
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("%{PRTSC}")
```

### 推荐架构：Bot 触发系统级操作
```
你 (手机 Telegram)
    │
    ▼
ductor Bot on Mac
    │
    ├─&gt; 普通任务 ──&gt; Hermes / OC CLI
    │
    └─&gt; 系统级任务 ──&gt; 执行 AppleScript / PowerShell ──&gt; 切换窗口/截图/测试
```

---

## 五、推荐组合方案

基于你「Mac 24/7 已完美实现」的现状，建议这样演进：

### 立即实施（今天）
1. **解决 Agent 协作**：在 Mac 上启动一个 SQLite 消息总线（或 Redis），让 Hermes 和 OC 通过它交换消息
   ```python
   # 最简单的实现：flask + sqlite
   # Mac 上跑一个 127.0.0.1:5000 的微型服务
   # 每个 Agent 通过 HTTP POST/GET 收发消息
   ```

2. **手机 SSH 进 Mac**：在 Android 装 Termux，配置 Tailscale SSH，测试 `ssh knight@100.91.29.68` + tmux attach

3. **Win 上部署 ductor**：让 Win 的 KimiCode 也能被 Telegram 控制（独立于 Mac 的 ductor）

### 本周实施
4. **评估 hermes-workspace**：在 Mac 上部署 hermes-workspace，把现有的 Hermes + OC 纳入 Swarm Mode
   - 用它的 Orchestrator 替代你手动在 Telegram 里协调
   - 用它的 Kanban TaskBoard 替代手动状态跟踪

5. **系统级脚本库**：给 ductor 写一组 `system-tools/`：
   - `switch_to_window.sh`（AppleScript 切窗口）
   - `run_tests.sh`（跑测试套件）
   - `screenshot_and_send.sh`（截图发 Telegram）

### 后续考虑
6. **Matrix 并行通道**：如果 Telegram Bot 互看问题持续困扰，在 ductor 中启用 Matrix transport，把 Agent 间对话迁移到 Matrix room

---

## 六、关键结论

| 问题 | 结论 |
|------|------|
| hermes-workspace 有价值吗？ | **有**，它是控制平面而非单纯 Dashboard，Swarm Mode 直接对标你的多角色需求 |
| Telegram Bot 能互看吗？ | **不能**，平台限制，任何工具都无能为力 |
| 现有工具能解决 Agent 协作吗？ | **ductor delegation + shared message bus** 可以，Telegram 群不行 |
| 手机能控制 Win 上 CLI 吗？ | **能**，但需要 Win 上也跑 ductor，或用 SSH + Tailscale |
| 系统级操作（窗口切换）能做吗？ | **能**，通过 AppleScript/PowerShell 触发，需要给 Agent 配置系统工具权限 |
