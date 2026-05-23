# Phase 1 Blueprint — Notification Hub + Desktop API + CLI Hook

> **前置**: Phase 0 完成（59 tests passing，手机端到端验证通过）
> **目标**: Agent 出错/完成秒通知手机，手机控制 Mac 桌面（浏览器/截图）
> **预计工时**: 4-6 小时（TDD）

---

## 一、Phase 1 全景

Phase 1 在 Phase 0 的 4 个核心模块之上，新增 **3 个模块** 和 **2 个扩展点**：

| 新增/扩展 | 文件 | 职责 |
|-----------|------|------|
| **Notification Hub** | `src/notification_hub.py` | 统一消息推送出口，三级优先级 |
| **Desktop API** | `src/desktop_api.py` | FastAPI 进程，执行 AppleScript 系统操作 |
| **CLI Hook** | `scripts/cli_notify.py` | 包装 CLI 工具，捕获退出码触发通知 |
| **Task Switcher 扩展** | `src/task_switcher.py` | 切换任务时注入环境变量 |
| **Command Proxy 扩展** | `src/command_proxy.py` | 接入 Desktop API 和 Notification Hub |

---

## 二、三大核心模块详解

---

### 模块 1: Notification Hub

**职责**: 任何组件（CLI Hook、Gateway、未来 Agent）都能通过它向手机发通知。

#### 为什么需要统一 Hub？

| 问题 | 没有 Hub | 有 Hub |
|------|---------|--------|
| CLI 出错通知 | 每个 CLI 自己实现 Telegram API 调用 | 统一调用 `NotificationHub.critical()` |
| 消息格式不一致 | 有的带 emoji 有的不带 | 统一格式：`[LEVEL] task_id \n message` |
| 测试困难 | 每个组件都要 mock Telegram API | 只需 mock Hub 的 3 个方法 |
| 未来换推送渠道 | 改 N 个文件 | 改 Hub 内部实现一处 |

#### 三级优先级设计

| 级别 | 触发条件 | 手机表现 | 为什么这样分 |
|------|---------|---------|-------------|
| **Critical** | 测试失败 / Build 失败 / 异常崩溃 / Agent 卡住 | 直接消息 + 震动 + 红色标记 | 需要人类立即介入，不能等 |
| **Normal** | 任务完成 / PR 就绪 / Review 请求 | 普通消息，不震动 | 重要但不紧急，人类有空再看 |
| **Info** | 日常进度 / Agent 心跳 / Token 用量 | 可选关闭，默认汇总日报 | 噪音控制，避免信息过载 |

#### 接口设计

```python
class NotificationHub:
    def __init__(self, bot_token: str, chat_id: str)
    async def critical(self, task_id: str, agent: str, message: str, actions: list = None)
    async def normal(self, task_id: str, agent: str, message: str)
    async def info(self, task_id: str, message: str)
```

**`actions` 参数**: Critical 通知可附带 Inline Keyboard 按钮，例如：
- "查看日志" → callback `/logs task-42`
- "标记已处理" → callback `/resolve task-42`

#### 集成点

- `gateway.py` 初始化时创建 `NotificationHub` 实例
- `CommandProxy.__init__` 接收 `notification_hub` 参数
- `scripts/cli_notify.py` 通过 **HTTP POST** 调用（避免 import 依赖，CLI 和 Gateway 可能不在同一个 Python 进程）

---

### 模块 2: Desktop API

**职责**: 接收 HTTP 请求，在 Mac 上执行 AppleScript 系统操作，把手机变成「遥控器」。

#### 为什么用 FastAPI 独立进程？

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **独立 FastAPI** | Gateway 和 Desktop 可独立重启；未来可部署到 Win；端口可暴露给 Tailscale | 多一个进程 | **选中** |
| 嵌入 Gateway 进程 | 少一个进程 | Gateway 重启 = Desktop 也重启；无法独立暴露端口；阻塞风险 | 放弃 |
| 直接用 AppleScript 在 Gateway 里执行 | 简单 | AppleScript 可能阻塞 1-3s，冻结 Bot 响应 | 放弃 |

#### 为什么用抽象基类（ABC）？

你当前主力在 Win11，但 Mac 是 24/7 Hub。未来 Win 也需要 Desktop 控制（比如通过 Tailscale 让 Mac 控制 Win 的浏览器）。

```python
class DesktopAPI(ABC):
    @abstractmethod
    async def open_browser(self, url: str) -> str
    @abstractmethod
    async def screenshot(self) -> bytes
    @abstractmethod
    async def focus_window(self, title: str) -> str
```

- **现在**: 实现 `MacDesktopAPI`（AppleScript）
- **未来**: 实现 `WinDesktopAPI`（PowerShell），零改动接入 Gateway

