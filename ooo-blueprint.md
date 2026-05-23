# OOO 远程工作最终蓝图

> **目标**: Android 手机 → 远程控制 Mac/Win 上的所有 CLI Agent，实现 Out-Of-Office 场景下的完整开发工作流。
>
> **核心原则**: 零重复 Context、一键任务切换、实时反馈推送、手机端体验逼近桌面 CLI。

---

## 一、需求 → 模块映射

| 你的需求 | 对应模块 | 解决思路 |
|---------|---------|---------|
| 避免重复 context copy paste，减少 token 浪费 | **Context Registry** | 渐进式披露（3 级上下文）+ 增量 diff 同步 + context_snapshot_hash |
| 清晰切换、定位任务 | **Task Switcher** | Task Registry（SQLite）+ Git Worktree 隔离 + `/switch` 命令 |
| 完成/bug 第一时间通知 | **Notification Hub** | Telegram Bot 主动推送 + 严重错误直接消息 |
| 手机端实现 CLI 内置功能（/commands） | **Command Proxy** | 所有 CLI 的 /slash commands 统一映射到 Telegram Bot |
| 桌面级控制（打开浏览器、localhost） | **Desktop API** | AppleScript / PowerShell HTTP API + Tailscale 端口转发 |

---

## 二、架构总览

```
Android (Telegram App)
    │
    │  /switch project-alpha    → 切换任务
    │  /commit -m "fix bug"     → 执行 git 命令
    │  /test                    → 运行测试
    │  /open http://100.x:3000  → 桌面控制
    │  /status                  → 查看所有 Agent 状态
    ▼
Telegram Bot Gateway (MacBook 24/7)
    │
    ├──→ Command Router      解析 / 命令，路由到对应模块
    │
    ├──→ Context Registry    拉取上下文（按 tier，非全量）
    │
    ├──→ Task Switcher       定位项目、分支、Worktree
    │
    ├──→ Notification Hub    推送完成/错误到手机
    │
    └──→ Desktop API         AppleScript / SSH 触发系统操作
            │
    ┌───────┼───────┬───────────┐
    ▼       ▼       ▼           ▼
  Kimi   Claude   Hermes    OpenHuman
  Code   Code     / OC      (可选)
    │       │       │
    ▼       ▼       ▼
Git Worktree (每个任务独立分支 + 目录)

Tailscale 100.x 连接 Mac ↔ Win
```

**关键设计决策**:
- **单点入口**: 所有操作通过 Telegram Bot 完成，不需要记住多个 Bot
- **Mac 为 Hub**: Win 退化为「远程执行节点」，Mac 上的 Gateway 统一编排
- **Context 不是复制，是引用**: Agent 通过 TaskID 拉取上下文，绝不 copy-paste

---

## 三、五大核心模块详解

### 模块 1: Context Registry — 终结 Token 浪费

**问题**: 你现在的流程是「看到 bug → 手机 copy 错误日志 → paste 给 Agent → Agent 再 copy 给另一个 Agent」。每一步都在浪费 token。

**解决方案**: Context Registry 是 SQLite 数据库，所有 Agent 共享。

#### 3 级渐进式披露

| Tier | 内容 | 大小 | 使用场景 |
|------|------|------|---------|
| Tier 1: Summary | 任务标题 + 状态 + 最后操作一句话 | ~50 tokens | Agent 快速了解「这是哪个任务」 |
| Tier 2: Detail | 关键决策 + 当前阻塞 + 相关文件列表 | ~500 tokens | Agent 开始工作前拉取 |
| Tier 3: Full | 完整对话历史 + 代码 diff + 测试输出 | 无上限 | 仅当 Agent 明确需要时 |

**代码示例**:

