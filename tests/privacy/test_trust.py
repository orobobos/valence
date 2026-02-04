"""Tests for trust graph storage - TrustEdge and TrustGraphStore.

Tests the 4D trust model (competence, integrity, confidentiality, judgment)
and the TrustGraphStore for managing trust relationships.

Key test areas:
- TrustEdge: Creation, validation, serialization
- Judgment dimension: Default 0.1, effects on delegated trust
- Transitive trust: Path finding, judgment weighting
- TrustGraphStore: CRUD operations
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from valence.privacy.trust import (
    TrustEdge,
    TrustGraphStore,
    TrustService,
    get_trust_graph_store,
    get_trust_service,
    grant_trust,
    revoke_trust,
    get_trust,
    list_trusted,
    compute_delegated_trust,
    compute_transitive_trust,
)


class TestTrustEdge:
    """Tests for TrustEdge dataclass."""
    
    def test_create_basic_edge(self):
        """Test creating a basic trust edge."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
        )
        
        assert edge.source_did == "did:key:alice"
        assert edge.target_did == "did:key:bob"
        assert edge.competence == 0.5  # default
        assert edge.integrity == 0.5
        assert edge.confidentiality == 0.5
        assert edge.judgment == 0.1  # very low default - judgment must be earned
        assert edge.domain is None
        assert edge.id is None
    
    def test_create_edge_with_scores(self):
        """Test creating edge with custom trust scores."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            integrity=0.8,
            confidentiality=0.7,
            judgment=0.6,
            domain="medical",
        )
        
        assert edge.competence == 0.9
        assert edge.integrity == 0.8
        assert edge.confidentiality == 0.7
        assert edge.judgment == 0.6
        assert edge.domain == "medical"
    
    def test_overall_trust_calculation(self):
        """Test geometric mean calculation for overall trust."""
        # All same value -> overall should be that value
        edge = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            competence=0.8,
            integrity=0.8,
            confidentiality=0.8,
            judgment=0.8,
        )
        assert abs(edge.overall_trust - 0.8) < 0.001
        
        # Mixed values
        edge2 = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            competence=1.0,
            integrity=1.0,
            confidentiality=1.0,
            judgment=0.0,
        )
        # geometric mean of (1, 1, 1, 0) = 0
        assert edge2.overall_trust == 0.0
    
    def test_invalid_score_too_high(self):
        """Test that scores > 1.0 raise ValueError."""
        with pytest.raises(ValueError, match="competence must be between"):
            TrustEdge(
                source_did="did:key:a",
                target_did="did:key:b",
                competence=1.5,
            )
    
    def test_invalid_score_negative(self):
        """Test that scores < 0.0 raise ValueError."""
        with pytest.raises(ValueError, match="integrity must be between"):
            TrustEdge(
                source_did="did:key:a",
                target_did="did:key:b",
                integrity=-0.1,
            )
    
    def test_invalid_judgment_score(self):
        """Test that invalid judgment scores raise ValueError."""
        with pytest.raises(ValueError, match="judgment must be between"):
            TrustEdge(
                source_did="did:key:a",
                target_did="did:key:b",
                judgment=1.5,
            )
    
    def test_no_self_trust(self):
        """Test that self-trust edges are rejected."""
        with pytest.raises(ValueError, match="Cannot create trust edge to self"):
            TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:alice",
            )
    
    def test_is_expired_no_expiry(self):
        """Test is_expired when no expiry set."""
        edge = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
        )
        assert not edge.is_expired()
    
    def test_is_expired_future(self):
        """Test is_expired with future expiry."""
        edge = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        assert not edge.is_expired()
    
    def test_is_expired_past(self):
        """Test is_expired with past expiry."""
        edge = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert edge.is_expired()
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            integrity=0.8,
            confidentiality=0.7,
            judgment=0.6,
            domain="research",
        )
        
        data = edge.to_dict()
        assert data["source_did"] == "did:key:alice"
        assert data["target_did"] == "did:key:bob"
        assert data["competence"] == 0.9
        assert data["integrity"] == 0.8
        assert data["confidentiality"] == 0.7
        assert data["judgment"] == 0.6
        assert data["domain"] == "research"
        assert "overall_trust" in data
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "source_did": "did:key:alice",
            "target_did": "did:key:bob",
            "competence": 0.9,
            "integrity": 0.8,
            "domain": "test",
        }
        
        edge = TrustEdge.from_dict(data)
        assert edge.source_did == "did:key:alice"
        assert edge.target_did == "did:key:bob"
        assert edge.competence == 0.9
        assert edge.integrity == 0.8
        assert edge.confidentiality == 0.5  # default
        assert edge.judgment == 0.1  # default (very low)
        assert edge.domain == "test"
    
    def test_roundtrip_serialization(self):
        """Test that to_dict/from_dict roundtrip preserves data."""
        original = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.95,
            integrity=0.85,
            confidentiality=0.75,
            judgment=0.65,
            domain="finance",
        )
        
        restored = TrustEdge.from_dict(original.to_dict())
        assert restored.source_did == original.source_did
        assert restored.target_did == original.target_did
        assert restored.competence == original.competence
        assert restored.integrity == original.integrity
        assert restored.confidentiality == original.confidentiality
        assert restored.judgment == original.judgment
        assert restored.domain == original.domain


class TestJudgmentDimension:
    """Tests specifically for the judgment dimension and its effects on trust delegation."""
    
    def test_judgment_default_is_very_low(self):
        """Test that judgment defaults to 0.1 (very low).
        
        Judgment trust must be earned - we don't automatically trust
        someone's ability to evaluate others just because we trust them.
        """
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
        )
        assert edge.judgment == 0.1
    
    def test_judgment_affects_overall_trust(self):
        """Test that low judgment pulls down overall trust."""
        # High scores on other dimensions, but default low judgment
        edge = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            # judgment defaults to 0.1
        )
        
        # Overall trust should be pulled down by low judgment
        # Geometric mean of (0.9, 0.9, 0.9, 0.1)
        assert edge.overall_trust < 0.6
        assert edge.overall_trust > 0.4
    
    def test_high_judgment_enables_delegation(self):
        """Test that high judgment enables meaningful trust delegation."""
        # Alice trusts Bob with high judgment AND allows delegation
        alice_bob = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.8,
            confidentiality=0.8,
            judgment=0.9,  # Alice trusts Bob's judgment highly
            can_delegate=True,  # Allow delegation
        )
        
        # Bob trusts Carol
        bob_carol = TrustEdge(
            source_did="did:key:bob",
            target_did="did:key:carol",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.9,
        )
        
        # Alice's delegated trust in Carol should be meaningful
        delegated = compute_delegated_trust(alice_bob, bob_carol)
        
        # With high judgment (0.9), delegated trust should be significant
        # min(0.8, 0.9) * 0.9 = 0.72
        assert delegated is not None
        assert delegated.competence >= 0.7
        assert delegated.source_did == "did:key:alice"
        assert delegated.target_did == "did:key:carol"
    
    def test_low_judgment_limits_delegation(self):
        """Test that low judgment severely limits trust delegation.
        
        This is the key behavior: if Alice trusts Bob but doesn't trust
        his judgment, Bob's recommendations about Carol carry little weight.
        """
        # Alice trusts Bob but not his judgment
        alice_bob = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.8,
            confidentiality=0.8,
            judgment=0.1,  # Alice doesn't trust Bob's judgment
            can_delegate=True,  # Still allow delegation
        )
        
        # Bob highly trusts Carol
        bob_carol = TrustEdge(
            source_did="did:key:bob",
            target_did="did:key:carol",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.9,
        )
        
        # Alice's delegated trust in Carol should be very low
        delegated = compute_delegated_trust(alice_bob, bob_carol)
        
        # With low judgment (0.1), delegated trust should be minimal
        # min(0.8, 0.9) * 0.1 = 0.08
        assert delegated is not None
        assert delegated.competence <= 0.1
        assert delegated.integrity <= 0.1
    
    def test_delegation_blocked_when_not_allowed(self):
        """Test that delegation returns None when can_delegate is False."""
        # Alice trusts Bob but doesn't allow delegation
        alice_bob = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            judgment=0.9,
            can_delegate=False,  # No delegation allowed
        )
        
        bob_carol = TrustEdge(
            source_did="did:key:bob",
            target_did="did:key:carol",
            competence=0.9,
        )
        
        # Should return None because delegation is not allowed
        delegated = compute_delegated_trust(alice_bob, bob_carol)
        assert delegated is None
    
    def test_judgment_chains_compound(self):
        """Test that judgment trust compounds across multiple hops.
        
        Each hop's judgment affects the next, so long chains with
        moderate judgment result in very low delegated trust.
        """
        # A -> B with moderate judgment
        a_b = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.5,
            can_delegate=True,
        )
        
        # B -> C with moderate judgment
        b_c = TrustEdge(
            source_did="did:key:b",
            target_did="did:key:c",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.5,
        )
        
        # A's delegated trust in C
        a_c = compute_delegated_trust(a_b, b_c)
        
        # First hop: competence = min(0.9, 0.9) * 0.5 = 0.45
        assert a_c is not None
        assert abs(a_c.competence - 0.45) < 0.01
        # Judgment also decays: min(0.5, 0.5) * 0.5 = 0.25
        assert abs(a_c.judgment - 0.25) < 0.01


class TestTransitiveTrust:
    """Tests for transitive trust computation through the graph."""
    
    def test_direct_trust_returned(self):
        """Test that direct trust is returned if available."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            judgment=0.8,
        )
        
        graph = {("did:key:alice", "did:key:bob"): edge}
        
        result = compute_transitive_trust("did:key:alice", "did:key:bob", graph)
        
        assert result is not None
        assert result.competence == 0.9
        assert result.judgment == 0.8
    
    def test_single_hop_transitive(self):
        """Test transitive trust with one intermediary."""
        a_b = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            competence=0.8,
            integrity=0.8,
            confidentiality=0.8,
            judgment=0.6,
            can_delegate=True,
        )
        
        b_c = TrustEdge(
            source_did="did:key:b",
            target_did="did:key:c",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.9,
        )
        
        graph = {
            ("did:key:a", "did:key:b"): a_b,
            ("did:key:b", "did:key:c"): b_c,
        }
        
        result = compute_transitive_trust("did:key:a", "did:key:c", graph)
        
        assert result is not None
        assert result.source_did == "did:key:a"
        assert result.target_did == "did:key:c"
        # competence = min(0.8, 0.9) * 0.6 = 0.48
        assert abs(result.competence - 0.48) < 0.01
    
    def test_no_path_returns_none(self):
        """Test that no path returns None."""
        a_b = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            competence=0.8,
            judgment=0.6,
        )
        
        graph = {("did:key:a", "did:key:b"): a_b}
        
        result = compute_transitive_trust("did:key:a", "did:key:c", graph)
        
        assert result is None
    
    def test_multiple_paths_takes_best(self):
        """Test that multiple paths take the best option per dimension."""
        # Path 1: A -> B -> D (low judgment intermediary)
        a_b = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.2,  # Low judgment
            can_delegate=True,
        )
        b_d = TrustEdge(
            source_did="did:key:b",
            target_did="did:key:d",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.9,
        )
        
        # Path 2: A -> C -> D (high judgment intermediary)
        a_c = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:c",
            competence=0.7,  # Lower direct trust
            integrity=0.7,
            confidentiality=0.7,
            judgment=0.8,  # High judgment
            can_delegate=True,
        )
        c_d = TrustEdge(
            source_did="did:key:c",
            target_did="did:key:d",
            competence=0.9,
            integrity=0.9,
            confidentiality=0.9,
            judgment=0.9,
        )
        
        graph = {
            ("did:key:a", "did:key:b"): a_b,
            ("did:key:b", "did:key:d"): b_d,
            ("did:key:a", "did:key:c"): a_c,
            ("did:key:c", "did:key:d"): c_d,
        }
        
        result = compute_transitive_trust("did:key:a", "did:key:d", graph)
        
        assert result is not None
        # Path 1: competence = min(0.9, 0.9) * 0.2 = 0.18
        # Path 2: competence = min(0.7, 0.9) * 0.8 = 0.56
        # Should take max = 0.56
        assert result.competence > 0.5
    
    def test_max_hops_respected(self):
        """Test that max_hops limit is respected."""
        # Create a long chain: A -> B -> C -> D -> E
        edges = [
            TrustEdge(
                source_did="did:key:a",
                target_did="did:key:b",
                competence=0.9,
                judgment=0.9,
                can_delegate=True,
            ),
            TrustEdge(
                source_did="did:key:b",
                target_did="did:key:c",
                competence=0.9,
                judgment=0.9,
                can_delegate=True,
            ),
            TrustEdge(
                source_did="did:key:c",
                target_did="did:key:d",
                competence=0.9,
                judgment=0.9,
                can_delegate=True,
            ),
            TrustEdge(
                source_did="did:key:d",
                target_did="did:key:e",
                competence=0.9,
                judgment=0.9,
            ),
        ]
        
        graph = {(e.source_did, e.target_did): e for e in edges}
        
        # With max_hops=2, should not reach E (4 hops away)
        result = compute_transitive_trust("did:key:a", "did:key:e", graph, max_hops=2)
        assert result is None
        
        # With max_hops=4, should reach E
        result = compute_transitive_trust("did:key:a", "did:key:e", graph, max_hops=4)
        assert result is not None


