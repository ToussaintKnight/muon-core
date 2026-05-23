# muon-core — 下一步完整指南

> 从「代码验证通过」到「手机上控制 CLI」，再到后续 Phase 规划。
> 每一步都是复制粘贴执行。

---

## Phase 0 最后一步：让 Bot 跑起来（今天）

### Step 1 — 创建 Telegram Bot（2 分钟）

1. 在手机上打开 Telegram，搜索 **@BotFather**
2. 发送 `/newbot`
3. 按提示输入：
   - Bot 名字：`muon-core`（或任何名字）
   - Bot 用户名：`muon_core_bot`（必须全局唯一，以 `_bot` 结尾）
4. BotFather 回复一条消息，里面包含 **HTTP API token**，格式：
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   **复制保存好，不要发给任何人。**

> 如果你已经有 Bot，直接用现有 token，跳过这步。

---

### Step 2 — 获取你的 Chat ID（1 分钟）

**方法一（最简单）：**

1. 给刚创建的 Bot 发一条消息，比如 `hi`
2. 在 Mac 终端执行：
   ```bash
   curl -s "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | grep -o '"chat":{[^}]*}' | grep -o '"id":[0-9]*'
   ```
   或者简单点：
   ```bash
   curl -s "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'][0]['message']['chat']['id'])"
   ```
3. 输出的数字就是你的 `chat_id`（例如 `123456789`）

**方法二（备用）：**

- 搜索 @userinfobot，发任意消息，它直接告诉你 ID。

---

### Step 3 — 配置 Token（Mac 上执行）

```bash
mkdir -p ~/.muon
cat > ~/.muon/config.yaml << 'EOF'
telegram:
  bot_token: "123456789:YOUR_TOKEN_HERE"
  user_chat_id: "123456789"
EOF
chmod 600 ~/.muon/config.yaml
```

> `chmod 600` 确保只有你能读取这个文件。

---

### Step 4 — 启动 Gateway（Mac 上执行）

```bash
cd ~/muon-core/.muon
python3 -m src.gateway
```

预期输出：
```
Gateway started. Send /status to your bot.
Press Ctrl+C to stop.
```

**保持终端运行**，这是你的 Bot 服务器。

---

### Step 5 — 手机上测试

打开 Telegram，找到你的 Bot，发送：

| 你发送 | Bot 回复 |
|--------|---------|
| `/start` | 欢迎消息 + 可用命令列表 |
| `/status` | 当前任务列表（现在应该是空的） |
| `/switch muon-core` | "No active task..."（还没注册任务） |
| `hello` | 自动转成 `/ask hello` → 当前没有活跃任务，提示错误 |

如果收到回复，说明 **Gateway 跑通了**。

---

### Step 6 — 注册第一个测试任务（Mac 上另开终端）

```bash
cd ~/muon-core/.muon
python3 << 'PYEOF'
from src.context_registry import ContextRegistry
from src.task_switcher import TaskSwitcher

reg = ContextRegistry(db_path="~/.muon/context.db")
switcher = TaskSwitcher(context_registry=reg, base_dir="~/projects")

switcher.create_task(
    task_id="muon-test-1",
    project="muon-core",
    branch="feature/telegram-bot",
    assigned_agent="hermes",
    tier1="Telegram Gateway integration",
    tier2="Hook up CommandProxy to Telegram Bot, test /status and /switch"
)

print("Task created. Try /status on your phone.")
PYEOF
```

手机上再发 `/status`，应该看到：
```
Tasks:
- muon-test-1 [pending] (muon-core / feature/telegram-bot)
```

---

## Phase 1：Notification Hub + Desktop API（本周）

### 目标
- Agent 出错 / 任务完成 → 手机秒收通知
- 手机发 `/browser http://100.x.x.x` → Mac 自动开 Chrome
- 手机发 `/screenshot` → Mac 截图发回手机

### 开发清单

| 模块 | 文件 | 功能 |
|------|------|------|
| Notification Hub | `src/notification_hub.py` | 三级推送（Critical/Normal/Info） |
| Desktop API | `src/desktop_api.py` | FastAPI 接收 HTTP 请求，执行 AppleScript |
| CLI Hook | `scripts/cli_notify.py` | 包装 KimiCode/Claude Code，捕获退出码触发通知 |

### 快速启动（等我写代码）

```bash
# 1. 安装额外依赖
pip3 install fastapi uvicorn

# 2. 启动 Desktop API（Mac 上）
python3 -m src.desktop_api

# 3. 手机上测试
/browser https://github.com/ToussaintKnight/muon-core
/screenshot
```

---

## Phase 2：完整 Command Proxy + 多 Agent 看板（下周）

### 目标
- 所有 CLI `/commands` 都能在手机执行
- 5 个 Agent（CTO/Eng/Data/Marketing/Review）状态实时看板

### 新增命令

| 命令 | 作用 |
|------|------|
| `/commit "msg"` | 在活跃任务的 worktree 执行 `git commit` |
| `/test` | 执行测试，失败则推送 Critical 通知 |
| `/review` | 生成 diff，发送到 Review Director Agent |
| `/browser <url>` | Mac 打开浏览器（Phase 1 实现） |
| `/screenshot` | Mac 截图发回（Phase 1 实现） |
| `/agents` | 查看 5 个 Agent 的在线状态和当前任务 |
| `/delegate <agent> <task>` | 把任务派给指定 Agent |

---

## Phase 3：与 Star 项目集成（后续）

| 项目 | 集成方式 | 价值 |
|------|---------|------|
| **paperclip** | 替换自建的调度大脑 | Heartbeat + Budget + Governance |
| **claude-mem** | 接入 Context Registry Tier 3 | 跨会话持久记忆 |
| **cc-switch** | 统一 CLI 配置 | Win/Mac 配置同步 |
| **openhuman** | 作为个人知识中枢 | Gmail/Calendar/GitHub 自动拉取 |

---

## 当前状态一览

```
Phase 0  ✅  Context Registry + Task Switcher + Command Proxy + Telegram Gateway
          ✅  59 tests passing
          ✅  GitHub 仓库同步
          ✅  Mac 跨平台验证通过
          ⏳  配置 Telegram Bot token（需要你手动做）
          ⏳  启动 Gateway 并手机上测试

Phase 1  ⏳  Notification Hub
          ⏳  Desktop API (Mac)
          ⏳  CLI wrapper hooks

Phase 2  ⏳  完整 /commands 映射
          ⏳  多 Agent 状态看板

Phase 3  ⏳  paperclip / claude-mem / cc-switch 集成
```

---

## 遇到问题？

| 症状 | 检查项 |
|------|--------|
| `ModuleNotFoundError` | `python3 scripts/verify.py` 确认依赖 |
| Bot 不回复 | 检查 token 是否正确；Mac 能否访问外网 |
| `/status` 报错 | `~/.muon/context.db` 是否有写权限 |
| Gateway 启动后没反应 | 终端是否保持运行？是否被防火墙拦截？ |

---

## 需要我做什么？

**选项 A**：继续写 Phase 1 代码（Notification Hub + Desktop API）
**选项 B**：先等你配完 Telegram Bot，跑通手机上 `/status`，再推进
**选项 C**：写 AGENTS.md 定义（5 个 Agent 的角色、能力边界、协作规则）

你想先走哪条？
