"""Tests for cursor-based pagination in federation sync (Issue #265).

Tests cover:
- Cursor encoding/decoding helpers
- SyncRequest page_size validation and clamping
- handle_sync_request with cursor-based pagination
- handle_request_beliefs with cursor-based pagination
- Edge cases: invalid cursors, empty results, exact page boundaries
- Deterministic ordering (timestamp + ID tiebreaking)
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from valence.federation.protocol import (
    BeliefsResponse,
    ErrorCode,
    ErrorMessage,
    RequestBeliefsRequest,
    SyncRequest,
    SyncResponse,
    _decode_cursor,
    _encode_cursor,
    handle_request_beliefs,
    handle_sync_request,
    parse_message,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_cursor():
    """Mock database cursor."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    return cursor


@pytest.fixture
def mock_get_cursor(mock_cursor):
    """Mock the get_cursor context manager."""

    @contextmanager
    def _mock_get_cursor(dict_cursor: bool = True) -> Generator:
        yield mock_cursor

    with patch("valence.federation.protocol.get_cursor", _mock_get_cursor):
        yield mock_cursor


def _make_belief_row(
    *,
    row_id: str | None = None,
    content: str = "Test belief",
    modified_at: datetime | None = None,
    created_at: datetime | None = None,
    supersedes_id: str | None = None,
    status: str = "active",
) -> dict:
    """Build a fake belief DB row for testing."""
    now = datetime.now()
    return {
        "id": row_id or str(uuid4()),
        "content": content,
        "confidence": {"overall": 0.7},
        "domain_path": ["test"],
        "valid_from": None,
        "valid_until": None,
        "visibility": "federated",
        "share_level": "belief_only",
        "created_at": created_at or now,
        "modified_at": modified_at or now,
        "status": status,
        "supersedes_id": supersedes_id,
        "superseded_by_id": None,
    }


# =============================================================================
# CURSOR HELPER TESTS
# =============================================================================


class TestEncodeCursor:
    """Tests for _encode_cursor."""

    def test_encode_basic(self):
        ts = datetime(2026, 2, 6, 14, 0, 0)
        cursor = _encode_cursor(ts, "abc-123")
        assert "|" in cursor
        assert "2026-02-06" in cursor
        assert "abc-123" in cursor

    def test_encode_microseconds_preserved(self):
        ts = datetime(2026, 1, 1, 0, 0, 0, 123456)
        cursor = _encode_cursor(ts, "id1")
        assert "123456" in cursor

    def test_encode_different_ids_produce_different_cursors(self):
        ts = datetime(2026, 1, 1)
        c1 = _encode_cursor(ts, "id-a")
        c2 = _encode_cursor(ts, "id-b")
        assert c1 != c2


class TestDecodeCursor:
    """Tests for _decode_cursor."""

    def test_decode_valid(self):
        ts = datetime(2026, 2, 6, 14, 0, 0)
        cursor = _encode_cursor(ts, "abc-123")
        decoded = _decode_cursor(cursor)
        assert decoded is not None
        assert decoded[0] == ts
        assert decoded[1] == "abc-123"

    def test_decode_roundtrip(self):
        ts = datetime(2026, 3, 15, 12, 30, 45, 678901)
        record_id = str(uuid4())
        cursor = _encode_cursor(ts, record_id)
        decoded = _decode_cursor(cursor)
        assert decoded is not None
        assert decoded[0] == ts
        assert decoded[1] == record_id

    def test_decode_invalid_no_pipe(self):
        assert _decode_cursor("garbage") is None

    def test_decode_invalid_bad_timestamp(self):
        assert _decode_cursor("not-a-date|some-id") is None

    def test_decode_invalid_empty_id(self):
        assert _decode_cursor("2026-01-01T00:00:00|") is None

    def test_decode_empty_string(self):
        assert _decode_cursor("") is None

    def test_decode_none_type(self):
        assert _decode_cursor(None) is None  # type: ignore[arg-type]