```python
# context_registry.py
import sqlite3, hashlib

class ContextRegistry:
    def __init__(self, db_path="/Users/knight/.muon/context.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
                task_id TEXT PRIMARY KEY,
                project TEXT,
                branch TEXT,
                tier1_summary TEXT,       -- ~50 tokens
                tier2_detail TEXT,        -- ~500 tokens
                tier3_full TEXT,          -- full, lazy load
                context_hash TEXT,        -- sha256 of full context
                last_updated TIMESTAMP,
                owner_agent TEXT          -- 当前负责此任务的 Agent
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS context_deltas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                agent_name TEXT,
                delta TEXT,               -- 只有变化的部分
                old_hash TEXT,
                new_hash TEXT,
                timestamp TIMESTAMP
            )
        """)

    def get_context(self, task_id: str, tier: int = 1) -> dict:
        """Agent 按需拉取，绝不传全量"""
        row = self.conn.execute(
            "SELECT tier1_summary, tier2_detail, tier3_full, context_hash, owner_agent FROM contexts WHERE task_id=?",
            (task_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "summary": row[0],      # tier 1: 永远给
            "detail": row[1] if tier >= 2 else None,
            "full": row[2] if tier >= 3 else None,
            "hash": row[3],
            "owner": row[4]
        }

    def update_context(self, task_id: str, agent: str, new_full: str):
        """Agent 完成后只写 diff，不是重写全量"""
        old = self.conn.execute("SELECT tier3_full, context_hash FROM contexts WHERE task_id=?", (task_id,)).fetchone()
        old_full = old[0] if old else ""
        old_hash = old[1] if old else ""

        new_hash = hashlib.sha256(new_full.encode()).hexdigest()[:16]

        # 计算 diff（简化版，可用 difflib）
        delta = self._compute_delta(old_full, new_full)

        self.conn.execute("""
            INSERT INTO context_deltas (task_id, agent_name, delta, old_hash, new_hash, timestamp)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (task_id, agent, delta, old_hash, new_hash))

        self.conn.execute("""
            UPDATE contexts SET tier3_full=?, context_hash=?, last_updated=datetime('now'), owner_agent=?
            WHERE task_id=?
        """, (new_full, new_hash, agent, task_id))
        self.conn.commit()
```

**关键机制**:
- `context_hash`: Agent 启动时对比 hash，若未变则跳过加载
- `delta` 表: 保留历史变更，新 Agent 只需读最新 delta，不需要读全部历史
- **没有 copy-paste**: Agent 通过 HTTP API `GET /context/{task_id}?tier=2` 拉取

---

### 模块 2: Task Switcher — 一键切换，精准定位

**问题**: 你同时有多个项目，每个项目有多个任务。手机打字切目录是噩梦。

**解决方案**: Task Registry + Git Worktree + `/switch` 命令。

#### Task Registry Schema

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,         -- 例如: "proj-alpha-42"
    project TEXT,                     -- 例如: "muon-core"
    branch TEXT,                      -- 例如: "feature/task-switcher"
    worktree_path TEXT,               -- 例如: "/Users/knight/projects/muon-core--task-switcher"
    status TEXT,                      -- active | pending | done | blocked | bug
    assigned_agent TEXT,              -- kimicode | claude | hermes | oc
    context_tier INTEGER DEFAULT 1,   -- 当前 Agent 需要的上下文级别
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

#### `/switch` 命令流

```
你发送: /switch muon-core

Bot 回复:
  muon-core 的活跃任务:
  1. feature/task-switcher (kimicode, active)
  2. fix/login-bug (claude, blocked)
  3. refactor/api (hermes, pending)

你发送: /switch 1

Bot 执行:
  1. cd /Users/knight/projects/muon-core--task-switcher
  2. git status
  3. 向 KimiCode 注入 Tier 2 Context (Detail)
  4. 回复: "已切换到 muon-core/feature/task-switcher。当前 3 个文件修改未提交。"
```

**代码示例**:

```python
# task_switcher.py
import subprocess, os

class TaskSwitcher:
    def __init__(self, base_dir="/Users/knight/projects"):
        self.base_dir = base_dir

    def switch(self, task_id: str) -> dict:
        task = self._get_task(task_id)
        if not task:
            # 模糊匹配项目名
            return self._list_tasks(fuzzy=task_id)

        # 1. 确保 worktree 存在
        if not os.path.exists(task["worktree_path"]):
            self._create_worktree(task["project"], task["branch"], task["worktree_path"])

        # 2. 注入上下文到对应 Agent
        ctx = context_registry.get_context(task_id, tier=task["context_tier"])
        agent = self._get_agent(task["assigned_agent"])
        agent.inject_context(ctx)

        # 3. 返回状态
        git_status = subprocess.run(
            ["git", "-C", task["worktree_path"], "status", "--short"],
            capture_output=True, text=True
        )
        return {
            "task_id": task_id,
            "project": task["project"],
            "branch": task["branch"],
            "agent": task["assigned_agent"],
            "git_status": git_status.stdout or "clean"
        }

    def _create_worktree(self, project: str, branch: str, path: str):
        repo = f"{self.base_dir}/{project}"
        subprocess.run(["git", "-C", repo, "worktree", "add", path, branch], check=True)
```

---

### 模块 3: Notification Hub — 完成/bug 秒级推送

**问题**: Agent 跑完测试、发现 bug、或者需要你决策时，你不知道。等你打开手机已经晚了。

