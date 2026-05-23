#!/usr/bin/env python3
"""Debug empty-reply issue from Win11 to Mac Desktop API."""

import subprocess
import sys

def run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        return e.output

print("=" * 50)
print("Empty Reply 诊断")
print("=" * 50)

# 1. 确认 8001 上的进程到底是谁
print("\n[1] 端口 8001 占用详情:")
print(run("lsof -i :8001 | grep LISTEN"))

# 2. 本机 localhost 测试
print("\n[2] 本机 localhost 测试:")
print(run("curl -s http://127.0.0.1:8001/ | head -c 200"))

# 3. 本机 Tailscale IP 测试
print("\n[3] 本机 Tailscale IP 测试:")
ts_ip = run("tailscale ip -4").strip().split("\n")[0]
print(run(f"curl -s http://{ts_ip}:8001/ | head -c 200"))

# 4. 检查有没有其他服务占了这个端口
print("\n[4] 检查端口冲突:")
print(run("netstat -anv | grep 8001 | grep LISTEN"))

# 5. Uvicorn 进程完整命令行
print("\n[5] Uvicorn 进程命令行:")
print(run("ps aux | grep 'src.desktop_api' | grep -v grep"))

# 6. 换个端口测试（排除端口被污染）
print("\n[6] 换端口 8006 启动测试服务器:")
print("建议手动执行: MUON_DESKTOP_PORT=8006 .venv/bin/python -m src.desktop_api")
print("然后 Win11 测试: curl.exe http://100.91.29.68:8006/")

print("\n" + "=" * 50)
