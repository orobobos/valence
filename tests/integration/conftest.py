"""Integration test fixtures for Valence.

This module provides fixtures for integration testing including:
- Real database connections with automatic cleanup
- Server instances for HTTP API testing
- Federation test fixtures with multiple nodes
- Test data seeding utilities
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from contextlib import contextmanager
from typing import Any, Generator
from uuid import UUID, uuid4

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
import pytest
import requests

# ============================================================================
# Configuration
# ============================================================================

# Database configuration (from environment or defaults)
DB_HOST = os.environ.get("VKB_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("VKB_DB_PORT", "5433"))  # 5433 for docker compose test env
DB_NAME = os.environ.get("VKB_DB_NAME", "valence_test")
DB_USER = os.environ.get("VKB_DB_USER", "valence")
DB_PASSWORD = os.environ.get("VKB_DB_PASSWORD", "testpass")

# Peer database for federation tests
PEER_DB_HOST = os.environ.get("VKB_PEER_DB_HOST", "localhost")
PEER_DB_PORT = int(os.environ.get("VKB_PEER_DB_PORT", "5434"))

# Server URLs
PRIMARY_URL = os.environ.get("VALENCE_PRIMARY_URL", "http://localhost:8080")
PEER_URL = os.environ.get("VALENCE_PEER_URL", "http://localhost:8081")


# ============================================================================
# Database Utilities
# ============================================================================

def _get_connection(host: str = DB_HOST, port: int = DB_PORT) -> psycopg2.extensions.connection:
    """Create a database connection."""
    return psycopg2.connect(
        host=host,
        port=port,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def _check_db_available(host: str = DB_HOST, port: int = DB_PORT) -> bool:
    """Check if database is available."""
    try:
        conn = _get_connection(host, port)
        conn.close()
        return True
    except Exception:
        return False


def _wait_for_db(host: str = DB_HOST, port: int = DB_PORT, timeout: int = 30) -> bool:
    """Wait for database to become available."""
    start = time.time()
    while time.time() - start < timeout:
        if _check_db_available(host, port):
            return True
        time.sleep(1)
    return False


def _clean_test_data(conn: psycopg2.extensions.connection) -> None:
    """Clean up test data from database (preserves schema)."""
    with conn.cursor() as cur:
        # Delete in correct order due to foreign keys
        # Tables ordered by dependency (children before parents)
        tables = [
            # Sync and federation
            "sync_outbound_queue",
            "sync_events",
            "sync_state",
            "consensus_votes",
            "aggregation_sources",
            "aggregated_beliefs",
            "belief_trust_annotations",
            "user_node_trust",
            "node_trust",
            "belief_provenance",
            "federation_nodes",
            # Patterns and sessions
            "vkb_session_insights",
            "vkb_patterns",
            "vkb_exchanges",
            "vkb_sessions",
            # Core knowledge
            "tension_resolutions",
            "tensions",
            "belief_entities",
            "beliefs",
            "entities",
            "sources",
        ]
        for table in tables:
            try:
                cur.execute(f"DELETE FROM {table}")
            except psycopg2.Error:
                # Table might not exist
                conn.rollback()
        conn.commit()


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def db_available() -> bool:
    """Check if database is available (session-scoped)."""
    return _wait_for_db()


@pytest.fixture(scope="session")
def peer_db_available() -> bool:
    """Check if peer database is available (session-scoped)."""
    return _wait_for_db(PEER_DB_HOST, PEER_DB_PORT)


@pytest.fixture
def db_conn(db_available):
    """Database connection with automatic rollback after each test.
    
    Use this for tests that should not persist data.
    """
    if not db_available:
        pytest.skip("Database not available")
    
    conn = _get_connection()
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def db_conn_committed(db_available):
    """Database connection that commits changes.
    
    Use this for tests that need to verify committed data.
    Cleanup happens after the test.
    """
    if not db_available:
        pytest.skip("Database not available")
    
    conn = _get_connection()
    yield conn
    # Clean up test data after the test
    _clean_test_data(conn)
    conn.close()


@pytest.fixture
def peer_db_conn(peer_db_available):
    """Connection to peer database for federation tests."""
    if not peer_db_available:
        pytest.skip("Peer database not available")
    
    conn = _get_connection(PEER_DB_HOST, PEER_DB_PORT)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture(scope="session")
def clean_database(db_available):
    """Clean database before tests (session-scoped).
    
    Runs once at the beginning of the test session.
    """
    if not db_available:
        pytest.skip("Database not available")
    
    conn = _get_connection()
    _clean_test_data(conn)
    conn.close()
    
    yield
    
    # Optional: clean up after all tests
    conn = _get_connection()
    _clean_test_data(conn)
    conn.close()


# ============================================================================
# Test Data Seeding
# ============================================================================

@pytest.fixture
def seed_beliefs(db_conn_committed) -> list[UUID]:
    """Seed the database with test beliefs."""
    beliefs = []
    with db_conn_committed.cursor() as cur:
        test_data = [
            ("Python is a programming language", ["tech", "languages"], 0.9),
            ("Claude is an AI assistant", ["tech", "ai"], 0.95),
            ("PostgreSQL supports vector search", ["tech", "databases"], 0.85),
            ("Testing is important for code quality", ["engineering", "practices"], 0.8),
            ("Valence stores knowledge as beliefs", ["tech", "valence"], 0.9),
        ]
        
        for content, domains, confidence in test_data:
            cur.execute("""
                INSERT INTO beliefs (content, domain_path, confidence)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (content, domains, Json({"overall": confidence})))
            beliefs.append(cur.fetchone()[0])
        
        db_conn_committed.commit()
    
    return beliefs


