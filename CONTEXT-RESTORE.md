# muon-core — Session 上下文恢复包

> **用途**: 在新 WorkBuddy session 中加载此文件，即可恢复从项目启动到 Phase 0 完成的全部上下文。
> **更新日期**: 2026-05-23
> **项目仓库**: https://github.com/ToussaintKnight/muon-core

---

## 一、你是谁 & 我是谁

### 用户（Sir. Everett Knight）
- **Name**: Sir. Everett Knight
- **工作方式**: 多设备（Android/MacBook/Win11）、多项目并行、人机协同
- **主力开发环境**: Win11 + KimiCode CLI
- **24/7 Agent 宿主**: MacBook Air（需注意稳定性风险）
- **网络基础设施**: Tailscale TailNet（GitHub-hosted），曾出现 Win 离线 9h
- **开发语言偏好**: 全程中文开发

### AI 助手
- **名称**: WorkBuddy（可自定义）
- **Vibe**: 直接、有主见、不废话
- **语言**: 用户用中文则中文回复

---

## 二、项目概述

**muon-core** 是一个跨设备多 Agent 远程工作系统，目标：
- 支持多项目快速切换
- AI Agent 异步协作
- 人机时间交错效率最大化
- Android 手机远程控制 Mac/Win 上的所有 CLI Agent

**核心创新**: "人机时间交错调度算法" — 现有工具空白区

---

## 三、技术栈

| 层级 | 工具 | 说明 |
|------|------|------|
| CLI 主力 | KimiCode CLI | Win11 主力开发 |
| CLI 辅助 | Claude Code, Codex CLI | 多工具并行 |
| IDE | AntiGravity IDE | 偶尔使用 |
| Agent 框架 | Hermes (Telegram/Matrix) | Mac 24/7 运行 |
| Agent 编排 | ductor | 远程异步任务 |
| 会话管理 | Agent Deck (TUI), CCManager | 备选 |
| 网络 | Tailscale | 三设备组网 |
| 通信 | Telegram Bot | 主入口 |
| 项目代码 | Python 3.10+ | SQLite + FastAPI |

---

## 四、架构设计（5 大模块）

### 4.1 Context Registry — 终结 Token 浪费
- SQLite 数据库 `~/.muon/context.db`
- 3 级渐进式披露（Tier 1: 50 tokens / Tier 2: 500 tokens / Tier 3: 全量）
- 增量 diff 同步 + sha256 hash 去重
- owner_agent 追踪

### 4.2 Task Switcher — 清晰任务切换
- Task Registry（SQLite tasks + active_task 表）
- Git Worktree 自动创建（`git worktree add -b`）
- 模糊项目匹配
- 状态校验：pending/active/done/blocked/bug

### 4.3 Command Proxy — 手机实现 CLI 功能
- 命令解析 + 异步路由
- 支持: `/switch` `/status` `/ask` `/browser` `/screenshot` `/commit` `/test`
- 4096 字符截断 + 错误处理

### 4.4 Telegram Gateway — Bot 入口
- Python Telegram Bot 框架
- 消息 → CommandProxy → 回复
- `/start` 欢迎命令
- 纯文本自动加 `/ask` 前缀

### 4.5 Notification Hub（Phase 1）— 待开发
- Critical/Normal/Info 三级推送

### 4.6 Desktop API（Phase 1）— 待开发
- FastAPI + AppleScript/PowerShell
- `/browser <url>` 打开 Chrome
- `/screenshot` 截图发回手机

---

## 五、Phase 0 完成状态 ✅

| 模块 | 文件 | 测试数 | 状态 |
|------|------|--------|------|
| Context Registry | `src/context_registry.py` | 14 passed | ✅ |
| Task Switcher | `src/task_switcher.py` | 17 passed | ✅ |
| Command Proxy | `src/command_proxy.py` | 17 passed | ✅ |
| Telegram Gateway | `src/gateway.py` | 11 passed | ✅ |
| **端到端验证** | 手机 `/status` | 任务列表回复 | ✅ |

**交付物**:
- `src/context_registry.py` — SQLite 上下文管理
- `src/task_switcher.py` — 任务注册表 + Git Worktree
- `src/command_proxy.py` — 命令路由
- `src/gateway.py` — Telegram Bot 入口（含 `__main__` 启动代码）
- `tests/` — 59 个 pytest 全部通过
- `scripts/verify.py` — 跨平台一键验证
- `MAC-DEPLOY.md` — Mac 部署指南
- `NEXT-STEPS.md` — 完整下一步指南