class TestTrustGraphStore:
    """Tests for TrustGraphStore database operations."""
    
    @pytest.fixture
    def mock_cursor(self):
        """Create a mock cursor for database tests."""
        with patch("valence.core.db.get_cursor") as mock_get_cursor:
            mock_cur = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_cur)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_get_cursor.return_value = mock_ctx
            yield mock_cur
    
    @pytest.fixture
    def store(self):
        """Create a TrustGraphStore instance."""
        return TrustGraphStore()
    
    def test_add_edge_new(self, store, mock_cursor):
        """Test adding a new trust edge."""
        mock_cursor.fetchone.return_value = {
            "id": uuid4(),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
        )
        
        result = store.add_edge(edge)
        
        assert result.id is not None
        assert mock_cursor.execute.called
        # Check that upsert query was used
        call_args = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO trust_edges" in call_args
        assert "ON CONFLICT" in call_args
    
    def test_add_edge_includes_judgment(self, store, mock_cursor):
        """Test that add_edge includes judgment in the query."""
        mock_cursor.fetchone.return_value = {
            "id": uuid4(),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            judgment=0.7,
        )
        
        store.add_edge(edge)
        
        call_args = mock_cursor.execute.call_args[0][0]
        assert "judgment" in call_args
    
    def test_get_edge_found(self, store, mock_cursor):
        """Test getting an existing trust edge."""
        mock_cursor.fetchone.return_value = {
            "id": uuid4(),
            "source_did": "did:key:alice",
            "target_did": "did:key:bob",
            "competence": 0.9,
            "integrity": 0.8,
            "confidentiality": 0.7,
            "judgment": 0.6,
            "domain": None,
            "can_delegate": True,
            "delegation_depth": 2,
            "decay_rate": 0.0,
            "decay_model": "exponential",
            "last_refreshed": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "expires_at": None,
        }
        
        edge = store.get_edge("did:key:alice", "did:key:bob")
        
        assert edge is not None
        assert edge.source_did == "did:key:alice"
        assert edge.target_did == "did:key:bob"
        assert edge.competence == 0.9
        assert edge.judgment == 0.6
    
    def test_get_edge_not_found(self, store, mock_cursor):
        """Test getting a non-existent trust edge."""
        mock_cursor.fetchone.return_value = None
        
        edge = store.get_edge("did:key:alice", "did:key:nobody")
        
        assert edge is None
    
    def test_get_edge_with_domain(self, store, mock_cursor):
        """Test getting edge with domain filter."""
        mock_cursor.fetchone.return_value = {
            "id": uuid4(),
            "source_did": "did:key:alice",
            "target_did": "did:key:bob",
            "competence": 0.9,
            "integrity": 0.8,
            "confidentiality": 0.7,
            "judgment": 0.6,
            "domain": "medical",
            "can_delegate": False,
            "delegation_depth": 0,
            "decay_rate": 0.0,
            "decay_model": "exponential",
            "last_refreshed": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "expires_at": None,
        }
        
        edge = store.get_edge("did:key:alice", "did:key:bob", domain="medical")
        
        assert edge is not None
        assert edge.domain == "medical"
        # Verify domain was passed to query
        call_args = mock_cursor.execute.call_args
        assert "medical" in call_args[0][1]
    
    def test_get_edges_from(self, store, mock_cursor):
        """Test getting all edges from a DID."""
        mock_cursor.fetchall.return_value = [
            {
                "id": uuid4(),
                "source_did": "did:key:alice",
                "target_did": "did:key:bob",
                "competence": 0.9,
                "integrity": 0.8,
                "confidentiality": 0.7,
                "judgment": 0.6,
                "domain": None,
                "can_delegate": True,
                "delegation_depth": 2,
                "decay_rate": 0.0,
                "decay_model": "exponential",
                "last_refreshed": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "expires_at": None,
            },
            {
                "id": uuid4(),
                "source_did": "did:key:alice",
                "target_did": "did:key:carol",
                "competence": 0.7,
                "integrity": 0.7,
                "confidentiality": 0.7,
                "judgment": 0.7,
                "domain": None,
                "can_delegate": False,
                "delegation_depth": 0,
                "decay_rate": 0.0,
                "decay_model": "exponential",
                "last_refreshed": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "expires_at": None,
            },
        ]
        
        edges = store.get_edges_from("did:key:alice")
        
        assert len(edges) == 2
        assert all(e.source_did == "did:key:alice" for e in edges)
    
    def test_get_edges_from_with_domain(self, store, mock_cursor):
        """Test getting edges with domain filter."""
        mock_cursor.fetchall.return_value = []
        
        store.get_edges_from("did:key:alice", domain="medical")
        
        call_args = mock_cursor.execute.call_args[0][0]
        assert "domain = %s" in call_args
    
    def test_get_edges_from_include_expired(self, store, mock_cursor):
        """Test including expired edges."""
        mock_cursor.fetchall.return_value = []
        
        # Without include_expired (default)
        store.get_edges_from("did:key:alice")
        call_args = mock_cursor.execute.call_args[0][0]
        assert "expires_at" in call_args
        
        # With include_expired
        store.get_edges_from("did:key:alice", include_expired=True)
        call_args = mock_cursor.execute.call_args[0][0]
        # The expiry filter should not have an extra clause
    
    def test_get_edges_to(self, store, mock_cursor):
        """Test getting all edges to a DID."""
        mock_cursor.fetchall.return_value = [
            {
                "id": uuid4(),
                "source_did": "did:key:bob",
                "target_did": "did:key:alice",
                "competence": 0.8,
                "integrity": 0.8,
                "confidentiality": 0.8,
                "judgment": 0.8,
                "domain": None,
                "can_delegate": False,
                "delegation_depth": 0,
                "decay_rate": 0.0,
                "decay_model": "exponential",
                "last_refreshed": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "expires_at": None,
            },
        ]
        
        edges = store.get_edges_to("did:key:alice")
        
        assert len(edges) == 1
        assert edges[0].target_did == "did:key:alice"
    
    def test_delete_edge_found(self, store, mock_cursor):
        """Test deleting an existing edge."""
        mock_cursor.fetchone.return_value = {"id": uuid4()}
        
        result = store.delete_edge("did:key:alice", "did:key:bob")
        
        assert result is True
        call_args = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM trust_edges" in call_args
    
    def test_delete_edge_not_found(self, store, mock_cursor):
        """Test deleting a non-existent edge."""
        mock_cursor.fetchone.return_value = None
        
        result = store.delete_edge("did:key:alice", "did:key:nobody")
        
        assert result is False
    
    def test_delete_edge_with_domain(self, store, mock_cursor):
        """Test deleting edge with domain."""
        mock_cursor.fetchone.return_value = {"id": uuid4()}
        
        store.delete_edge("did:key:alice", "did:key:bob", domain="medical")
        
        call_args = mock_cursor.execute.call_args
        assert "medical" in call_args[0][1]
    
    def test_delete_edges_from(self, store, mock_cursor):
        """Test deleting all edges from a DID."""
        mock_cursor.fetchall.return_value = [{"id": uuid4()}, {"id": uuid4()}]
        
        count = store.delete_edges_from("did:key:alice")
        
        assert count == 2
    
    def test_delete_edges_to(self, store, mock_cursor):
        """Test deleting all edges to a DID."""
        mock_cursor.fetchall.return_value = [{"id": uuid4()}]
        
        count = store.delete_edges_to("did:key:bob")
        
        assert count == 1
    
    def test_cleanup_expired(self, store, mock_cursor):
        """Test cleaning up expired edges."""
        mock_cursor.fetchall.return_value = [{"id": uuid4()}, {"id": uuid4()}, {"id": uuid4()}]
        
        count = store.cleanup_expired()
        
        assert count == 3
        call_args = mock_cursor.execute.call_args[0][0]
        assert "expires_at IS NOT NULL" in call_args
        assert "expires_at < NOW()" in call_args
    
    def test_count_edges_all(self, store, mock_cursor):
        """Test counting all edges."""
        mock_cursor.fetchone.return_value = {"count": 42}
        
        count = store.count_edges()
        
        assert count == 42
    
    def test_count_edges_filtered(self, store, mock_cursor):
        """Test counting edges with filters."""
        mock_cursor.fetchone.return_value = {"count": 5}
        
        count = store.count_edges(source_did="did:key:alice")
        
        assert count == 5
        call_args = mock_cursor.execute.call_args
        assert "did:key:alice" in call_args[0][1]


class TestModuleFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_trust_graph_store_singleton(self):
        """Test that get_trust_graph_store returns singleton."""
        # Reset module state
        import valence.privacy.trust as trust_module
        trust_module._default_store = None
        
        store1 = get_trust_graph_store()
        store2 = get_trust_graph_store()
        
        assert store1 is store2


# Integration tests (require database)
@pytest.mark.integration
class TestTrustGraphStoreIntegration:
    """Integration tests that require a real database.
    
    Run with: pytest -m integration
    """
    
    @pytest.fixture
    def store(self):
        """Create store and clean up after test."""
        store = TrustGraphStore()
        yield store
        # Cleanup test data
        try:
            store.delete_edges_from("did:test:alice")
            store.delete_edges_from("did:test:bob")
            store.delete_edges_from("did:test:carol")
        except Exception:
            pass
    
    def test_full_crud_cycle(self, store):
        """Test create, read, update, delete cycle."""
        # Create
        edge = TrustEdge(
            source_did="did:test:alice",
            target_did="did:test:bob",
            competence=0.9,
            integrity=0.8,
            confidentiality=0.7,
            judgment=0.6,
        )
        created = store.add_edge(edge)
        assert created.id is not None
        
        # Read
        retrieved = store.get_edge("did:test:alice", "did:test:bob")
        assert retrieved is not None
        assert retrieved.competence == 0.9
        assert retrieved.judgment == 0.6
        
        # Update
        edge.competence = 0.95
        edge.judgment = 0.8
        updated = store.add_edge(edge)
        assert updated.competence == 0.95
        
        # Verify update
        retrieved2 = store.get_edge("did:test:alice", "did:test:bob")
        assert retrieved2.competence == 0.95
        assert retrieved2.judgment == 0.8
        
        # Delete
        deleted = store.delete_edge("did:test:alice", "did:test:bob")
        assert deleted is True
        
        # Verify deletion
        gone = store.get_edge("did:test:alice", "did:test:bob")
        assert gone is None
    
    def test_graph_queries(self, store):
        """Test graph traversal queries."""
        # Create a small graph: alice -> bob, alice -> carol, bob -> carol
        store.add_edge(TrustEdge(
            source_did="did:test:alice",
            target_did="did:test:bob",
            competence=0.9,
            judgment=0.7,
        ))
        store.add_edge(TrustEdge(
            source_did="did:test:alice",
            target_did="did:test:carol",
            competence=0.8,
            judgment=0.6,
        ))
        store.add_edge(TrustEdge(
            source_did="did:test:bob",
            target_did="did:test:carol",
            competence=0.7,
            judgment=0.5,
        ))
        
        # Who does alice trust?
        from_alice = store.get_edges_from("did:test:alice")
        assert len(from_alice) == 2
        
        # Who trusts carol?
        to_carol = store.get_edges_to("did:test:carol")
        assert len(to_carol) == 2
    
    def test_domain_scoped_trust(self, store):
        """Test domain-specific trust edges."""
        # General trust
        store.add_edge(TrustEdge(
            source_did="did:test:alice",
            target_did="did:test:bob",
            competence=0.5,
            judgment=0.3,
        ))
        
        # Domain-specific trust (higher)
        store.add_edge(TrustEdge(
            source_did="did:test:alice",
            target_did="did:test:bob",
            competence=0.9,
            judgment=0.8,
            domain="medical",
        ))
        
        # Should have both edges
        all_edges = store.get_edges_from("did:test:alice")
        assert len(all_edges) == 2
        
        # Filter by domain
        medical_edges = store.get_edges_from("did:test:alice", domain="medical")
        assert len(medical_edges) == 1
        assert medical_edges[0].competence == 0.9