**解决方案**: 双轨通知系统。

| 级别 | 触发条件 | 渠道 | 示例 |
|------|---------|------|------|
| **Critical** | 测试失败 / Build 失败 / 异常崩溃 | Telegram 直接消息 + 手机震动 | "muon-core: Test failed in auth/login.spec.ts — 需要你确认修复方向" |
| **Normal** | 任务完成 / PR 就绪 / 代码 Review 完成 | Telegram Topic 消息 | "feature/task-switcher 已完成，3 commits，PR 待 Review" |
| **Info** | 日常进度 / Agent 心跳 | 汇总日报（可关闭） | "今日完成: 2 tasks, 1 blocked, Token 消耗: 12K" |

**集成方式**:

```python
# notification_hub.py
import asyncio

class NotificationHub:
    def __init__(self, telegram_bot_token: str, user_chat_id: str):
        self.bot_token = telegram_bot_token
        self.user_chat_id = user_chat_id

    async def notify(self, level: str, task_id: str, message: str, actions: list = None):
        """
        actions: [{"text": "查看日志", "callback": "/logs task-42"}, ...]
        """
        emoji = {"critical": "🔴", "normal": "🟢", "info": "🔵"}.get(level, "⚪")
        text = f"{emoji} [{level.upper()}] {task_id}\n\n{message}"

        if actions:
            # Telegram Inline Keyboard
            keyboard = [[{"text": a["text"], "callback_data": a["callback"]}] for a in actions]
            await self._send_message(text, reply_markup={"inline_keyboard": keyboard})
        else:
            await self._send_message(text)

    async def _send_message(self, text: str, **kwargs):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.user_chat_id, "text": text, **kwargs}
        async with aiohttp.ClientSession() as session:
            await session.post(url, json=payload)
```

**Agent 侧集成**:

每个 CLI 工具运行时包装一层 hook：

```bash
# 在 KimiCode / Claude Code 启动前设置环境变量
export MUON_NOTIFY_ON_DONE=true
export MUON_NOTIFY_ON_ERROR=true
export MUON_TASK_ID="muon-core-42"
```

Wrapper 脚本在检测到进程退出码非 0 时，自动调用 NotificationHub 发送 Critical 级别通知。

---

### 模块 4: Command Proxy — 手机端就是 CLI

**目标**: 在 Telegram 里打字 `/commit -m "fix"` 的效果，和在 KimiCode 里打 `/commit -m "fix"` 完全一样。

#### 命令映射表

| Telegram 命令 | 映射到 CLI | 说明 |
|--------------|-----------|------|
| `/switch <project>` | Task Switcher | 切换项目/任务 |
| `/commit <msg>` | `git commit` | 当前 worktree 执行 |
| `/test [pattern]` | `npm test` / `pytest` | 运行测试 |
| `/review` | `/review` (Claude Code) | 请求代码 Review |
| `/deploy [env]` | `deploy.sh` | 部署脚本 |
| `/ask <question>` | 直接发给当前 Agent | 向负责的 Agent 提问 |
| `/status` | 查询所有 Agent 状态 | 谁在干什么 |
| `/logs [n]` | `tail -n` | 查看最近日志 |
| `/browser <url>` | Desktop API | 远程打开浏览器 |
| `/screenshot` | Desktop API | 截取当前屏幕 |

#### 实现方式

```python
# command_proxy.py
class CommandProxy:
    def __init__(self):
        self.agents = {
            "kimicode": KimiCodeAdapter(),
            "claude": ClaudeCodeAdapter(),
            "hermes": HermesAdapter(),
            "oc": OpenCodeAdapter()
        }

    async def handle(self, command: str, task_id: str = None) -> str:
        parts = command.split()
        cmd = parts[0].lstrip("/")
        args = parts[1:]

        # 1. 查询当前任务（如果没指定）
        if not task_id:
            task_id = task_switcher.get_active_task()

        task = task_switcher.get_task(task_id)
        agent = self.agents.get(task["assigned_agent"])

        # 2. 路由命令
        if cmd == "switch":
            return task_switcher.switch(" ".join(args))
        elif cmd == "commit":
            return agent.run_git_command(task["worktree_path"], "commit", args)
        elif cmd == "test":
            return agent.run_test(task["worktree_path"], args)
        elif cmd == "ask":
            # 直接转发给 Agent
            context = context_registry.get_context(task_id, tier=2)
            return agent.ask(context, " ".join(args))
        elif cmd == "browser":
            return desktop_api.open_browser(args[0])
        elif cmd == "screenshot":
            return desktop_api.screenshot()
        elif cmd == "status":
            return self._status_report()
        else:
            return f"未知命令: /{cmd}。可用命令: /switch, /commit, /test, /review, /ask, /status, /browser, /screenshot"
```