# =============================================================================
# SYNC REQUEST PAGE_SIZE TESTS
# =============================================================================


class TestSyncRequestPageSize:
    """Tests for SyncRequest page_size field and clamping."""

    def test_default_page_size(self):
        req = SyncRequest()
        assert req.page_size == 100

    def test_custom_page_size(self):
        req = SyncRequest(page_size=50)
        assert req.page_size == 50

    def test_page_size_clamped_to_max(self):
        req = SyncRequest(page_size=5000)
        assert req.page_size == 1000

    def test_page_size_clamped_to_min(self):
        req = SyncRequest(page_size=0)
        assert req.page_size == 1

    def test_negative_page_size_clamped(self):
        req = SyncRequest(page_size=-10)
        assert req.page_size == 1

    def test_page_size_at_max_boundary(self):
        req = SyncRequest(page_size=1000)
        assert req.page_size == 1000

    def test_page_size_in_to_dict(self):
        req = SyncRequest(page_size=25)
        d = req.to_dict()
        assert d["page_size"] == 25

    def test_page_size_from_parse_message(self):
        data = {
            "type": "SYNC_REQUEST",
            "request_id": str(uuid4()),
            "page_size": 42,
        }
        result = parse_message(data)
        assert isinstance(result, SyncRequest)
        assert result.page_size == 42

    def test_page_size_default_from_parse_message(self):
        data = {
            "type": "SYNC_REQUEST",
            "request_id": str(uuid4()),
        }
        result = parse_message(data)
        assert isinstance(result, SyncRequest)
        assert result.page_size == 100

    def test_page_size_clamped_from_parse_message(self):
        data = {
            "type": "SYNC_REQUEST",
            "request_id": str(uuid4()),
            "page_size": 9999,
        }
        result = parse_message(data)
        assert isinstance(result, SyncRequest)
        assert result.page_size == 1000


# =============================================================================
# SYNC HANDLER PAGINATION TESTS
# =============================================================================


