#!/usr/bin/env python3
"""
Cross-platform verification script for muon-core Phase 0.

Automatically detects OS, checks prerequisites, installs dependencies,
and runs the full test suite. Designed to run on both macOS and Windows.

Usage:
    python scripts/verify.py          # Full verification
    python scripts/verify.py --quick  # Skip tests, just check env
"""

import sys
import os
import subprocess
import platform
import argparse
from pathlib import Path


def print_section(title: str):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


def check_python_version() -> bool:
    """Check Python >= 3.10."""
    version = sys.version_info
    ok = version >= (3, 10)
    print(f"  Python: {version.major}.{version.minor}.{version.micro} {'OK' if ok else 'FAIL (need >= 3.10)'}")
    return ok


def check_git() -> bool:
    """Check git is available."""
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True)
        print(f"  Git: {result.stdout.strip()} OK")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  Git: NOT FOUND (required for Task Switcher worktree tests)")
        return False


def check_dependencies() -> bool:
    """Check if pytest is installed."""
    try:
        import pytest  # noqa: F401
        print("  pytest: installed OK")
        return True
    except ImportError:
        print("  pytest: NOT FOUND")
        return False


def install_dependencies(project_root: Path) -> tuple[bool, Path | None]:
    """Install requirements.txt. Returns (success, venv_python_path)."""
    req_file = project_root / "requirements.txt"
    if not req_file.exists():
        print("  requirements.txt not found, skipping install")
        return True, None

    print("  Installing dependencies from requirements.txt...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("  Dependencies installed OK")
        return True, None

    # Handle externally-managed environments (macOS brew Python, etc.)
    if "externally-managed" in result.stderr:
        print("  Detected externally-managed environment.")
        venv_dir = project_root / ".venv"
        venv_python = venv_dir / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python3")

        if not venv_dir.exists():
            print("  Creating virtual environment (.venv)...")
            venv_result = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                capture_output=True, text=True
            )
            if venv_result.returncode != 0:
                print(f"  venv creation failed: {venv_result.stderr[:200]}")
                return False, None
            print("  Virtual environment created.")

        print("  Installing into virtual environment...")
        result = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", str(req_file)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  Dependencies installed in venv OK")
            return True, venv_python
        else:
            print(f"  venv install failed: {result.stderr[:200]}")
            return False, None
    else:
        print(f"  Install failed: {result.stderr[:200]}")
        return False, None


def run_tests(project_root: Path, venv_python: Path | None = None) -> bool:
    """Run full pytest suite. Optionally use venv python."""
    python = str(venv_python) if venv_python else sys.executable
    print("  Running tests...")
    result = subprocess.run(
        [python, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(project_root),
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        return False
    return True


def check_paths(project_root: Path) -> bool:
    """Check that expected files exist."""
    required = ["src/context_registry.py", "src/task_switcher.py", "src/command_proxy.py"]
    all_ok = True
    for f in required:
        path = project_root / f
        ok = path.exists()
        print(f"  {f}: {'OK' if ok else 'MISSING'}")
        all_ok = all_ok and ok
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Verify muon-core Phase 0 setup")
    parser.add_argument("--quick", action="store_true", help="Skip tests, just check environment")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    os_name = platform.system()

    print_section(f"muon-core Phase 0 Verification ({os_name})")
    print(f"  Project root: {project_root}")

    # Phase 1: Environment
    print_section("1. Environment Check")
    env_ok = check_python_version() and check_git()

    # Phase 2: Dependencies
    print_section("2. Dependencies")
    deps_ok = check_dependencies()
    venv_python = None
    if not deps_ok:
        deps_ok, venv_python = install_dependencies(project_root)

    # Phase 3: Files
    print_section("3. Project Files")
    files_ok = check_paths(project_root)

    if args.quick:
        print_section("Result (--quick mode, tests skipped)")
        if env_ok and deps_ok and files_ok:
            print("  All checks passed. Ready for testing.")
            return 0
        else:
            print("  Some checks failed. See above.")
            return 1

    # Phase 4: Tests
    print_section("4. Test Suite")
    tests_ok = run_tests(project_root, venv_python)

    # Summary
    print_section("Summary")
    results = {
        "Environment": env_ok,
        "Dependencies": deps_ok,
        "Files": files_ok,
        "Tests": tests_ok
    }
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")

    all_ok = all(results.values())
    if all_ok:
        print("\n  Phase 0 verification complete. All systems go.")
        return 0
    else:
        print("\n  Some checks failed. Fix issues above and re-run.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
