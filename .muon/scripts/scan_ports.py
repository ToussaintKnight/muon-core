#!/usr/bin/env python3
"""Find what's REALLY listening on ports 8001-8010."""

import subprocess

def run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        return e.output

print("=" * 60)
print("端口占用全景扫描 (8000-8010)")
print("=" * 60)

for port in range(8000, 8011):
    print(f"\n--- Port {port} ---")
    # 用 sudo 确保看到所有进程
    out = run(f"sudo lsof -i :{port} 2>/dev/null || lsof -i :{port} 2>/dev/null")
    if out.strip():
        print(out)
    else:
        print("  (no process found)")

print("\n" + "=" * 60)
print("活跃连接扫描")
print("=" * 60)
print(run("netstat -an | grep -E '800[0-9]' | head -20"))

print("\n" + "=" * 60)
print("所有 LISTEN 状态的端口")
print("=" * 60)
print(run("sudo lsof -iTCP -sTCP:LISTEN | grep -E '800[0-9]' || lsof -iTCP -sTCP:LISTEN | grep -E '800[0-9]'"))

print("\n" + "=" * 60)
print("所有 Python 进程")
print("=" * 60)
print(run("ps aux | grep python | grep -v grep | grep -v 'diagnose'"))
