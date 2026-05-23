"""Context Registry - SQLite-backed context storage with 3-tier disclosure and incremental diff tracking.

Design fixes from blueprint v1.0:
- Removed project/branch duplication (Task Registry owns those)
- Added create_context() for clean initialization
- Implemented _compute_delta() using difflib for human-readable output
- Added hash deduplication to skip redundant deltas
- Added error handling for missing tasks
"""

import sqlite3
import hashlib
import difflib
from datetime import datetime


class ContextRegistry:
    """Manages shared context across all agents with token-efficient progressive disclosure."""

    def __init__(self, db_path: str = "~/.muon/context.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Initialize database schema for contexts and deltas."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
                task_id TEXT PRIMARY KEY,
                tier1_summary TEXT NOT NULL,
                tier2_detail TEXT,
                tier3_full TEXT,
                context_hash TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                owner_agent TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS context_deltas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                delta TEXT NOT NULL,
                old_hash TEXT,
                new_hash TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_deltas_task ON context_deltas(task_id)
        """)
        self.conn.commit()

    def create_context(
        self,
        task_id: str,
        tier1: str,
        tier2: str = "",
        tier3: str = "",
        owner_agent: str = None
    ) -> None:
        """Create a new context entry. Called when a task is first registered."""
        full_hash = self._hash_content(tier3) if tier3 else ""
        self.conn.execute("""
            INSERT INTO contexts (task_id, tier1_summary, tier2_detail, tier3_full, context_hash, owner_agent)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (task_id, tier1, tier2, tier3, full_hash, owner_agent))
        self.conn.commit()

    def get_context(self, task_id: str, tier: int = 1) -> dict | None:
        """Retrieve context with progressive disclosure.

        Tier 1: Always returns summary.
        Tier 2: Returns summary + detail.
        Tier 3: Returns summary + detail + full context.
        """
        if tier not in (1, 2, 3):
            raise ValueError(f"tier must be 1, 2, or 3, got {tier}")

        row = self.conn.execute(
            "SELECT tier1_summary, tier2_detail, tier3_full, context_hash, owner_agent "
            "FROM contexts WHERE task_id=?",
            (task_id,)
        ).fetchone()

        if row is None:
            return None

        return {
            "summary": row["tier1_summary"],
            "detail": row["tier2_detail"] if tier >= 2 else None,
            "full": row["tier3_full"] if tier >= 3 else None,
            "hash": row["context_hash"],
            "owner": row["owner_agent"]
        }

    def update_context(self, task_id: str, agent: str, new_full: str) -> bool:
        """Update full context with incremental diff tracking.

        Returns True if a delta was recorded, False if content was identical.
        """
        old = self.conn.execute(
            "SELECT tier3_full, context_hash FROM contexts WHERE task_id=?",
            (task_id,)
        ).fetchone()

        if old is None:
            raise KeyError(f"Task {task_id} not found in context registry")

        old_full = old["tier3_full"] or ""
        old_hash = old["context_hash"] or ""
        new_hash = self._hash_content(new_full)

        # Hash deduplication: skip if content unchanged
        if new_hash == old_hash:
            return False

        # Compute human-readable delta
        delta = self._compute_delta(old_full, new_full)

        # Record delta
        self.conn.execute("""
            INSERT INTO context_deltas (task_id, agent_name, delta, old_hash, new_hash)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, agent, delta, old_hash, new_hash))

        # Update context
        self.conn.execute("""
            UPDATE contexts
            SET tier3_full=?, context_hash=?, last_updated=?, owner_agent=?
            WHERE task_id=?
        """, (new_full, new_hash, datetime.now().isoformat(), agent, task_id))

        self.conn.commit()
        return True

    def get_delta_history(self, task_id: str, limit: int = 10) -> list[dict]:
        """Get recent delta entries for a task."""
        rows = self.conn.execute(
            "SELECT agent_name, delta, old_hash, new_hash, timestamp "
            "FROM context_deltas WHERE task_id=? ORDER BY timestamp DESC LIMIT ?",
            (task_id, limit)
        ).fetchall()
        return [
            {
                "agent": r["agent_name"],
                "delta": r["delta"],
                "old_hash": r["old_hash"],
                "new_hash": r["new_hash"],
                "timestamp": r["timestamp"]
            }
            for r in rows
        ]

    def _hash_content(self, content: str) -> str:
        """Generate 16-char hash for content deduplication."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _compute_delta(self, old: str, new: str) -> str:
        """Compute human-readable unified diff between two strings."""
        old_lines = old.splitlines(keepends=True) or [""]
        new_lines = new.splitlines(keepends=True) or [""]

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="previous",
            tofile="current",
            lineterm=""
        )
        return "".join(diff)

    def close(self):
        """Close database connection."""
        self.conn.close()