class TestHandleSyncRequestPagination:
    """Tests for cursor-based pagination in handle_sync_request."""

    def _run_sync(self, mock_cursor, *, request=None, trust=0.5, node_id=None):
        """Helper to run handle_sync_request with mocked config."""
        if request is None:
            request = SyncRequest()
        if node_id is None:
            node_id = uuid4()

        mock_config = MagicMock(
            federation_node_did="did:vkb:web:local",
            federation_private_key=None,
        )
        with patch("valence.core.config.get_federation_config", return_value=mock_config):
            return handle_sync_request(request, node_id, trust)

    def test_empty_result_no_cursor(self, mock_get_cursor):
        """No changes → cursor is None, has_more is False."""
        mock_get_cursor.fetchall.return_value = []
        mock_get_cursor.fetchone.return_value = None

        resp = self._run_sync(mock_get_cursor)

        assert isinstance(resp, SyncResponse)
        assert resp.cursor is None
        assert resp.has_more is False
        assert len(resp.changes) == 0

    def test_partial_page_no_has_more(self, mock_get_cursor):
        """Fewer results than page_size → has_more=False, cursor=None."""
        rows = [_make_belief_row(content=f"b{i}") for i in range(3)]
        mock_get_cursor.fetchall.return_value = rows
        mock_get_cursor.fetchone.return_value = None

        request = SyncRequest(page_size=10)
        resp = self._run_sync(mock_get_cursor, request=request)

        assert isinstance(resp, SyncResponse)
        assert resp.has_more is False
        assert resp.cursor is None
        assert len(resp.changes) == 3

    def test_full_page_has_more(self, mock_get_cursor):
        """page_size + 1 rows returned → has_more=True with cursor."""
        base_time = datetime(2026, 1, 1)
        # Create page_size + 1 rows to trigger has_more
        page_size = 5
        rows = [
            _make_belief_row(
                row_id=f"id-{i:03d}",
                content=f"belief-{i}",
                modified_at=base_time + timedelta(minutes=i),
            )
            for i in range(page_size + 1)
        ]
        mock_get_cursor.fetchall.return_value = rows
        mock_get_cursor.fetchone.return_value = None

        request = SyncRequest(page_size=page_size)
        resp = self._run_sync(mock_get_cursor, request=request)

        assert isinstance(resp, SyncResponse)
        assert resp.has_more is True
        assert resp.cursor is not None
        # Should only return page_size changes, not page_size+1
        assert len(resp.changes) == page_size

    def test_cursor_is_decodable(self, mock_get_cursor):
        """Returned cursor can be decoded back to valid timestamp + id."""
        page_size = 2
        rows = [
            _make_belief_row(
                row_id="last-id",
                modified_at=datetime(2026, 6, 15, 12, 0, 0),
            )
            for _ in range(page_size + 1)
        ]
        # Make the last row within page have distinct values
        rows[page_size - 1] = _make_belief_row(
            row_id="the-last-returned",
            modified_at=datetime(2026, 6, 15, 12, 30, 0),
        )
        mock_get_cursor.fetchall.return_value = rows
        mock_get_cursor.fetchone.return_value = None

        request = SyncRequest(page_size=page_size)
        resp = self._run_sync(mock_get_cursor, request=request)

        assert resp.cursor is not None
        decoded = _decode_cursor(resp.cursor)
        assert decoded is not None
        ts, rid = decoded
        assert rid == "the-last-returned"
        assert ts == datetime(2026, 6, 15, 12, 30, 0)

    def test_invalid_cursor_returns_error(self, mock_get_cursor):
        """Invalid cursor format returns SYNC_CURSOR_INVALID error."""
        request = SyncRequest(cursor="not-a-valid-cursor")
        resp = self._run_sync(mock_get_cursor, request=request)

        assert isinstance(resp, ErrorMessage)
        assert resp.error_code == ErrorCode.SYNC_CURSOR_INVALID

    def test_cursor_overrides_since(self, mock_get_cursor):
        """When cursor is provided, it takes precedence over 'since'."""
        ts = datetime(2026, 3, 1, 10, 0, 0)
        cursor = _encode_cursor(ts, "prev-id")
        mock_get_cursor.fetchall.return_value = []
        mock_get_cursor.fetchone.return_value = None

        request = SyncRequest(
            since=datetime(2025, 1, 1),  # Should be ignored
            cursor=cursor,
        )
        resp = self._run_sync(mock_get_cursor, request=request)

        assert isinstance(resp, SyncResponse)
        # Verify the query used cursor conditions, not 'since'
        # We check the SQL that was executed
        call_args = mock_get_cursor.execute.call_args_list
        first_query = call_args[0][0][0]
        assert "modified_at > %s OR (modified_at = %s AND id::text > %s)" in first_query

    def test_since_used_when_no_cursor(self, mock_get_cursor):
        """When no cursor, 'since' filter is applied."""
        mock_get_cursor.fetchall.return_value = []
        mock_get_cursor.fetchone.return_value = None

        since = datetime(2026, 1, 1)
        request = SyncRequest(since=since)
        resp = self._run_sync(mock_get_cursor, request=request)

        assert isinstance(resp, SyncResponse)
        call_args = mock_get_cursor.execute.call_args_list
        first_query = call_args[0][0][0]
        assert "modified_at > %s" in first_query
        # Should NOT contain cursor keyset condition
        assert "id::text > %s" not in first_query

    def test_page_size_controls_limit(self, mock_get_cursor):
        """The SQL LIMIT should be page_size + 1."""
        mock_get_cursor.fetchall.return_value = []
        mock_get_cursor.fetchone.return_value = None

        request = SyncRequest(page_size=25)
        self._run_sync(mock_get_cursor, request=request)

        # First execute call is the main query
        call_args = mock_get_cursor.execute.call_args_list
        first_params = call_args[0][0][1]
        # Last param should be page_size + 1 = 26
        assert first_params[-1] == 26

    def test_deterministic_ordering(self, mock_get_cursor):
        """Query should ORDER BY modified_at ASC, id ASC."""
        mock_get_cursor.fetchall.return_value = []
        mock_get_cursor.fetchone.return_value = None

        request = SyncRequest()
        self._run_sync(mock_get_cursor, request=request)

        call_args = mock_get_cursor.execute.call_args_list
        first_query = call_args[0][0][0]
        assert "ORDER BY modified_at ASC, id ASC" in first_query

    def test_low_trust_rejected(self):
        """Trust below threshold returns error, no cursor logic needed."""
        request = SyncRequest()
        resp = handle_sync_request(request, uuid4(), requester_trust=0.1)
        assert isinstance(resp, ErrorMessage)
        assert resp.error_code == ErrorCode.TRUST_INSUFFICIENT

    def test_change_types_preserved(self, mock_get_cursor):
        """Change types (created, superseded, archived) are correctly set."""
        rows = [
            _make_belief_row(row_id="r1"),
            _make_belief_row(row_id="r2", supersedes_id="old-1"),
        ]
        mock_get_cursor.fetchall.return_value = rows
        mock_get_cursor.fetchone.return_value = None

        resp = self._run_sync(mock_get_cursor)
        assert isinstance(resp, SyncResponse)
        assert resp.changes[0].change_type == "belief_created"
        assert resp.changes[1].change_type == "belief_superseded"
        assert resp.changes[1].old_belief_id == "old-1"

    def test_exact_page_size_no_has_more(self, mock_get_cursor):
        """Exactly page_size rows (not page_size + 1) → has_more=False."""
        page_size = 3
        rows = [_make_belief_row(row_id=f"id-{i}") for i in range(page_size)]
        mock_get_cursor.fetchall.return_value = rows
        mock_get_cursor.fetchone.return_value = None

        request = SyncRequest(page_size=page_size)
        resp = self._run_sync(mock_get_cursor, request=request)

        assert isinstance(resp, SyncResponse)
        assert resp.has_more is False
        assert resp.cursor is None
        assert len(resp.changes) == page_size