@pytest.fixture
def seed_entities(db_conn_committed) -> list[UUID]:
    """Seed the database with test entities."""
    entities = []
    with db_conn_committed.cursor() as cur:
        test_data = [
            ("Python", "tool", ["py", "python3"]),
            ("Claude", "agent", ["claude-ai", "anthropic-claude"]),
            ("PostgreSQL", "tool", ["postgres", "pg"]),
            ("Alice", "person", ["alice-dev"]),
            ("Bob", "person", ["bob-ops"]),
        ]
        
        for name, entity_type, aliases in test_data:
            cur.execute("""
                INSERT INTO entities (name, entity_type, aliases)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (name, entity_type, aliases))
            entities.append(cur.fetchone()[0])
        
        db_conn_committed.commit()
    
    return entities


@pytest.fixture
def seed_session(db_conn_committed) -> UUID:
    """Seed a test session with exchanges."""
    with db_conn_committed.cursor() as cur:
        # Create session
        cur.execute("""
            INSERT INTO vkb_sessions (external_room_id, status, platform)
            VALUES (%s, %s, %s)
            RETURNING id
        """, ("!test-room:example.com", "active", "test"))
        session_id = cur.fetchone()[0]
        
        # Add exchanges
        exchanges = [
            (1, "user", "What is Valence?"),
            (2, "assistant", "Valence is a personal knowledge substrate for AI agents."),
            (3, "user", "How does it store knowledge?"),
            (4, "assistant", "It stores knowledge as beliefs with confidence scores."),
        ]
        
        for seq, role, content in exchanges:
            cur.execute("""
                INSERT INTO vkb_exchanges (session_id, sequence, role, content)
                VALUES (%s, %s, %s, %s)
            """, (session_id, seq, role, content))
        
        db_conn_committed.commit()
    
    return session_id


@pytest.fixture
def seed_federation_nodes(db_conn_committed) -> list[dict]:
    """Seed federation nodes for federation tests."""
    nodes = []
    with db_conn_committed.cursor() as cur:
        test_nodes = [
            ("did:vkb:web:peer.example.com", PRIMARY_URL, "active"),
            ("did:vkb:web:external.example.com", "http://external.example.com:8080", "pending"),
        ]
        
        for did, endpoint, status in test_nodes:
            cur.execute("""
                INSERT INTO federation_nodes (did, federation_endpoint, status)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (did, endpoint, status))
            node_id = cur.fetchone()[0]
            nodes.append({
                "id": node_id,
                "did": did,
                "endpoint": endpoint,
                "status": status,
            })
        
        db_conn_committed.commit()
    
    return nodes


