"""Tests for supersession chain integrity verification (#354).

Tests cover:
1. Healthy chains pass verification
2. Bidirectional mismatch detection
3. Non-monotonic timestamp detection
4. Cycle detection
5. Bad terminal status detection
6. Orphan detection (superseded_by_id points to non-existent belief)
7. Empty database (no chains)
8. Single-link chains
9. Multi-link chains
10. Limit parameter
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from valence.core.verification.chain_integrity import ChainIssue, ChainReport, verify_chains


def _uuid():
    return str(uuid4())


def _make_belief(id, status="active", supersedes_id=None, superseded_by_id=None, created_at=None):
    """Helper to make a mock belief row."""
    return {
        "id": id,
        "content": f"belief {id[:8]}",
        "status": status,
        "supersedes_id": supersedes_id,
        "superseded_by_id": superseded_by_id,
        "created_at": created_at or datetime.now(),
    }


class TestChainReport:
    """Test report dataclass."""

    def test_empty_report(self):
        report = ChainReport()
        assert report.total_chains == 0
        assert report.unhealthy_chains == 0
        assert "0" in str(report)

    def test_report_with_issues(self):
        report = ChainReport(total_chains=3, healthy_chains=2)
        report.issues.append(ChainIssue(chain_id="abc", issue_type="cycle", description="test"))
        assert report.unhealthy_chains == 1
        d = report.to_dict()
        assert d["total_chains"] == 3
        assert len(d["issues"]) == 1

    def test_str_includes_issue_types(self):
        report = ChainReport(total_chains=1, healthy_chains=0)
        report.issues.append(ChainIssue(chain_id="abc", issue_type="cycle", description="found a cycle"))
        s = str(report)
        assert "cycle" in s
        assert "found a cycle" in s


class TestChainIssue:
    """Test issue dataclass."""

    def test_to_dict(self):
        issue = ChainIssue(chain_id="abc", issue_type="orphan", description="test", belief_ids=["a", "b"])
        d = issue.to_dict()
        assert d["chain_id"] == "abc"
        assert d["issue_type"] == "orphan"
        assert len(d["belief_ids"]) == 2


class TestVerifyChainsHealthy:
    """Test healthy chains pass verification."""

    def test_no_chains(self):
        """Empty database = no issues."""
        cur = MagicMock()
        # chain heads query returns empty
        cur.fetchall.side_effect = [[], []]  # heads, orphans
        report = verify_chains(cur)
        assert report.total_chains == 0
        assert report.issues == []

    def test_single_link_healthy(self):
        """A -> B chain where everything is correct."""
        head_id = _uuid()
        old_id = _uuid()
        now = datetime.now()
        earlier = now - timedelta(hours=1)

        head_row = _make_belief(head_id, status="active", supersedes_id=old_id, created_at=now)

        cur = MagicMock()
        # Query 1: chain heads
        # Query 2: orphans
        cur.fetchall.side_effect = [
            [head_row],  # chain heads
            [],  # orphans
        ]
        # fetchone calls during chain walk:
        # 1. fetch head belief
        # 2. check older belief's superseded_by_id
        # 3. fetch older belief (the one supersedes_id points to)
        cur.fetchone.side_effect = [
            # Walk: fetch head
            _make_belief(head_id, status="active", supersedes_id=old_id, created_at=now),
            # Bidir check: older.superseded_by_id should be head_id
            {"superseded_by_id": head_id},
            # Walk: fetch older belief
            _make_belief(old_id, status="superseded", supersedes_id=None, superseded_by_id=head_id, created_at=earlier),
        ]

        report = verify_chains(cur)
        assert report.total_chains == 1
        assert report.healthy_chains == 1
        assert report.issues == []

    def test_three_link_healthy(self):
        """A -> B -> C chain, all correct."""
        c_id, b_id, a_id = _uuid(), _uuid(), _uuid()
        t3 = datetime.now()
        t2 = t3 - timedelta(hours=1)
        t1 = t2 - timedelta(hours=1)

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [_make_belief(c_id, supersedes_id=b_id, created_at=t3)],  # heads
            [],  # orphans
        ]
        cur.fetchone.side_effect = [
            # Walk C
            _make_belief(c_id, status="active", supersedes_id=b_id, created_at=t3),
            # Bidir C->B: check B.superseded_by_id == C
            {"superseded_by_id": c_id},
            # Walk B
            _make_belief(b_id, status="superseded", supersedes_id=a_id, superseded_by_id=c_id, created_at=t2),
            # Bidir B->A: check A.superseded_by_id == B
            {"superseded_by_id": b_id},
            # Walk A
            _make_belief(a_id, status="superseded", supersedes_id=None, superseded_by_id=b_id, created_at=t1),
        ]

        report = verify_chains(cur)
        assert report.total_chains == 1
        assert report.healthy_chains == 1
        assert report.total_beliefs_in_chains == 3
        assert report.issues == []


class TestVerifyChainsBidirectionalMismatch:
    """Test detection of bidirectional pointer mismatches."""

    def test_detects_mismatch(self):
        """B supersedes A, but A.superseded_by_id != B."""
        head_id = _uuid()
        old_id = _uuid()
        wrong_id = _uuid()
        now = datetime.now()
        earlier = now - timedelta(hours=1)

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [_make_belief(head_id, supersedes_id=old_id, created_at=now)],
            [],  # orphans
        ]
        cur.fetchone.side_effect = [
            _make_belief(head_id, status="active", supersedes_id=old_id, created_at=now),
            # old belief's superseded_by_id points to wrong belief
            {"superseded_by_id": wrong_id},
            _make_belief(old_id, status="superseded", supersedes_id=None, superseded_by_id=wrong_id, created_at=earlier),
        ]

        report = verify_chains(cur)
        assert report.total_chains == 1
        assert report.healthy_chains == 0
        assert any(i.issue_type == "bidirectional_mismatch" for i in report.issues)


class TestVerifyChainsNonMonotonic:
    """Test detection of non-monotonic timestamps."""

    def test_detects_non_monotonic(self):
        """Newer belief has earlier timestamp than older belief."""
        head_id = _uuid()
        old_id = _uuid()
        earlier = datetime.now() - timedelta(hours=2)
        later = earlier + timedelta(hours=1)

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [_make_belief(head_id, supersedes_id=old_id, created_at=earlier)],  # head has EARLIER timestamp
            [],
        ]
        cur.fetchone.side_effect = [
            _make_belief(head_id, status="active", supersedes_id=old_id, created_at=earlier),
            {"superseded_by_id": head_id},
            _make_belief(old_id, status="superseded", supersedes_id=None, superseded_by_id=head_id, created_at=later),  # old has LATER
        ]

        report = verify_chains(cur)
        assert any(i.issue_type == "non_monotonic" for i in report.issues)


class TestVerifyChainsCycle:
    """Test cycle detection."""

    def test_detects_cycle(self):
        """A -> B -> A cycle."""
        a_id = _uuid()
        b_id = _uuid()
        now = datetime.now()

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [_make_belief(a_id, supersedes_id=b_id, created_at=now)],
            [],
        ]
        cur.fetchone.side_effect = [
            # Walk A: fetch A
            _make_belief(a_id, status="active", supersedes_id=b_id, created_at=now),
            # Bidir check: fetch B.superseded_by_id
            {"superseded_by_id": a_id},
            # Walk B: fetch B (supersedes_id=a_id creates the cycle)
            _make_belief(b_id, status="superseded", supersedes_id=a_id, superseded_by_id=a_id, created_at=now - timedelta(hours=1)),
            # Bidir check: fetch A.superseded_by_id (before cycle is detected on next iteration)
            {"superseded_by_id": b_id},
        ]

        report = verify_chains(cur)
        assert any(i.issue_type == "cycle" for i in report.issues)


class TestVerifyChainsBadTerminal:
    """Test terminal status validation."""

    def test_head_not_active(self):
        """Chain head has status='superseded' instead of 'active'."""
        head_id = _uuid()
        old_id = _uuid()
        now = datetime.now()
        earlier = now - timedelta(hours=1)

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [_make_belief(head_id, supersedes_id=old_id, created_at=now)],
            [],
        ]
        cur.fetchone.side_effect = [
            _make_belief(head_id, status="superseded", supersedes_id=old_id, created_at=now),
            {"superseded_by_id": head_id},
            _make_belief(old_id, status="superseded", supersedes_id=None, superseded_by_id=head_id, created_at=earlier),
        ]

        report = verify_chains(cur)
        assert any(i.issue_type == "bad_terminal" and "head" in i.description for i in report.issues)

    def test_non_head_active(self):
        """Non-head belief has status='active' instead of 'superseded'."""
        head_id = _uuid()
        old_id = _uuid()
        now = datetime.now()
        earlier = now - timedelta(hours=1)

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [_make_belief(head_id, supersedes_id=old_id, created_at=now)],
            [],
        ]
        cur.fetchone.side_effect = [
            _make_belief(head_id, status="active", supersedes_id=old_id, created_at=now),
            {"superseded_by_id": head_id},
            _make_belief(old_id, status="active", supersedes_id=None, superseded_by_id=head_id, created_at=earlier),
        ]

        report = verify_chains(cur)
        assert any(i.issue_type == "bad_terminal" and "Non-head" in i.description for i in report.issues)


class TestVerifyChainsOrphans:
    """Test orphan detection."""

    def test_detects_orphan(self):
        """Belief has superseded_by_id pointing to non-existent belief."""
        orphan_id = _uuid()
        ghost_id = _uuid()

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [],  # no chain heads
            [{"id": orphan_id, "superseded_by_id": ghost_id}],  # orphan
        ]

        report = verify_chains(cur)
        assert any(i.issue_type == "orphan" for i in report.issues)


class TestVerifyChainsLimit:
    """Test the limit parameter."""

    def test_limit_restricts_chains(self):
        """With limit=1, only one chain is checked."""
        cur = MagicMock()
        # The LIMIT clause will be in the SQL
        cur.fetchall.side_effect = [[], []]
        report = verify_chains(cur, limit=1)
        # Verify the SQL includes LIMIT
        call_args = cur.execute.call_args_list[0]
        assert "LIMIT" in call_args[0][0]