# =============================================================================
# REQUEST BELIEFS PAGINATION TESTS
# =============================================================================


class TestHandleRequestBeliefsPagination:
    """Tests for cursor-based pagination in handle_request_beliefs."""

    def _run_request(self, mock_cursor, *, request=None, trust=0.5, node_id=None):
        """Helper to run handle_request_beliefs with mocked config."""
        if request is None:
            request = RequestBeliefsRequest(requester_did="did:vkb:web:peer")
        if node_id is None:
            node_id = uuid4()

        mock_config = MagicMock(
            federation_node_did="did:vkb:web:local",
            federation_private_key=None,
        )
        with patch("valence.core.config.get_federation_config", return_value=mock_config):
            return handle_request_beliefs(request, node_id, trust)

    def test_no_cursor_returns_first_page(self, mock_get_cursor):
        """Without cursor, returns the first page of results."""
        rows = [_make_belief_row(content=f"b{i}") for i in range(3)]
        # First fetchall → beliefs, then fetchone → total
        mock_get_cursor.fetchall.return_value = rows
        mock_get_cursor.fetchone.return_value = {"total": 3}

        resp = self._run_request(mock_get_cursor)
        assert isinstance(resp, BeliefsResponse)
        assert resp.cursor is None  # Only 3 results, no more
        assert resp.total_available == 3

    def test_cursor_returned_when_more_results(self, mock_get_cursor):
        """When there are more results, a cursor is returned."""
        limit = 5
        # Return limit + 1 rows to indicate more
        rows = [
            _make_belief_row(
                row_id=f"id-{i:03d}",
                created_at=datetime(2026, 1, 1) - timedelta(minutes=i),
            )
            for i in range(limit + 1)
        ]
        mock_get_cursor.fetchall.return_value = rows
        mock_get_cursor.fetchone.return_value = {"total": 20}

        request = RequestBeliefsRequest(requester_did="did:vkb:web:peer", limit=limit)
        resp = self._run_request(mock_get_cursor, request=request)

        assert isinstance(resp, BeliefsResponse)
        assert resp.cursor is not None
        assert len(resp.beliefs) == limit  # Not limit + 1

    def test_invalid_cursor_returns_error(self, mock_get_cursor):
        """Invalid cursor returns SYNC_CURSOR_INVALID."""
        request = RequestBeliefsRequest(
            requester_did="did:vkb:web:peer",
            cursor="invalid-cursor",
        )
        resp = self._run_request(mock_get_cursor, request=request)

        assert isinstance(resp, ErrorMessage)
        assert resp.error_code == ErrorCode.SYNC_CURSOR_INVALID

    def test_valid_cursor_filters_results(self, mock_get_cursor):
        """Valid cursor adds keyset condition to query."""
        ts = datetime(2026, 3, 1, 10, 0, 0)
        cursor = _encode_cursor(ts, "prev-id")
        mock_get_cursor.fetchall.return_value = []
        mock_get_cursor.fetchone.return_value = {"total": 0}

        request = RequestBeliefsRequest(
            requester_did="did:vkb:web:peer",
            cursor=cursor,
        )
        resp = self._run_request(mock_get_cursor, request=request)

        assert isinstance(resp, BeliefsResponse)
        # Verify keyset condition is in the query
        call_args = mock_get_cursor.execute.call_args_list
        first_query = call_args[0][0][0]
        assert "created_at < %s" in first_query

    def test_ordering_is_deterministic(self, mock_get_cursor):
        """Query should ORDER BY created_at DESC, id DESC."""
        mock_get_cursor.fetchall.return_value = []
        mock_get_cursor.fetchone.return_value = {"total": 0}

        self._run_request(mock_get_cursor)

        call_args = mock_get_cursor.execute.call_args_list
        first_query = call_args[0][0][0]
        assert "ORDER BY created_at DESC, id DESC" in first_query

    def test_low_trust_rejected(self):
        """Insufficient trust returns error."""
        request = RequestBeliefsRequest(requester_did="did:vkb:web:peer")
        resp = handle_request_beliefs(request, uuid4(), requester_trust=0.05)
        assert isinstance(resp, ErrorMessage)
        assert resp.error_code == ErrorCode.TRUST_INSUFFICIENT


