#!/usr/bin/env python3
"""Diagnose why Desktop API isn't reachable from Tailscale."""

import socket
import subprocess
import sys


def run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        return e.output


def main():
    print("=" * 50)
    print("Muon Desktop API 网络诊断")
    print("=" * 50)

    # 1. Check what's listening on 8001
    print("\n[1] 端口 8001 监听状态:")
    print(run("lsof -i :8001 | head -5"))

    # 2. Check if 0.0.0.0 or 127.0.0.1
    print("\n[2] 绑定地址详情:")
    print(run("netstat -anv | grep 8001 | head -5"))

    # 3. Tailscale IP
    print("\n[3] Tailscale IP:")
    print(run("tailscale ip -4"))

    # 4. Tailscale status
    print("\n[4] Tailscale 状态:")
    print(run("tailscale status | head -5"))

    # 5. macOS firewall status
    print("\n[5] macOS 防火墙状态:")
    print(run("sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate"))

    # 6. Self-test from localhost
    print("\n[6] 本机自测 (127.0.0.1:8001):")
    try:
        s = socket.create_connection(("127.0.0.1", 8001), timeout=2)
        s.close()
        print("   ✅ 127.0.0.1:8001 可达")
    except Exception as e:
        print(f"   ❌ {e}")

    # 7. Self-test from Tailscale IP
    print("\n[7] 本机 Tailscale IP 自测:")
    ts_ip = run("tailscale ip -4").strip().split("\n")[0]
    try:
        s = socket.create_connection((ts_ip, 8001), timeout=2)
        s.close()
        print(f"   ✅ {ts_ip}:8001 可达")
    except Exception as e:
        print(f"   ❌ {e}")

    # 8. Check if uvicorn is binding to all interfaces
    print("\n[8] Uvicorn 进程参数:")
    print(run("ps aux | grep uvicorn | grep -v grep"))

    print("\n" + "=" * 50)
    print("常见修复方案:")
    print("  A) 如果是防火墙问题，临时关闭测试:")
    print("     sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate off")
    print("  B) 如果绑定在 127.0.0.1，改绑 Tailscale IP:")
    print(f"     MUON_DESKTOP_HOST={ts_ip} .venv/bin/python -m src.desktop_api")
    print("  C) 给 Python 加防火墙例外:")
    print("     sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add $(which python3)")
    print("=" * 50)


if __name__ == "__main__":
    main()
