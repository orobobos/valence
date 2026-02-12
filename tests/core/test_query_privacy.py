"""Tests for query obfuscation with cover traffic (#355).

Tests cover:
1. get_domain_distribution from DB
2. get_domain_distribution empty returns default
3. generate_dummy_query structure
4. generate_dummy_query samples from distribution
5. build_query_bundle correct count
6. build_query_bundle custom cover_count
7. QueryBundle.all_queries includes real
8. QueryBundle.total_queries correct
9. filter_results extracts real only
10. filter_results counts dummies
11. QueryResult serialization
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from valence.core.query_privacy import (
    DEFAULT_COVER_COUNT,
    QueryBundle,
    QueryResult,
    build_query_bundle,
    filter_results,
    generate_dummy_query,
    get_domain_distribution,
)


@pytest.fixture
def mock_cur():
    return MagicMock()


@pytest.fixture
def sample_distribution():
    return {"tech": 0.5, "science": 0.3, "general": 0.2}


class TestGetDomainDistribution:
    """Test domain distribution from DB."""

    def test_returns_distribution(self, mock_cur):
        mock_cur.fetchall.return_value = [
            {"domain": "tech", "cnt": 50},
            {"domain": "science", "cnt": 30},
            {"domain": "general", "cnt": 20},
        ]
        dist = get_domain_distribution(mock_cur)
        assert dist["tech"] == pytest.approx(0.5)
        assert dist["science"] == pytest.approx(0.3)
        assert dist["general"] == pytest.approx(0.2)

    def test_empty_returns_default(self, mock_cur):
        mock_cur.fetchall.return_value = []
        dist = get_domain_distribution(mock_cur)
        assert dist == {"general": 1.0}

    def test_queries_beliefs_table(self, mock_cur):
        mock_cur.fetchall.return_value = []
        get_domain_distribution(mock_cur)
        sql = mock_cur.execute.call_args[0][0]
        assert "FROM beliefs" in sql
        assert "domain_path" in sql


class TestGenerateDummyQuery:
    """Test dummy query generation."""

    def test_structure(self, sample_distribution):
        query = generate_dummy_query(sample_distribution)
        assert "query" in query
        assert "domain_filter" in query
        assert "limit" in query
        assert query["is_dummy"] is True

    def test_domain_from_distribution(self, sample_distribution):
        # Generate many and check domains come from distribution
        domains_seen = set()
        for _ in range(100):
            q = generate_dummy_query(sample_distribution)
            domains_seen.update(q["domain_filter"])
        # Should see at least 2 of the 3 domains
        assert len(domains_seen) >= 2
        assert all(d in sample_distribution for d in domains_seen)

    def test_limit_in_range(self, sample_distribution):
        for _ in range(20):
            q = generate_dummy_query(sample_distribution)
            assert 5 <= q["limit"] <= 20


class TestBuildQueryBundle:
    """Test bundle construction."""

    def test_default_cover_count(self, sample_distribution):
        real = {"query": "find beliefs about AI"}
        bundle = build_query_bundle(real, sample_distribution)
        assert len(bundle.dummy_queries) == DEFAULT_COVER_COUNT
        assert bundle.real_query == real

    def test_custom_cover_count(self, sample_distribution):
        real = {"query": "test"}
        bundle = build_query_bundle(real, sample_distribution, cover_count=5)
        assert len(bundle.dummy_queries) == 5
        assert bundle.cover_count == 5

    def test_zero_cover(self, sample_distribution):
        real = {"query": "test"}
        bundle = build_query_bundle(real, sample_distribution, cover_count=0)
        assert len(bundle.dummy_queries) == 0
        assert bundle.total_queries == 1


class TestQueryBundle:
    """Test QueryBundle properties."""

    def test_all_queries_includes_real(self):
        real = {"query": "real query"}
        bundle = QueryBundle(
            real_query=real,
            dummy_queries=[{"query": "fake1"}, {"query": "fake2"}],
        )
        all_q = bundle.all_queries
        assert len(all_q) == 3
        real_found = [q for q in all_q if q["is_real"]]
        assert len(real_found) == 1
        assert real_found[0]["query"] == real

    def test_total_queries(self):
        bundle = QueryBundle(
            real_query={"query": "test"},
            dummy_queries=[{"q": 1}, {"q": 2}, {"q": 3}],
        )
        assert bundle.total_queries == 4

    def test_all_queries_randomized(self):
        """All queries should be shuffled (non-deterministic order)."""
        real = {"query": "real"}
        dummies = [{"query": f"fake{i}"} for i in range(9)]
        bundle = QueryBundle(real_query=real, dummy_queries=dummies)

        # Run multiple times and check order varies
        orders = []
        for _ in range(10):
            all_q = bundle.all_queries
            orders.append(tuple(q["is_real"] for q in all_q))
        # With 10 queries, getting same order 10 times is astronomically unlikely
        assert len(set(orders)) > 1


class TestFilterResults:
    """Test result filtering."""

    def test_extracts_real_results(self):
        all_results = [
            ({"query": "real", "is_dummy": False}, [{"result": "a"}, {"result": "b"}]),
            ({"query": "fake", "is_dummy": True}, [{"result": "noise"}]),
            ({"query": "fake2", "is_dummy": True}, []),
        ]
        result = filter_results(all_results, {"query": "real"})
        assert len(result.real_results) == 2
        assert result.dummy_count == 2
        assert result.total_queries_sent == 3

    def test_no_dummies(self):
        all_results = [
            ({"query": "real"}, [{"result": "a"}]),
        ]
        result = filter_results(all_results, {"query": "real"})
        assert len(result.real_results) == 1
        assert result.dummy_count == 0

    def test_empty_results(self):
        result = filter_results([], {"query": "anything"})
        assert len(result.real_results) == 0
        assert result.dummy_count == 0
        assert result.total_queries_sent == 0


class TestQueryResultSerialization:
    """Test QueryResult.to_dict."""

    def test_to_dict(self):
        result = QueryResult(
            real_results=[{"r": 1}],
            dummy_count=3,
            total_queries_sent=4,
        )
        d = result.to_dict()
        assert d["results"] == [{"r": 1}]
        assert d["dummy_count"] == 3
        assert d["total_queries_sent"] == 4