**KimiCode Adapter 示例**:

```python
class KimiCodeAdapter:
    def __init__(self, socket_path="/tmp/kimicode.sock"):
        self.socket_path = socket_path

    def run_git_command(self, cwd: str, subcmd: str, args: list) -> str:
        # 方法 A: 通过 KimiCode 的 MCP socket 发送命令
        # 方法 B: 直接在 worktree 目录执行 git
        result = subprocess.run(
            ["git", "-C", cwd, subcmd] + args,
            capture_output=True, text=True
        )
        return result.stdout or result.stderr

    def ask(self, context: dict, question: str) -> str:
        # 通过 KimiCode CLI 的 stdin 注入问题
        prompt = f"""Context: {context['summary']}
Detail: {context.get('detail', 'N/A')}

Question: {question}
"""
        # 调用 KimiCode API 或 subprocess
        return self._send_to_kimicode(prompt)
```

---

### 模块 5: Desktop API — 手机控制桌面

**目标**: 在手机上发 `/browser http://100.xx.xx.xx:3000`，Mac 上自动打开 Chrome 并访问该地址。

#### 功能清单

| 命令 | Mac 实现 | Win 实现 |
|------|---------|---------|
| `/browser <url>` | `osascript -e 'open location "URL"'` | `Start-Process chrome URL` |
| `/screenshot` | `screencapture` / `osascript` | `Add-Type [System.Drawing.Graphics]` |
| `/focus <app>` | `osascript -e 'tell app "App" to activate'` | `Get-Process \| ?{ $_.Name -like "*App*" }` |
| `/type <text>` | AppleScript System Events keystroke | `SendKeys` |
| `/key <shortcut>` | `osascript -e 'keystroke "s" using command down'` | PowerShell `SendKeys` |

#### HTTP API (FastAPI)

```python
# desktop_api.py
from fastapi import FastAPI
import subprocess, base64

app = FastAPI()

@app.post("/browser")
def open_browser(url: str):
    subprocess.run([
        "osascript", "-e",
        f'tell application "Google Chrome" to open location "{url}"'
    ])
    return {"status": "opened", "url": url}

@app.post("/screenshot")
def screenshot():
    path = "/tmp/muon_screenshot.png"
    subprocess.run(["screencapture", path])
    with open(path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    return {"image_b64": img_b64}

@app.post("/focus")
def focus_app(app_name: str):
    subprocess.run([
        "osascript", "-e",
        f'tell application "{app_name}" to activate'
    ])
    return {"status": "focused", "app": app_name}
```

**Win 节点**: 在 Win 上跑同样的 FastAPI（Python 跨平台），用 PowerShell 替代 AppleScript。Mac Gateway 通过 Tailscale `POST http://100.x.x.x:8000/browser` 控制 Win。

**访问 localhost/100.x**: 不需要桌面控制。Tailscale 已经打通了网络，手机上直接浏览器打开 `http://100.91.29.68:3000` 即可。如果需要「让 Mac 打开某个 localhost 页面给我看」，用 `/browser http://localhost:3000` + `/screenshot` 组合。

---

## 四、部署路线图

### Phase 0: 今天（2 小时）

**目标**: 跑通最小可用版本（一个任务 + 一个 Agent + 一个命令）。

1. **Mac 上创建 Context Registry SQLite**
   ```bash
   mkdir -p ~/.muon
   sqlite3 ~/.muon/context.db < schema.sql
   ```

2. **创建 Telegram Bot（如果还没有）**
   - @BotFather → `/newbot` → 拿到 token

3. **写最小 Gateway（Python + python-telegram-bot）**
   ```bash
   pip install python-telegram-bot fastapi uvicorn aiohttp
   ```
   只实现 `/switch` 和 `/ask` 两个命令。

4. **测试**
   - 手机上发 `/switch muon-core`
   - Bot 回复当前任务列表
   - 发 `/ask 这个 bug 怎么修`
   - KimiCode 回复，结果推送到手机

### Phase 1: 本周

5. **集成 Notification Hub**
   - 包装 KimiCode / Claude Code 启动脚本，出错时自动调用 notify API

6. **实现 Context Registry 的 3-tier 拉取**
   - 修改 KimiCode / Hermes 启动逻辑，启动时先 GET `/context/{task_id}?tier=2`

