"""Task Switcher - Manages task registry, worktree isolation, and context-aware switching.

Design fixes from blueprint v1.0:
- Added create_task() with optional context creation
- Implemented _get_task() and fuzzy matching
- Added active_task tracking
- Added status validation (pending/active/done/blocked/bug)
- Worktree path auto-generated from project + branch
- Error handling for missing tasks and git failures
"""

import sqlite3
import os
import subprocess
from datetime import datetime
from src.context_registry import ContextRegistry


VALID_STATUSES = {"pending", "active", "done", "blocked", "bug"}


class TaskSwitcher:
    """Manages task lifecycle: creation, listing, switching, and worktree isolation."""

    def __init__(
        self,
        context_registry: ContextRegistry,
        base_dir: str = "~/projects"
    ):
        self.context_registry = context_registry
        self.base_dir = os.path.expanduser(base_dir)
        self.conn = context_registry.conn  # Share connection with Context Registry
        self._init_db()

    def _init_db(self):
        """Initialize Task Registry tables in the shared database."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                branch TEXT NOT NULL,
                worktree_path TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                assigned_agent TEXT,
                context_tier INTEGER DEFAULT 2,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS active_task (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                task_id TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        """)
        self.conn.commit()

    def create_task(
        self,
        task_id: str,
        project: str,
        branch: str,
        assigned_agent: str,
        tier1: str = "",
        tier2: str = "",
        tier3: str = "",
        context_tier: int = 2
    ) -> None:
        """Register a new task with optional context initialization."""
        worktree_path = self._worktree_path(project, branch)

        self.conn.execute("""
            INSERT INTO tasks (task_id, project, branch, worktree_path, assigned_agent, context_tier)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (task_id, project, branch, worktree_path, assigned_agent, context_tier))
        self.conn.commit()

        # Initialize context if provided
        if tier1:
            self.context_registry.create_context(
                task_id=task_id,
                tier1=tier1,
                tier2=tier2,
                tier3=tier3
            )

    def list_tasks(self, project: str = None, fuzzy: str = None) -> list[dict]:
        """List tasks with optional filtering.

        Args:
            project: Exact project name filter
            fuzzy: Substring match on project name
        """
        if project:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE project=? ORDER BY updated_at DESC",
                (project,)
            ).fetchall()
        elif fuzzy:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE project LIKE ? ORDER BY updated_at DESC",
                (f"%{fuzzy}%",)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC"
            ).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_task(self, task_id: str) -> dict | None:
        """Get a single task by ID."""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_active_task(self) -> str | None:
        """Get the currently active task ID."""
        row = self.conn.execute(
            "SELECT task_id FROM active_task WHERE id=1"
        ).fetchone()
        return row["task_id"] if row else None

    def set_active_task(self, task_id: str) -> None:
        """Set the active task."""
        if not self.get_task(task_id):
            raise KeyError(f"Task {task_id} not found")

        self.conn.execute("""
            INSERT INTO active_task (id, task_id, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                task_id=excluded.task_id,
                updated_at=excluded.updated_at
        """, (task_id, datetime.now().isoformat()))
        self.conn.commit()

    def switch(self, task_id: str) -> dict:
        """Switch to a task: ensure worktree exists, set active, return status."""
        task = self.get_task(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        # Ensure worktree exists
        if not os.path.exists(task["worktree_path"]):
            self._create_worktree(task["project"], task["branch"], task["worktree_path"])

        # Set as active
        self.set_active_task(task_id)

        # Update status to active
        self.update_status(task_id, "active")

        # Get git status
        git_status = self._git_status(task["worktree_path"])

        return {
            "task_id": task_id,
            "project": task["project"],
            "branch": task["branch"],
            "agent": task["assigned_agent"],
            "worktree_path": task["worktree_path"],
            "git_status": git_status
        }

    def update_status(self, task_id: str, status: str) -> None:
        """Update task status with validation."""
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}")

        self.conn.execute("""
            UPDATE tasks SET status=?, updated_at=? WHERE task_id=?
        """, (status, datetime.now().isoformat(), task_id))
        self.conn.commit()

    def _worktree_path(self, project: str, branch: str) -> str:
        """Generate worktree path from project and branch."""
        safe_branch = branch.replace("/", "--")
        return os.path.join(self.base_dir, f"{project}--{safe_branch}")

    def _create_worktree(self, project: str, branch: str, path: str):
        """Create a git worktree for the task.

        Uses 'git worktree add -b' to create a new branch from the default branch,
        avoiding conflicts when the branch is already checked out elsewhere.
        """
        repo = os.path.join(self.base_dir, project)
        if not os.path.exists(repo):
            raise FileNotFoundError(f"Project repository not found: {repo}")

        # Skip if worktree already exists
        if os.path.exists(path):
            return

        # Check if branch already exists
        result = subprocess.run(
            ["git", "-C", repo, "branch", "--list", branch],
            capture_output=True, text=True
        )

        if result.stdout.strip():
            # Branch exists - try to add worktree for it
            # This will fail if branch is already checked out elsewhere,
            # which is the expected behavior
            subprocess.run(
                ["git", "-C", repo, "worktree", "add", path, branch],
                check=True, capture_output=True
            )
        else:
            # Branch doesn't exist - create from default branch
            default_branch = self._get_default_branch(repo)
            subprocess.run(
                ["git", "-C", repo, "worktree", "add", "-b", branch, path, default_branch],
                check=True, capture_output=True
            )

    def _get_default_branch(self, repo: str) -> str:
        """Detect default branch (main or master)."""
        for branch in ["main", "master"]:
            result = subprocess.run(
                ["git", "-C", repo, "rev-parse", "--verify", branch],
                capture_output=True
            )
            if result.returncode == 0:
                return branch
        raise RuntimeError(f"No main or master branch found in {repo}")

    def _git_status(self, worktree_path: str) -> str:
        """Get git status for a worktree."""
        if not os.path.exists(worktree_path):
            return "worktree not found"

        result = subprocess.run(
            ["git", "-C", worktree_path, "status", "--short"],
            capture_output=True, text=True
        )
        status = result.stdout.strip()
        return status if status else "clean"

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a dictionary."""
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}