class TestDelegationPolicy:
    """Tests for trust delegation policy (can_delegate and delegation_depth)."""
    
    def test_default_delegation_values(self):
        """Test that edges are non-delegatable by default."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
        )
        assert edge.can_delegate is False
        assert edge.delegation_depth == 0
    
    def test_create_delegatable_edge(self):
        """Test creating an edge that allows delegation."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            can_delegate=True,
            delegation_depth=2,
        )
        assert edge.can_delegate is True
        assert edge.delegation_depth == 2
    
    def test_invalid_delegation_depth(self):
        """Test that negative delegation_depth raises ValueError."""
        with pytest.raises(ValueError, match="delegation_depth must be >= 0"):
            TrustEdge(
                source_did="did:key:a",
                target_did="did:key:b",
                delegation_depth=-1,
            )
    
    def test_with_delegation_method(self):
        """Test with_delegation creates a copy with delegation settings."""
        edge = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
        )
        
        delegatable = edge.with_delegation(can_delegate=True, delegation_depth=3)
        
        # Original unchanged
        assert edge.can_delegate is False
        assert edge.delegation_depth == 0
        
        # New edge has delegation
        assert delegatable.can_delegate is True
        assert delegatable.delegation_depth == 3
        # Other properties preserved
        assert delegatable.competence == 0.9
        assert delegatable.source_did == "did:key:alice"
    
    def test_delegation_serialization_roundtrip(self):
        """Test that delegation fields survive serialization."""
        original = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            can_delegate=True,
            delegation_depth=5,
        )
        
        restored = TrustEdge.from_dict(original.to_dict())
        assert restored.can_delegate == original.can_delegate
        assert restored.delegation_depth == original.delegation_depth
    
    def test_delegation_in_to_dict(self):
        """Test that to_dict includes delegation fields."""
        edge = TrustEdge(
            source_did="did:key:a",
            target_did="did:key:b",
            can_delegate=True,
            delegation_depth=2,
        )
        
        data = edge.to_dict()
        assert data["can_delegate"] is True
        assert data["delegation_depth"] == 2