7. **Win 上部署 Desktop API**
   - 同样的 FastAPI，PowerShell 脚本
   - 测试 `/browser` 和 `/screenshot`

### Phase 2: 下周

8. **完善 Command Proxy**
   - 实现所有 /commands 映射
   - 长输出截断 + 分页（Telegram 4096 字符限制）

9. **Task Registry Web UI（可选）**
   - 手机浏览器打开 `http://100.x.x.x:8080` 看任务看板

10. **多 Agent 状态看板**
    - `/status` 显示所有 Agent 的当前任务、Token 消耗、最后心跳

---

## 五、文件结构

```
~/.muon/
├── context.db              # Context Registry + Task Registry + Delta 历史
├── config.yaml             # Telegram token, Tailscale IPs, Agent paths
├── gateway.py              # Telegram Bot + Command Router
├── desktop_api.py          # FastAPI for Mac desktop control
├── adapters/
│   ├── kimicode.py         # KimiCode CLI adapter
│   ├── claude.py           # Claude Code adapter
│   ├── hermes.py           # Hermes adapter
│   └── oc.py               # OpenCode adapter
├── scripts/
│   ├── notify_on_error.sh  # CLI wrapper hook
│   └── worktree_init.sh    # Git worktree 自动创建
└── logs/
    └── gateway.log
```

---

## 六、关键配置

```yaml
# ~/.muon/config.yaml
 Telegram:
  bot_token: "YOUR_BOT_TOKEN"
  user_chat_id: "YOUR_CHAT_ID"

agents:
  kimicode:
    socket: "/tmp/kimicode.sock"
    worktree_base: "/Users/knight/projects"
  claude:
    socket: "/tmp/claude.sock"
    worktree_base: "/Users/knight/projects"
  hermes:
    config: "/Users/knight/.hermes/config.yaml"
    worktree_base: "/Users/knight/projects"

devices:
  mac:
    tailscale_ip: "100.91.29.68"
    desktop_api_port: 8000
  win:
    tailscale_ip: "100.91.29.100"
    desktop_api_port: 8000

projects:
  muon-core:
    repo: "/Users/knight/projects/muon-core"
    default_agent: "kimicode"
    test_command: "npm test"
```

---

## 七、与现有工具的衔接

| 你已有的 | 如何接入蓝图 |
|---------|------------|
| Hermes (Mac 24/7) | 作为 Agent 之一注册到 Command Proxy，通过 adapter 转发命令 |
| OpenCode (Mac 24/7) | 同上 |
| KimiCode CLI (Win) | 可选迁移到 Mac，或在 Win 上跑 Desktop API + 通过 Tailscale 暴露 |
| Tailscale | 已经是网络层，不需要改。Desktop API 监听 Tailscale IP |
| claude-mem | Context Registry 的 Tier 3 可以直接读 claude-mem 的 SQLite |
| ductor | Telegram Gateway 可以替代 ductor 的 transport 层，或并行运行 |
| Agent Deck | 读取同一个 `context.db` 做 TUI 展示，不冲突 |

---

## 八、Token 效率量化

| 场景 | 旧方式 (copy-paste) | 新方式 (Context Registry) | 节省 |
|------|-------------------|------------------------|------|
| 切换任务给 Agent | 全量历史 3000 tokens | Tier 2 Detail 500 tokens | **83%** |
| Agent A → Agent B 交接 | A 的完整输出 2000 tokens | Delta diff 200 tokens | **90%** |
| 日常状态查询 | 不需要 context | Tier 1 Summary 50 tokens | **可忽略** |
| 5 个 Agent 并行 | 5 × 3000 = 15000 tokens | 5 × 500 = 2500 tokens | **83%** |

---

## 九、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| MacBook Air 资源不足跑 Gateway + 多 Agent | Gateway 响应慢 | Gateway 很轻量（Python < 50MB），若不够加 Hetzner ARM 云机 |
| Telegram Bot 延迟（3-5s）| 不适合实时交互 | Critical 通知用直接消息（快），日常命令延迟可接受 |
| Context Registry 单点故障 | 所有 Agent 无法获取上下文 | SQLite 文件定期备份到 iCloud/Dropbox |
| Git Worktree 分支过多 | 磁盘爆炸 | 每周清理已合并的 worktree |
| 手机屏幕小，长输出难读 | 体验差 | 截断 + 分页 + 关键信息高亮 + 可选 Web UI |

---

*Blueprint v1.0 — 2026-05-23*
*下一步: Phase 0 最小可用版本实现*