# =============================================================================
# INTEGRATION-STYLE: MULTI-PAGE TRAVERSAL
# =============================================================================


class TestMultiPageSync:
    """Test that cursor values chain correctly across pages."""

    def test_cursor_chain_across_pages(self):
        """Cursors from successive pages should advance monotonically."""
        c1 = _encode_cursor(datetime(2026, 1, 1, 10, 0), "id-001")
        c2 = _encode_cursor(datetime(2026, 1, 1, 10, 5), "id-002")
        c3 = _encode_cursor(datetime(2026, 1, 1, 10, 10), "id-003")

        d1 = _decode_cursor(c1)
        d2 = _decode_cursor(c2)
        d3 = _decode_cursor(c3)

        assert d1 is not None and d2 is not None and d3 is not None
        # Timestamps advance
        assert d1[0] < d2[0] < d3[0]

    def test_same_timestamp_different_ids(self):
        """Tiebreaking by ID handles same-timestamp records."""
        ts = datetime(2026, 1, 1, 12, 0, 0)
        c1 = _encode_cursor(ts, "aaa")
        c2 = _encode_cursor(ts, "zzz")

        d1 = _decode_cursor(c1)
        d2 = _decode_cursor(c2)

        assert d1 is not None and d2 is not None
        assert d1[0] == d2[0]  # Same timestamp
        assert d1[1] < d2[1]  # Different IDs, string-ordered