class TestComputeDelegatedTrust:
    """Tests for compute_delegated_trust with delegation policy."""
    
    def test_delegation_blocked_when_can_delegate_false(self):
        """Test that non-delegatable edges block transitive trust."""
        # Alice trusts Bob but NOT delegatably
        alice_bob = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            judgment=0.8,
            can_delegate=False,  # Non-transitive
        )
        
        # Bob trusts Carol
        bob_carol = TrustEdge(
            source_did="did:key:bob",
            target_did="did:key:carol",
            competence=0.8,
        )
        
        # Should return None because Alice's trust in Bob is non-delegatable
        result = compute_delegated_trust(alice_bob, bob_carol)
        assert result is None
    
    def test_delegation_allowed_when_can_delegate_true(self):
        """Test that delegatable edges allow transitive trust."""
        # Alice trusts Bob delegatably
        alice_bob = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            judgment=0.8,
            can_delegate=True,
        )
        
        # Bob trusts Carol
        bob_carol = TrustEdge(
            source_did="did:key:bob",
            target_did="did:key:carol",
            competence=0.8,
        )
        
        result = compute_delegated_trust(alice_bob, bob_carol)
        assert result is not None
        assert result.source_did == "did:key:alice"
        assert result.target_did == "did:key:carol"
    
    def test_delegation_depth_propagation(self):
        """Test that delegation depth is properly tracked."""
        # Alice trusts Bob with depth limit of 2
        alice_bob = TrustEdge(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.9,
            judgment=0.8,
            can_delegate=True,
            delegation_depth=2,
        )
        
        # Bob trusts Carol (unlimited)
        bob_carol = TrustEdge(
            source_did="did:key:bob",
            target_did="did:key:carol",
            competence=0.8,
            can_delegate=True,
            delegation_depth=0,  # Unlimited
        )
        
        result = compute_delegated_trust(alice_bob, bob_carol)
        assert result is not None
        # Depth should be decremented
        assert result.delegation_depth == 1  # Was 2, now 1


