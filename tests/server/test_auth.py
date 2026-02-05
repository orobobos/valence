"""Tests for token authentication."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from valence.server.auth import (
    TOKEN_PREFIX,
    Token,
    TokenStore,
    generate_token,
    get_token_store,
    hash_token,
    verify_token,
)


@pytest.fixture(autouse=True)
def reset_token_store():
    """Reset global token store between tests."""
    import valence.server.auth as auth_module

    auth_module._token_store = None
    yield
    auth_module._token_store = None


class TestToken:
    """Tests for Token dataclass."""

    def test_token_creation(self):
        """Test creating a token."""
        token = Token(
            token_hash="abc123",
            client_id="test-client",
            scopes=["mcp:access"],
        )

        assert token.token_hash == "abc123"
        assert token.client_id == "test-client"
        assert token.scopes == ["mcp:access"]
        assert token.expires_at is None
        assert token.description == ""

    def test_is_expired_no_expiry(self):
        """Test is_expired with no expiration."""
        token = Token(
            token_hash="abc123",
            client_id="test-client",
        )

        assert token.is_expired() is False

    def test_is_expired_future(self):
        """Test is_expired with future expiration."""
        token = Token(
            token_hash="abc123",
            client_id="test-client",
            expires_at=time.time() + 3600,  # 1 hour from now
        )

        assert token.is_expired() is False

    def test_is_expired_past(self):
        """Test is_expired with past expiration."""
        token = Token(
            token_hash="abc123",
            client_id="test-client",
            expires_at=time.time() - 3600,  # 1 hour ago
        )

        assert token.is_expired() is True

    def test_has_scope_present(self):
        """Test has_scope with present scope."""
        token = Token(
            token_hash="abc123",
            client_id="test-client",
            scopes=["mcp:access", "mcp:admin"],
        )

        assert token.has_scope("mcp:access") is True
        assert token.has_scope("mcp:admin") is True

    def test_has_scope_missing(self):
        """Test has_scope with missing scope."""
        token = Token(
            token_hash="abc123",
            client_id="test-client",
            scopes=["mcp:access"],
        )

        assert token.has_scope("mcp:admin") is False

    def test_to_dict(self):
        """Test to_dict serialization."""
        token = Token(
            token_hash="abc123",
            client_id="test-client",
            scopes=["mcp:access"],
            expires_at=1234567890.0,
            created_at=1234567800.0,
            description="Test token",
        )

        result = token.to_dict()

        assert result["token_hash"] == "abc123"
        assert result["client_id"] == "test-client"
        assert result["scopes"] == ["mcp:access"]
        assert result["expires_at"] == 1234567890.0
        assert result["created_at"] == 1234567800.0
        assert result["description"] == "Test token"

    def test_from_dict(self):
        """Test from_dict deserialization."""
        data = {
            "token_hash": "abc123",
            "client_id": "test-client",
            "scopes": ["mcp:access"],
            "expires_at": 1234567890.0,
            "created_at": 1234567800.0,
            "description": "Test token",
        }

        token = Token.from_dict(data)

        assert token.token_hash == "abc123"
        assert token.client_id == "test-client"
        assert token.scopes == ["mcp:access"]
        assert token.expires_at == 1234567890.0


class TestHashToken:
    """Tests for hash_token function."""

    def test_consistent_hashing(self):
        """Test that same token produces same hash."""
        token = "vt_test123"

        hash1 = hash_token(token)
        hash2 = hash_token(token)

        assert hash1 == hash2

    def test_different_tokens_different_hashes(self):
        """Test that different tokens produce different hashes."""
        hash1 = hash_token("vt_test123")
        hash2 = hash_token("vt_test456")

        assert hash1 != hash2

    def test_hash_format(self):
        """Test hash output format."""
        result = hash_token("test")

        # SHA-256 produces 64 hex characters
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestGenerateToken:
    """Tests for generate_token function."""

    def test_token_prefix(self):
        """Test token has correct prefix."""
        token = generate_token()

        assert token.startswith(TOKEN_PREFIX)

    def test_token_length(self):
        """Test token has appropriate length."""
        token = generate_token()

        # vt_ prefix (3) + 64 hex chars = 67 total
        assert len(token) == 67

    def test_unique_tokens(self):
        """Test that generated tokens are unique."""
        tokens = [generate_token() for _ in range(10)]

        assert len(set(tokens)) == 10


class TestTokenStore:
    """Tests for TokenStore class."""

    def test_create_token(self, temp_token_file):
        """Test creating a token."""
        store = TokenStore(temp_token_file)

        raw_token = store.create(client_id="test-client", description="Test")

        assert raw_token.startswith(TOKEN_PREFIX)
        assert len(store.list_tokens()) == 1

    def test_verify_valid_token(self, temp_token_file):
        """Test verifying a valid token."""
        store = TokenStore(temp_token_file)
        raw_token = store.create(client_id="test-client")

        token = store.verify(raw_token)

        assert token is not None
        assert token.client_id == "test-client"

    def test_verify_invalid_token(self, temp_token_file):
        """Test verifying an invalid token."""
        store = TokenStore(temp_token_file)

        token = store.verify("invalid-token")

        assert token is None

    def test_verify_invalid_token_logs_warning(self, temp_token_file, caplog):
        """Test that invalid token verification logs a warning."""
        import logging

        store = TokenStore(temp_token_file)

        with caplog.at_level(logging.WARNING, logger="valence.server.auth"):
            store.verify("invalid-token")

        assert "Token not found" in caplog.text
        # Verify it's at WARNING level, not DEBUG
        assert any(record.levelno == logging.WARNING and "Token not found" in record.message for record in caplog.records)

    def test_verify_with_bearer_prefix(self, temp_token_file):
        """Test verifying token with Bearer prefix."""
        store = TokenStore(temp_token_file)
        raw_token = store.create(client_id="test-client")

        token = store.verify(f"Bearer {raw_token}")

        assert token is not None
        assert token.client_id == "test-client"

    def test_verify_expired_token(self, temp_token_file):
        """Test verifying an expired token."""
        store = TokenStore(temp_token_file)
        raw_token = store.create(
            client_id="test-client",
            expires_at=time.time() - 3600,  # Already expired
        )

        token = store.verify(raw_token)

        assert token is None

    def test_revoke_token(self, temp_token_file):
        """Test revoking a token."""
        store = TokenStore(temp_token_file)
        raw_token = store.create(client_id="test-client")
        token_hash = hash_token(raw_token)

        assert store.revoke(token_hash) is True
        assert store.verify(raw_token) is None

    def test_revoke_nonexistent_token(self, temp_token_file):
        """Test revoking a non-existent token."""
        store = TokenStore(temp_token_file)

        assert store.revoke("nonexistent-hash") is False

    def test_list_tokens(self, temp_token_file):
        """Test listing tokens."""
        store = TokenStore(temp_token_file)
        store.create(client_id="client1")
        store.create(client_id="client2")

        tokens = store.list_tokens()

        assert len(tokens) == 2

    def test_get_by_client_id(self, temp_token_file):
        """Test getting tokens by client ID."""
        store = TokenStore(temp_token_file)
        store.create(client_id="client1")
        store.create(client_id="client1")
        store.create(client_id="client2")

        client1_tokens = store.get_by_client_id("client1")

        assert len(client1_tokens) == 2
        assert all(t.client_id == "client1" for t in client1_tokens)

    def test_persistence(self, temp_token_file):
        """Test tokens persist to file."""
        store1 = TokenStore(temp_token_file)
        raw_token = store1.create(client_id="test-client", description="Persistent")

        # Create new store from same file
        store2 = TokenStore(temp_token_file)

        token = store2.verify(raw_token)
        assert token is not None
        assert token.description == "Persistent"

    def test_file_permissions(self, temp_token_file):
        """Test token file has restricted permissions."""
        store = TokenStore(temp_token_file)
        store.create(client_id="test-client")

        # Check file mode
        mode = temp_token_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_load_empty_file(self, temp_token_file):
        """Test loading from empty/nonexistent file."""
        import os

        os.remove(temp_token_file)

        store = TokenStore(temp_token_file)

        assert len(store.list_tokens()) == 0


class TestVerifyToken:
    """Tests for verify_token function."""

    def test_verify_with_required_scope(self, temp_token_file):
        """Test verifying token with required scope."""
        with patch("valence.server.auth.get_token_store") as mock_get_store:
            store = TokenStore(temp_token_file)
            raw_token = store.create(
                client_id="test-client",
                scopes=["mcp:access", "mcp:admin"],
            )
            mock_get_store.return_value = store

            token = verify_token(raw_token, required_scope="mcp:admin")

            assert token is not None

    def test_verify_missing_required_scope(self, temp_token_file):
        """Test verifying token missing required scope."""
        with patch("valence.server.auth.get_token_store") as mock_get_store:
            store = TokenStore(temp_token_file)
            raw_token = store.create(
                client_id="test-client",
                scopes=["mcp:access"],  # No admin scope
            )
            mock_get_store.return_value = store

            token = verify_token(raw_token, required_scope="mcp:admin")

            assert token is None


class TestGetTokenStore:
    """Tests for get_token_store function."""

    def test_singleton_pattern(self, temp_token_file):
        """Test token store singleton."""
        store1 = get_token_store(temp_token_file)
        store2 = get_token_store()

        assert store1 is store2

    def test_uses_settings_default(self, monkeypatch, temp_token_file):
        """Test using settings for default token file."""
        monkeypatch.setenv("VALENCE_TOKEN_FILE", str(temp_token_file))

        # Reset global store
        import valence.server.auth as auth_module

        auth_module._token_store = None
        import valence.server.config as config_module

        config_module._settings = None

        store = get_token_store()

        assert store.token_file == temp_token_file