---

## 六、关键决策记录

1. **Mac 为统一 Hub**: Win 退化为远程执行节点，所有操作通过单一 Telegram Bot 入口
2. **Context 引用而非复制**: Agent 通过 TaskID + tier 参数按需拉取，不 copy-paste
3. **Git Worktree 隔离**: 每个任务一个分支 + 一个目录，Agent 之间不冲突
4. **不在 Session 管理层重复造轮子**: Agent Deck 已覆盖 80% 需求
5. **差异化创新点在「调度算法」层**: 人机时间交错调度是核心差异化
6. **OOO Blueprint 核心原则**: Mac 为统一 Hub，单一 Telegram Bot 入口

---

## 七、待办清单（按优先级）

### Phase 1（本周）
- [ ] Notification Hub 集成（CLI wrapper hook，捕获退出码推送）
- [ ] Win Desktop API 部署（PowerShell HTTP API）
- [ ] Tailscale 稳定化（Win 开机自启 + 进程守护）
- [ ] Mac brew 重装 Tailscale（解决 SSH 限制）

### Phase 2（下周）
- [ ] 完整 Command Proxy（所有 /commands 映射实现）
- [ ] 5 角色 Agent 的 AGENTS.md 定义
- [ ] Context 3-tier 渐进式披露接入 KimiCode/Hermes
- [ ] 多 Agent 状态看板

### Phase 3（后续）
- [ ] 调度大脑原型（人类注意力检测 + 简单调度算法）
- [ ] 集成 claude-mem（作为 Context Registry Tier 3 数据源）
- [ ] 评估 paperclip 替换自建调度层

---

## 八、部署踩坑记录

| Bug | 原因 | 修复 |
|-----|------|------|
| `/status` 无回复 | `MessageHandler(filters.TEXT & ~filters.COMMAND)` 过滤了所有命令 | 改为 `filters.TEXT` |
| Gateway 启动无反应 | 缺少 `if __name__ == "__main__"` 入口 | 添加启动代码 |
| `ImportError: socksio` | Mac SOCKS 代理需要额外包 | `pip install socksio` |
| `unable to open database file` | `~/.muon/context.db` 的 `~` 未展开 | `os.path.expanduser()` |
| `__pycache__` 缓存旧代码 | Python 加载 .pyc 不重新编译 | `find . -type d -name "__pycache__" -exec rm -rf {} +` |
| Git push SSL 错误 | 网络代理/防火墙干扰 | 多尝试几次或换 SSH |

---

## 九、GitHub Stars 关键项目

| 项目 | Stars | 价值 |
|------|-------|------|
| paperclipai/paperclip | 67.2k | 多 Agent orchestration 平台，可替换自建调度大脑 |
| thedotmack/claude-mem | 77.6k | 跨会话持久记忆，支持所有 CLI |
| farion1231/cc-switch | 78.5k | 统一管理 6 个 CLI 配置 |
| tinyhumansai/openhuman | 25.9k | 个人 AI OS，知识中枢 |
| MiroFish | 61.6k | 千级 Agent 群体智能参考 |
| TradingAgents-CN | 27.1k | 图驱动 Agent 编排参考 |

---

## 十、新 Session 加载步骤

### 方法 A：GitHub 同步（推荐）

```bash
# 1. 克隆仓库（新机器）
git clone https://github.com/ToussaintKnight/muon-core.git
cd muon-core/.muon

# 2. 一键验证
python3 scripts/verify.py

# 3. 配置 Telegram Bot（手动填入 token）
mkdir -p ~/.muon
cat > ~/.muon/config.yaml << 'EOF'
telegram:
  bot_token: "YOUR_BOT_TOKEN_HERE"
  user_chat_id: "YOUR_CHAT_ID_HERE"
EOF

# 4. 启动 Gateway
.venv/bin/python -m src.gateway
```

### 方法 B：读取此恢复包

在新 session 中直接发送此文件（`CONTEXT-RESTORE.md`），AI 会读取并恢复全部上下文。

---

## 十一、当前活跃任务

- **muon-test-1**: muon-core / feature/telegram-bot / hermes / pending
- 上下文: Telegram Gateway integration, 测试 /status 和 /switch

---

_此文件由 AI 在 2026-05-23 生成，用于跨 session / 跨设备上下文恢复。_