@pytest.fixture
def seed_node_trust(db_conn_committed, seed_federation_nodes) -> list[dict]:
    """Seed node trust relationships."""
    trust_records = []
    with db_conn_committed.cursor() as cur:
        for node in seed_federation_nodes:
            trust_level = 0.8 if node["status"] == "active" else 0.3
            cur.execute("""
                INSERT INTO node_trust (node_id, trust)
                VALUES (%s, %s)
                RETURNING id
            """, (node["id"], Json({"overall": trust_level})))
            trust_records.append({
                "id": cur.fetchone()[0],
                "node_id": node["id"],
                "trust_level": trust_level,
            })
        
        db_conn_committed.commit()
    
    return trust_records


# ============================================================================
# Server Fixtures
# ============================================================================

def _wait_for_server(url: str, timeout: int = 30) -> bool:
    """Wait for server to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{url}/api/v1/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="session")
def primary_server_available() -> bool:
    """Check if primary server is available."""
    return _wait_for_server(PRIMARY_URL)


@pytest.fixture(scope="session")
def peer_server_available() -> bool:
    """Check if peer server is available."""
    return _wait_for_server(PEER_URL)


@pytest.fixture
def primary_api(primary_server_available) -> str:
    """Get primary server URL."""
    if not primary_server_available:
        pytest.skip("Primary server not available")
    return PRIMARY_URL


@pytest.fixture
def peer_api(peer_server_available) -> str:
    """Get peer server URL."""
    if not peer_server_available:
        pytest.skip("Peer server not available")
    return PEER_URL


@pytest.fixture
def authenticated_client(primary_api) -> tuple[str, dict]:
    """Get an authenticated client for API testing.
    
    Returns:
        Tuple of (base_url, headers_dict)
    """
    # In a real setup, we'd generate or retrieve a valid token
    # For testing, we'll use a test token or skip auth
    test_token = os.environ.get("VALENCE_TEST_TOKEN", "test-token")
    headers = {
        "Authorization": f"Bearer {test_token}",
        "Content-Type": "application/json",
    }
    return primary_api, headers


# ============================================================================
# Helper Fixtures
# ============================================================================

@pytest.fixture
def make_belief(db_conn_committed):
    """Factory fixture for creating test beliefs."""
    created_ids = []
    
    def _make_belief(
        content: str,
        domains: list[str] | None = None,
        confidence: float = 0.7,
        **kwargs
    ) -> UUID:
        with db_conn_committed.cursor() as cur:
            cur.execute("""
                INSERT INTO beliefs (content, domain_path, confidence)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (content, domains or ["test"], Json({"overall": confidence})))
            belief_id = cur.fetchone()[0]
            db_conn_committed.commit()
            created_ids.append(belief_id)
            return belief_id
    
    yield _make_belief


@pytest.fixture
def make_session(db_conn_committed):
    """Factory fixture for creating test sessions."""
    def _make_session(
        room_id: str | None = None,
        platform: str = "test",
        status: str = "active",
    ) -> UUID:
        with db_conn_committed.cursor() as cur:
            cur.execute("""
                INSERT INTO vkb_sessions (external_room_id, platform, status)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (room_id or f"!room-{uuid4()}:test", platform, status))
            session_id = cur.fetchone()[0]
            db_conn_committed.commit()
            return session_id
    
    return _make_session


# ============================================================================
# Event Loop Fixture
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
