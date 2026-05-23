"""
Test Driven Development for Task Switcher.

Tests cover:
- Task creation and registration
- Task listing with project filtering and fuzzy matching
- Active task tracking
- Task switching (worktree validation, git status)
- Integration with Context Registry
"""

import pytest
import tempfile
import os
import subprocess
from src.task_switcher import TaskSwitcher
from src.context_registry import ContextRegistry


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for worktree tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "muon-core")
        os.makedirs(repo)
        subprocess.run(["git", "-C", repo, "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "config", "user.email", "test@test.com"], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "config", "user.name", "Test"], check=True, capture_output=True)
        # Create initial commit on main
        with open(os.path.join(repo, "README.md"), "w") as f:
            f.write("# Test repo\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "commit", "-m", "init"], check=True, capture_output=True)
        # Rename to main if needed
        subprocess.run(["git", "-C", repo, "branch", "-m", "main"], check=True, capture_output=True)
        yield repo


@pytest.fixture
def task_switcher(temp_registry, temp_git_repo):
    """Provide a TaskSwitcher with temporary registry and git repo."""
    return TaskSwitcher(
        context_registry=temp_registry,
        base_dir=os.path.dirname(temp_git_repo)
    )


class TestTaskCreation:
    """Tests for registering new tasks."""

    def test_create_task_inserts_record(self, task_switcher):
        task_switcher.create_task(
            task_id="muon-42",
            project="muon-core",
            branch="feature/auth",
            assigned_agent="kimicode"
        )
        tasks = task_switcher.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "muon-42"
        assert tasks[0]["project"] == "muon-core"
        assert tasks[0]["branch"] == "feature/auth"
        assert tasks[0]["assigned_agent"] == "kimicode"
        assert tasks[0]["status"] == "pending"

    def test_create_task_generates_worktree_path(self, task_switcher, temp_git_repo):
        task_switcher.create_task(
            task_id="muon-42",
            project="muon-core",
            branch="feature/auth",
            assigned_agent="kimicode"
        )
        tasks = task_switcher.list_tasks()
        # branch "feature/auth" -> safe "feature--auth"
        expected_path = os.path.join(
            os.path.dirname(temp_git_repo),
            "muon-core--feature--auth"
        )
        assert tasks[0]["worktree_path"] == expected_path

    def test_create_task_with_context(self, task_switcher, temp_registry):
        task_switcher.create_task(
            task_id="muon-42",
            project="muon-core",
            branch="feature/auth",
            assigned_agent="kimicode",
            tier1="Auth refactor",
            tier2="OAuth2 config needs update"
        )
        ctx = temp_registry.get_context("muon-42", tier=2)
        assert ctx["summary"] == "Auth refactor"
        assert ctx["detail"] == "OAuth2 config needs update"


class TestTaskListing:
    """Tests for listing and filtering tasks."""

    def test_list_all_tasks(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        task_switcher.create_task("task-2", "muon-core", "fix/b", "claude")
        task_switcher.create_task("task-3", "other-proj", "feature/c", "hermes")
        tasks = task_switcher.list_tasks()
        assert len(tasks) == 3

    def test_filter_by_project(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        task_switcher.create_task("task-2", "muon-core", "fix/b", "claude")
        task_switcher.create_task("task-3", "other-proj", "feature/c", "hermes")
        tasks = task_switcher.list_tasks(project="muon-core")
        assert len(tasks) == 2
        assert all(t["project"] == "muon-core" for t in tasks)

    def test_fuzzy_match_project(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        tasks = task_switcher.list_tasks(fuzzy="muon")
        assert len(tasks) == 1

    def test_fuzzy_match_no_results(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        tasks = task_switcher.list_tasks(fuzzy="nonexistent")
        assert len(tasks) == 0


class TestActiveTask:
    """Tests for active task tracking."""

    def test_no_active_task_returns_none(self, task_switcher):
        assert task_switcher.get_active_task() is None

    def test_set_active_task(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        task_switcher.set_active_task("task-1")
        assert task_switcher.get_active_task() == "task-1"

    def test_switch_sets_active_task(self, task_switcher, temp_git_repo):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        # _create_worktree will create the branch via 'git worktree add -b'
        result = task_switcher.switch("task-1")
        assert task_switcher.get_active_task() == "task-1"
        assert result["task_id"] == "task-1"


class TestTaskSwitching:
    """Tests for task switch operation."""

    def test_switch_creates_worktree(self, task_switcher, temp_git_repo):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        # _create_worktree creates branch via 'git worktree add -b'
        task_switcher.switch("task-1")
        worktree_path = os.path.join(
            os.path.dirname(temp_git_repo), "muon-core--feature--a"
        )
        assert os.path.exists(worktree_path)
        assert os.path.exists(os.path.join(worktree_path, ".git"))

    def test_switch_returns_git_status(self, task_switcher, temp_git_repo):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        # _create_worktree creates branch via 'git worktree add -b'
        result = task_switcher.switch("task-1")
        assert "task_id" in result
        assert "project" in result
        assert "branch" in result
        assert "git_status" in result

    def test_switch_nonexistent_task_raises(self, task_switcher):
        with pytest.raises(KeyError):
            task_switcher.switch("nonexistent")

    def test_switch_injects_context(self, task_switcher, temp_registry, temp_git_repo):
        task_switcher.create_task(
            "task-1", "muon-core", "feature/a", "kimicode",
            tier1="Auth fix", tier2="Update OAuth config"
        )
        # _create_worktree creates branch via 'git worktree add -b'
        task_switcher.switch("task-1")
        # Context should be accessible
        ctx = temp_registry.get_context("task-1", tier=2)
        assert ctx["summary"] == "Auth fix"


class TestTaskStatus:
    """Tests for task status management."""

    def test_default_status_is_pending(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        tasks = task_switcher.list_tasks()
        assert tasks[0]["status"] == "pending"

    def test_update_status(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        task_switcher.update_status("task-1", "active")
        tasks = task_switcher.list_tasks()
        assert tasks[0]["status"] == "active"

    def test_invalid_status_rejected(self, task_switcher):
        task_switcher.create_task("task-1", "muon-core", "feature/a", "kimicode")
        with pytest.raises(ValueError):
            task_switcher.update_status("task-1", "invalid_status")