class TestComputeTransitiveTrust:
    """Tests for compute_transitive_trust with delegation policy."""
    
    def test_direct_trust_always_returned(self):
        """Test that direct trust is returned regardless of delegation."""
        graph = {
            ("did:key:alice", "did:key:bob"): TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.9,
                can_delegate=False,  # Non-delegatable
            )
        }
        
        result = compute_transitive_trust(
            "did:key:alice", "did:key:bob", graph
        )
        assert result is not None
        assert result.competence == 0.9
    
    def test_transitive_trust_blocked_without_delegation(self):
        """Test transitive trust is blocked when edges are non-delegatable."""
        graph = {
            ("did:key:alice", "did:key:bob"): TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.9,
                judgment=0.8,
                can_delegate=False,  # Blocks transitive
            ),
            ("did:key:bob", "did:key:carol"): TrustEdge(
                source_did="did:key:bob",
                target_did="did:key:carol",
                competence=0.8,
            )
        }
        
        # No direct trust alice -> carol, and transitive is blocked
        result = compute_transitive_trust(
            "did:key:alice", "did:key:carol", graph
        )
        assert result is None
    
    def test_transitive_trust_with_delegation(self):
        """Test transitive trust works when edges allow delegation."""
        graph = {
            ("did:key:alice", "did:key:bob"): TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.9,
                judgment=0.8,
                can_delegate=True,  # Allows transitive
            ),
            ("did:key:bob", "did:key:carol"): TrustEdge(
                source_did="did:key:bob",
                target_did="did:key:carol",
                competence=0.8,
            )
        }
        
        result = compute_transitive_trust(
            "did:key:alice", "did:key:carol", graph
        )
        assert result is not None
        assert result.source_did == "did:key:alice"
        assert result.target_did == "did:key:carol"
    
    def test_transitive_trust_respects_depth_limit(self):
        """Test that delegation_depth limits chain length."""
        # Create a 3-hop chain: alice -> bob -> carol -> dave
        graph = {
            ("did:key:alice", "did:key:bob"): TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.9,
                judgment=0.9,
                can_delegate=True,
                delegation_depth=1,  # Only 1 hop allowed
            ),
            ("did:key:bob", "did:key:carol"): TrustEdge(
                source_did="did:key:bob",
                target_did="did:key:carol",
                competence=0.8,
                judgment=0.8,
                can_delegate=True,
            ),
            ("did:key:carol", "did:key:dave"): TrustEdge(
                source_did="did:key:carol",
                target_did="did:key:dave",
                competence=0.7,
            )
        }
        
        # Alice can reach Carol (1 hop from alice -> bob)
        result_carol = compute_transitive_trust(
            "did:key:alice", "did:key:carol", graph
        )
        assert result_carol is not None
        
        # Alice cannot reach Dave (would be 2 hops, but depth limit is 1)
        result_dave = compute_transitive_trust(
            "did:key:alice", "did:key:dave", graph
        )
        assert result_dave is None
    
    def test_respect_delegation_flag(self):
        """Test that respect_delegation=False ignores delegation policy."""
        graph = {
            ("did:key:alice", "did:key:bob"): TrustEdge(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.9,
                judgment=0.8,
                can_delegate=False,  # Would block normally
            ),
            ("did:key:bob", "did:key:carol"): TrustEdge(
                source_did="did:key:bob",
                target_did="did:key:carol",
                competence=0.8,
            )
        }
        
        # With respect_delegation=True (default), blocked
        result_strict = compute_transitive_trust(
            "did:key:alice", "did:key:carol", graph, respect_delegation=True
        )
        assert result_strict is None
        
        # With respect_delegation=False, allowed
        result_permissive = compute_transitive_trust(
            "did:key:alice", "did:key:carol", graph, respect_delegation=False
        )
        assert result_permissive is not None
        assert medical_edges[0].judgment == 0.8
