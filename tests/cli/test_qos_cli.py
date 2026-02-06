"""Tests for QoS CLI commands.

Covers:
- ``valence qos status`` (human-readable + JSON)
- ``valence qos score`` (default + with dimensions + JSON)
- Dispatching and error handling

Issue #276: Network: Contribution-based QoS with dynamic curve.
"""

from __future__ import annotations

import argparse
import json

import pytest

from valence.cli.commands.qos import cmd_qos, cmd_qos_score, cmd_qos_status


def _make_args(**kwargs: object) -> argparse.Namespace:
    """Build a Namespace with defaults for QoS commands."""
    defaults = {
        "qos_command": None,
        "json": False,
        "node_id": None,
        "routing_capacity": None,
        "uptime_reliability": None,
        "belief_quality": None,
        "resource_sharing": None,
        "trust_received": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestQoSStatusCLI:
    """Tests for valence qos status."""

    def test_status_human_readable(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command="status")
        rc = cmd_qos_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "QoS System Status" in out
        assert "Policy" in out
        assert "Load" in out

    def test_status_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command="status", json=True)
        rc = cmd_qos_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "policy" in data
        assert "load" in data
        assert "node_count" in data
        assert "tier_summary" in data


class TestQoSScoreCLI:
    """Tests for valence qos score."""

    def test_score_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command="score")
        rc = cmd_qos_score(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Contribution Score" in out
        assert "Dimensions" in out
        assert "Priority" in out

    def test_score_with_node_id(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command="score", node_id="my-node")
        rc = cmd_qos_score(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "my-node" in out

    def test_score_with_dimensions(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(
            qos_command="score",
            routing_capacity=0.9,
            uptime_reliability=0.8,
        )
        rc = cmd_qos_score(args)
        assert rc == 0

    def test_score_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command="score", json=True)
        rc = cmd_qos_score(args)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "overall" in data
        assert "tier" in data
        assert "priority_at_load_0" in data
        assert "priority_at_load_50" in data
        assert "priority_at_load_100" in data

    def test_score_json_with_custom_dimensions(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(
            qos_command="score",
            json=True,
            routing_capacity=1.0,
            belief_quality=0.5,
        )
        rc = cmd_qos_score(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["overall"] > 0


class TestQoSDispatch:
    """Tests for the cmd_qos dispatcher."""

    def test_dispatch_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command="status")
        rc = cmd_qos(args)
        assert rc == 0

    def test_dispatch_score(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command="score")
        rc = cmd_qos(args)
        assert rc == 0

    def test_dispatch_unknown(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(qos_command=None)
        rc = cmd_qos(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Usage" in out
