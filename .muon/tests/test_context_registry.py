"""
Test Driven Development for Context Registry.

Tests cover:
- Database schema initialization
- 3-tier context retrieval (summary/detail/full)
- Incremental diff tracking (delta sync)
- Context hash deduplication (skip reload when unchanged)
- Edge cases: missing task, empty context, concurrent updates
"""

import pytest


class TestContextRegistryInit:
    """Tests for database schema initialization."""

    def test_creates_contexts_table(self, temp_registry):
        tables = temp_registry.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "contexts" in table_names
        assert "context_deltas" in table_names

    def test_contexts_table_schema(self, temp_registry):
        cols = temp_registry.conn.execute("PRAGMA table_info(contexts)").fetchall()
        col_names = [c[1] for c in cols]
        expected = [
            "task_id", "tier1_summary", "tier2_detail", "tier3_full",
            "context_hash", "last_updated", "owner_agent"
        ]
        for col in expected:
            assert col in col_names

    def test_deltas_table_schema(self, temp_registry):
        cols = temp_registry.conn.execute("PRAGMA table_info(context_deltas)").fetchall()
        col_names = [c[1] for c in cols]
        expected = [
            "id", "task_id", "agent_name", "delta",
            "old_hash", "new_hash", "timestamp"
        ]
        for col in expected:
            assert col in col_names


class TestContextRetrieval:
    """Tests for 3-tier progressive disclosure."""

    def test_get_tier1_returns_summary_only(self, temp_registry):
        temp_registry.create_context(
            task_id="task-1",
            tier1="Fix login bug",
            tier2="Auth module needs refactor, blocked by OAuth config",
            tier3="Full conversation history..."
        )
        ctx = temp_registry.get_context("task-1", tier=1)
        assert ctx["summary"] == "Fix login bug"
        assert ctx["detail"] is None
        assert ctx["full"] is None
        assert ctx["hash"] is not None

    def test_get_tier2_returns_summary_and_detail(self, temp_registry):
        temp_registry.create_context(
            task_id="task-1",
            tier1="Fix login bug",
            tier2="Auth module needs refactor",
            tier3="Full conversation history..."
        )
        ctx = temp_registry.get_context("task-1", tier=2)
        assert ctx["summary"] == "Fix login bug"
        assert ctx["detail"] == "Auth module needs refactor"
        assert ctx["full"] is None

    def test_get_tier3_returns_all(self, temp_registry):
        temp_registry.create_context(
            task_id="task-1",
            tier1="Fix login bug",
            tier2="Auth module needs refactor",
            tier3="Full conversation history..."
        )
        ctx = temp_registry.get_context("task-1", tier=3)
        assert ctx["summary"] == "Fix login bug"
        assert ctx["detail"] == "Auth module needs refactor"
        assert ctx["full"] == "Full conversation history..."

    def test_get_missing_task_returns_none(self, temp_registry):
        assert temp_registry.get_context("nonexistent") is None


class TestContextUpdate:
    """Tests for incremental diff tracking and hash dedup."""

    def test_update_creates_delta_entry(self, temp_registry):
        temp_registry.create_context(task_id="task-1", tier1="Initial", tier2="Detail", tier3="Old full context")

        old_hash = temp_registry.get_context("task-1")["hash"]
        temp_registry.update_context("task-1", agent="kimicode", new_full="New full context with changes")

        deltas = temp_registry.conn.execute(
            "SELECT * FROM context_deltas WHERE task_id=?", ("task-1",)
        ).fetchall()
        assert len(deltas) == 1
        assert deltas[0][2] == "kimicode"  # agent_name
        assert deltas[0][3] != ""  # delta not empty
        assert deltas[0][4] == old_hash  # old_hash matches
        assert deltas[0][5] != old_hash  # new_hash different

    def test_update_changes_context_hash(self, temp_registry):
        temp_registry.create_context(task_id="task-1", tier1="Initial", tier2="Detail", tier3="Old")
        old_hash = temp_registry.get_context("task-1")["hash"]

        temp_registry.update_context("task-1", agent="kimicode", new_full="New")
        new_hash = temp_registry.get_context("task-1")["hash"]

        assert new_hash != old_hash
        assert temp_registry.get_context("task-1")["owner"] == "kimicode"

    def test_identical_content_no_redundant_delta(self, temp_registry):
        """If content unchanged, should not create a delta entry."""
        temp_registry.create_context(task_id="task-1", tier1="Initial", tier2="Detail", tier3="Same")
        old_hash = temp_registry.get_context("task-1")["hash"]

        temp_registry.update_context("task-1", agent="kimicode", new_full="Same")
        new_hash = temp_registry.get_context("task-1")["hash"]

        # Hash should be same
        assert new_hash == old_hash
        # No delta should be created for identical content
        deltas = temp_registry.conn.execute(
            "SELECT * FROM context_deltas WHERE task_id=?", ("task-1",)
        ).fetchall()
        assert len(deltas) == 0

    def test_delta_computation_is_readable(self, temp_registry):
        """Delta should be human-readable, not binary gibberish."""
        old = "Line 1\nLine 2\nLine 3"
        new = "Line 1\nLine 2 modified\nLine 3\nLine 4"
        temp_registry.create_context(task_id="task-1", tier1="Test", tier2="Detail", tier3=old)

        temp_registry.update_context("task-1", agent="claude", new_full=new)
        deltas = temp_registry.conn.execute(
            "SELECT delta FROM context_deltas WHERE task_id=?", ("task-1",)
        ).fetchall()
        assert len(deltas) == 1
        delta_text = deltas[0][0]
        # Delta should contain the changed line
        assert "modified" in delta_text or "Line 4" in delta_text


class TestContextOwnership:
    """Tests for owner_agent tracking."""

    def test_create_sets_no_owner(self, temp_registry):
        temp_registry.create_context(task_id="task-1", tier1="Test", tier2="Detail", tier3="Full")
        ctx = temp_registry.get_context("task-1")
        assert ctx["owner"] is None

    def test_update_sets_owner(self, temp_registry):
        temp_registry.create_context(task_id="task-1", tier1="Test", tier2="Detail", tier3="Full")
        temp_registry.update_context("task-1", agent="hermes", new_full="Updated")
        assert temp_registry.get_context("task-1")["owner"] == "hermes"

    def test_update_changes_owner(self, temp_registry):
        temp_registry.create_context(task_id="task-1", tier1="Test", tier2="Detail", tier3="Full")
        temp_registry.update_context("task-1", agent="hermes", new_full="V1")
        temp_registry.update_context("task-1", agent="oc", new_full="V2")
        assert temp_registry.get_context("task-1")["owner"] == "oc"