#### Mac 实现细节

| 命令 | AppleScript | 输出 |
|------|------------|------|
| `open_browser(url)` | `osascript -e 'open location "{url}"'` | `{"status": "opened", "url": url}` |
| `screenshot()` | `screencapture /tmp/muon_screenshot.png` | PNG bytes → base64 → Telegram photo |
| `focus_window(title)` | `osascript -e 'tell application "System Events" to tell process "{title}" to set frontmost to true'` | `{"status": "focused", "app": title}` |

**权限提醒**: `screenshot` 需要 macOS 屏幕录制权限，首次运行会弹窗，用户手动允许一次即可。

#### FastAPI 端点

```python
@app.post("/browser")
async def browser(url: str):
    result = await desktop.open_browser(url)
    return result

@app.post("/screenshot")
async def screenshot():
    img_bytes = await desktop.screenshot()
    return {"image_b64": base64.b64encode(img_bytes).decode()}

@app.post("/focus")
async def focus(app_name: str):
    result = await desktop.focus_window(app_name)
    return result
```

#### 与 Gateway 的集成

```python
# command_proxy.py
async def _handle_browser(self, args):
    url = args[0]
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{self.desktop_api_url}/browser", json={"url": url})
    return f"Opened: {url}"
```

---

### 模块 3: CLI Hook

**职责**: 包装 KimiCode / Claude Code / 任何 CLI，捕获退出码，失败时自动通知手机。

#### 为什么用环境变量传递任务信息？

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **环境变量** | 零配置；子进程自动继承；不改动 CLI 调用方式 | 变量可能被覆盖 | **选中** |
| 命令行参数 | 显式；不会被覆盖 | 每次都要加 `--task-id`；容易忘 | 放弃 |
| 配置文件 | 持久化 | 需要读写文件；多任务并发时冲突 | 放弃 |

环境变量列表（Task Switcher 切换时自动设置）：

```bash
MUON_TASK_ID="muon-test-1"
MUON_PROJECT="muon-core"
MUON_BRANCH="feature/telegram-bot"
MUON_AGENT="hermes"
MUON_NOTIFY_ON_ERROR="true"
MUON_NOTIFY_ON_DONE="true"
```

#### CLI Hook 工作流程

```bash
# 用户原本执行的命令
kimicode /test

# 用 CLI Hook 包装后
cli_notify kimicode /test

# 内部流程
1. 读取 MUON_TASK_ID, MUON_AGENT 环境变量
2. 执行原始命令: kimicode /test
3. 捕获 exit_code
4. exit_code != 0 → POST http://localhost:8001/notify
   {"level": "critical", "task_id": "muon-test-1", "message": "Test failed"}
5. exit_code == 0 且 MUON_NOTIFY_ON_DONE=true → POST normal 级别通知
```

#### 为什么是 HTTP POST 而不是直接 import？

CLI Hook 是一个独立脚本，可能在完全不同的 Python 环境（甚至不是 Python）中运行。HTTP 是最松耦合的通信方式。

---

## 三、扩展点设计

---

### 扩展 1: Task Switcher 环境变量注入

**修改文件**: `src/task_switcher.py`

**修改点**: `switch()` 方法成功后，设置进程级环境变量：

```python
def switch(self, task_id: str) -> dict:
    # ... existing worktree + active task logic ...
    
    # NEW: Inject env vars for CLI Hook
    os.environ["MUON_TASK_ID"] = task_id
    os.environ["MUON_PROJECT"] = task["project"]
    os.environ["MUON_BRANCH"] = task["branch"]
    os.environ["MUON_AGENT"] = task["assigned_agent"]
    
    return { ... }
```

**为什么只设环境变量不设全局状态？** 因为 Gateway 和 CLI 工具可能在不同进程中。环境变量是进程树共享的，而 Python 全局变量不是。

---

### 扩展 2: CommandProxy 集成

**修改文件**: `src/command_proxy.py`

**修改点**:
1. `__init__` 新增参数：`desktop_api_url`, `notification_hub`
2. `/browser` handler: 发送 HTTP POST 到 Desktop API
3. `/screenshot` handler: 同上
4. `/test` handler: Phase 2 扩展，先占位

**为什么不在 Gateway 层直接调 Desktop API？** 保持架构分层——Gateway 只负责 Telegram 协议，CommandProxy 负责业务逻辑路由。未来如果不用 Telegram（比如换 Matrix），Gateway 换掉，CommandProxy 和 Desktop API 不用动。

---

## 四、运行架构

