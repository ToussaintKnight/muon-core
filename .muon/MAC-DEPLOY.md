# Mac 部署指南 — 一键验证

> 目标：把 Win 上开发的代码放到 Mac 上跑通，确认跨平台兼容。
> 原则：能自动的绝不手动，只留必要的手动步骤。

---

## 自动步骤（复制粘贴执行）

### 1. 同步代码到 Mac

在 **Mac 终端**执行：

```bash
# 如果你用 git 管理 muon-core 项目
cd ~/projects/muon-core
# 确保 .muon/ 目录已提交到 git
git pull

# 如果没有 git，用 Tailscale + scp（Win 上执行这条）
# scp -r .muon/ knight@100.91.29.68:~/projects/muon-core/
```

### 2. 一键验证

在 **Mac 终端**执行：

```bash
cd ~/projects/muon-core/.muon
python3 scripts/verify.py
```

预期输出：
```
  Environment: PASS
  Dependencies: PASS
  Files: PASS
  Tests: PASS
  Phase 0 verification complete. All systems go.
```

如果 `pytest` 没装，脚本会自动 `pip install`。

### 3. 快速验证（跳过测试，只看环境）

```bash
python3 scripts/verify.py --quick
```

---

## 手动步骤（只有这一步必须手动）

### 4. 配置 Telegram Bot Token

```bash
# 创建配置文件
cat > ~/.muon/config.yaml << 'EOF'
telegram:
  bot_token: "YOUR_BOT_TOKEN_HERE"
  user_chat_id: "YOUR_CHAT_ID_HERE"
EOF
```

获取方式：
- @BotFather → `/newbot` → 复制 token
- 给 Bot 发一条消息 → 访问 `https://api.telegram.org/bot<token>/getUpdates` → 找 `chat.id`

---

## 跨平台已知差异

| 项目 | Win | Mac | 处理方案 |
|------|-----|-----|---------|
| 路径分隔符 | `\` | `/` | Python `pathlib` / `os.path` 自动处理 |
| 用户目录 | `C:\Users\Mother` | `/Users/knight` | `os.path.expanduser("~")` 自动处理 |
| Git Worktree | 支持 | 支持 | 统一使用 `git worktree add -b` |
| Python 版本 | 3.13.12 | 需 >= 3.10 | verify.py 自动检查 |
| SQLite | 内置 | 内置 | 无需额外安装 |

代码本身无平台依赖，**理论上 Mac 零改动直接跑**。

---

## 如果验证失败

| 症状 | 解决方案 |
|------|---------|
| `git: command not found` | `brew install git` |
| `pytest: not found` | 脚本会自动安装，若失败则 `pip3 install pytest pytest-asyncio` |
| `PermissionError` on db | 确保脚本有写临时文件权限（`chmod 755 scripts/verify.py`） |
| Worktree 测试失败 | 确保 git >= 2.40（`git --version`） |

---

## 验证通过后

```bash
# 启动 Telegram Gateway（Phase 0 最后一步）
python3 -m src.gateway
```

手机上发 `/status`，Bot 应该回复任务列表。