```
MacBook 24/7
|
|-- Terminal 1: Gateway (python -m src.gateway)
|   |-- Telegram Bot polling
|   |-- CommandProxy → routes to Task Switcher / Desktop API / Notification Hub
|   |-- Notification Hub → pushes to phone
|
|-- Terminal 2: Desktop API (python -m src.desktop_api)
|   |-- FastAPI on :8001 → AppleScript execution
|
|-- CLI Hook (scripts/cli_notify.py)
|   |-- 包装 kimicode / claude code，env vars → notify on failure
```

---

## 五、测试策略（TDD）

| 模块 | 测试文件 | 测试数 | 关键测试 |
|------|---------|--------|---------|
| Notification Hub | `tests/test_notification_hub.py` | 10+ | mock Telegram API call, level routing, message formatting, actions keyboard |
| Desktop API | `tests/test_desktop_api.py` | 10+ | mock AppleScript subprocess, HTTP endpoint 200/404, base64 encoding |
| CLI Hook | `tests/test_cli_hook.py` | 8+ | mock subprocess exit codes, env var reading, HTTP notify POST |
| Task Switcher 扩展 | `tests/test_task_switcher.py` | +3 | env var injection on switch, env var cleanup |

---

## 六、文件清单

### 新增文件
- `src/notification_hub.py`
- `src/desktop_api.py`
- `scripts/cli_notify.py`
- `tests/test_notification_hub.py`
- `tests/test_desktop_api.py`
- `tests/test_cli_hook.py`

### 修改文件
- `src/task_switcher.py` — 环境变量注入
- `src/command_proxy.py` — Desktop API / Notification Hub 集成
- `src/gateway.py` — Notification Hub 初始化
- `requirements.txt` — 添加 `httpx`（async HTTP client）

---

## 七、部署步骤

```bash
# 1. Mac 上拉取最新代码
cd ~/muon-core && git pull

# 2. 安装 Phase 1 依赖
cd .muon
.venv/bin/pip install -r requirements.txt

# 3. 运行测试
.venv/bin/python -m pytest tests/ -v

# 4. 启动 Desktop API（Terminal 2）
.venv/bin/python -m src.desktop_api

# 5. 启动 Gateway（Terminal 1，保持运行）
.venv/bin/python -m src.gateway

# 6. 手机上测试
#    /browser https://github.com
#    /screenshot
```

---

## 八、设计决策汇总

| 决策 | 选择 | 理由 |
|------|------|------|
| Desktop API 平台 | 跨平台抽象（ABC） | Mac hub 现在跑，Win 节点未来补，不重复造轮子 |
| Desktop API 架构 | 独立 FastAPI 进程 | 独立重启、独立端口暴露、不阻塞 Gateway |
| CLI Hook 任务识别 | 环境变量 | 零配置、子进程自动继承、不改动 CLI 调用方式 |
| CLI Hook → Hub 通信 | HTTP POST | CLI 和 Gateway 可能在不同进程/环境，HTTP 最松耦合 |
| Notification 分级 | Critical/Normal/Info 三级 | 噪音控制 + 紧急度区分，避免信息过载 |
| Gateway 与 Desktop 关系 | HTTP 调用而非嵌入 | 分层架构，Gateway 只负责 Telegram 协议 |
| Screenshot 返回方式 | base64 → Telegram sendPhoto | Telegram 原生支持图片消息，体验最佳 |

---

## 九、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Desktop API 需要 GUI 权限（Mac 屏幕录制/辅助功能）| 首次运行截图/焦点命令失败 | macOS 弹窗请求权限，用户手动允许一次 |
| FastAPI 端口冲突（:8001）| Desktop API 启动失败 | 配置文件支持自定义端口，默认 8001 |
| AppleScript 执行慢（~1s）| Gateway 响应延迟 | Desktop API 是独立进程，异步 HTTP 不阻塞 Bot |
| CLI Hook 拦截不到所有错误 | 某些错误不写 stderr | 同时监控 stderr + stdout，关键词匹配补充 |
| Telegram 图片大小限制 | screenshot 发送失败 | PNG 压缩或裁剪，超过 10MB 发链接 |

---

## 十、Phase 1 完成标准

- [ ] Notification Hub: 3 级推送全部实现，10+ tests passing
- [ ] Desktop API: FastAPI 运行，/browser /screenshot 工作，10+ tests passing
- [ ] CLI Hook: 包装 KimiCode/Claude Code，退出码捕获，8+ tests passing
- [ ] 手机端到端: `/browser <url>` 打开 Mac 浏览器，`/screenshot` 截图发回手机
- [ ] 错误通知: CLI 测试失败 → 手机秒收 Critical 通知

---

*Blueprint v1.0 — 2026-05-23*
*下一步: TDD 开发 Notification Hub → Desktop API → CLI Hook*
