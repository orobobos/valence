"""Tests for OAuth 2.1 models and storage."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from valence.server.oauth_models import (
    AuthorizationCode,
    AuthorizationCodeStore,
    OAuthClient,
    OAuthClientStore,
    RefreshToken,
    RefreshTokenStore,
    create_access_token,
    get_client_store,
    get_code_store,
    get_refresh_store,
    verify_access_token,
    verify_pkce,
)


@pytest.fixture(autouse=True)
def reset_oauth_stores():
    """Reset global OAuth stores between tests."""
    import valence.server.oauth_models as oauth_module
    oauth_module._client_store = None
    oauth_module._code_store = None
    oauth_module._refresh_store = None
    yield
    oauth_module._client_store = None
    oauth_module._code_store = None
    oauth_module._refresh_store = None


# ============================================================================
# OAuthClient Tests
# ============================================================================

class TestOAuthClient:
    """Tests for OAuthClient dataclass."""

    def test_client_creation(self):
        """Test creating an OAuth client."""
        client = OAuthClient(
            client_id="test-client-id",
            client_name="Test Client",
            redirect_uris=["http://localhost/callback"],
        )
        
        assert client.client_id == "test-client-id"
        assert client.client_name == "Test Client"
        assert client.redirect_uris == ["http://localhost/callback"]
        assert client.grant_types == ["authorization_code", "refresh_token"]
        assert client.response_types == ["code"]
        assert client.scope == "mcp:tools mcp:resources"

    def test_to_dict(self):
        """Test to_dict serialization."""
        client = OAuthClient(
            client_id="test-id",
            client_name="Test",
            redirect_uris=["http://localhost"],
            scope="mcp:tools",
        )
        
        result = client.to_dict()
        
        assert result["client_id"] == "test-id"
        assert result["client_name"] == "Test"
        assert result["redirect_uris"] == ["http://localhost"]
        assert result["scope"] == "mcp:tools"

    def test_from_dict(self):
        """Test from_dict deserialization."""
        data = {
            "client_id": "test-id",
            "client_name": "Test",
            "redirect_uris": ["http://localhost"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "scope": "mcp:tools",
        }
        
        client = OAuthClient.from_dict(data)
        
        assert client.client_id == "test-id"
        assert client.client_name == "Test"
        assert client.scope == "mcp:tools"


class TestOAuthClientStore:
    """Tests for OAuthClientStore."""

    def test_register_client(self, temp_clients_file):
        """Test registering a new client."""
        store = OAuthClientStore(temp_clients_file)
        
        client = store.register(
            client_name="My App",
            redirect_uris=["http://localhost:3000/callback"],
        )
        
        assert client.client_name == "My App"
        assert len(client.client_id) > 10  # Auto-generated

    def test_get_client(self, temp_clients_file):
        """Test retrieving a client."""
        store = OAuthClientStore(temp_clients_file)
        registered = store.register(
            client_name="My App",
            redirect_uris=["http://localhost/callback"],
        )
        
        client = store.get(registered.client_id)
        
        assert client is not None
        assert client.client_name == "My App"

    def test_get_nonexistent_client(self, temp_clients_file):
        """Test getting non-existent client."""
        store = OAuthClientStore(temp_clients_file)
        
        client = store.get("nonexistent-id")
        
        assert client is None

    def test_validate_redirect_uri_valid(self, temp_clients_file):
        """Test validating registered redirect URI."""
        store = OAuthClientStore(temp_clients_file)
        client = store.register(
            client_name="My App",
            redirect_uris=["http://localhost/callback", "http://localhost/alt"],
        )
        
        assert store.validate_redirect_uri(client.client_id, "http://localhost/callback")
        assert store.validate_redirect_uri(client.client_id, "http://localhost/alt")

    def test_validate_redirect_uri_invalid(self, temp_clients_file):
        """Test rejecting unregistered redirect URI."""
        store = OAuthClientStore(temp_clients_file)
        client = store.register(
            client_name="My App",
            redirect_uris=["http://localhost/callback"],
        )
        
        assert not store.validate_redirect_uri(client.client_id, "http://evil.com/steal")

    def test_persistence(self, temp_clients_file):
        """Test clients persist to file."""
        store1 = OAuthClientStore(temp_clients_file)
        client = store1.register(
            client_name="Persistent App",
            redirect_uris=["http://localhost/callback"],
        )
        
        # Create new store from same file
        store2 = OAuthClientStore(temp_clients_file)
        retrieved = store2.get(client.client_id)
        
        assert retrieved is not None
        assert retrieved.client_name == "Persistent App"


# ============================================================================
# AuthorizationCode Tests
# ============================================================================

class TestAuthorizationCode:
    """Tests for AuthorizationCode dataclass."""

    def test_code_creation(self):
        """Test creating an authorization code."""
        code = AuthorizationCode(
            code="test-code-123",
            client_id="client-id",
            redirect_uri="http://localhost/callback",
            scope="mcp:tools",
            code_challenge="challenge123",
            code_challenge_method="S256",
            user_id="admin",
        )
        
        assert code.code == "test-code-123"
        assert code.client_id == "client-id"
        assert code.user_id == "admin"

    def test_is_expired_not_expired(self):
        """Test is_expired when not expired."""
        code = AuthorizationCode(
            code="test",
            client_id="client",
            redirect_uri="http://localhost",
            scope="mcp:tools",
            code_challenge="ch",
            code_challenge_method="S256",
            user_id="admin",
            expires_at=time.time() + 600,  # 10 minutes from now
        )
        
        assert code.is_expired() is False

    def test_is_expired_expired(self):
        """Test is_expired when expired."""
        code = AuthorizationCode(
            code="test",
            client_id="client",
            redirect_uri="http://localhost",
            scope="mcp:tools",
            code_challenge="ch",
            code_challenge_method="S256",
            user_id="admin",
            expires_at=time.time() - 60,  # 1 minute ago
        )
        
        assert code.is_expired() is True


class TestAuthorizationCodeStore:
    """Tests for AuthorizationCodeStore."""

    def test_create_code(self):
        """Test creating an authorization code."""
        store = AuthorizationCodeStore()
        
        code = store.create(
            client_id="client-id",
            redirect_uri="http://localhost/callback",
            scope="mcp:tools",
            code_challenge="challenge",
            code_challenge_method="S256",
            user_id="admin",
        )
        
        assert len(code) > 20  # Should be a secure random token

    def test_consume_valid_code(self):
        """Test consuming a valid code."""
        store = AuthorizationCodeStore()
        code = store.create(
            client_id="client-id",
            redirect_uri="http://localhost/callback",
            scope="mcp:tools",
            code_challenge="challenge",
            code_challenge_method="S256",
            user_id="admin",
        )
        
        auth_code = store.consume(code)
        
        assert auth_code is not None
        assert auth_code.client_id == "client-id"
        assert auth_code.user_id == "admin"

    def test_consume_code_only_once(self):
        """Test that codes can only be consumed once."""
        store = AuthorizationCodeStore()
        code = store.create(
            client_id="client-id",
            redirect_uri="http://localhost/callback",
            scope="mcp:tools",
            code_challenge="challenge",
            code_challenge_method="S256",
            user_id="admin",
        )
        
        # First consumption succeeds
        auth_code1 = store.consume(code)
        assert auth_code1 is not None
        
        # Second consumption fails
        auth_code2 = store.consume(code)
        assert auth_code2 is None

    def test_consume_invalid_code(self):
        """Test consuming invalid code."""
        store = AuthorizationCodeStore()
        
        auth_code = store.consume("nonexistent-code")
        
        assert auth_code is None

    def test_cleanup_expired(self):
        """Test cleaning up expired codes."""
        store = AuthorizationCodeStore()
        
        # Create a code that's already expired
        code = store.create(
            client_id="client",
            redirect_uri="http://localhost",
            scope="mcp:tools",
            code_challenge="ch",
            code_challenge_method="S256",
            user_id="admin",
        )
        
        # Manually expire it
        store._codes[code].expires_at = time.time() - 100
        
        store.cleanup_expired()
        
        assert code not in store._codes


# ============================================================================
# RefreshToken Tests
# ============================================================================

class TestRefreshToken:
    """Tests for RefreshToken dataclass."""

    def test_token_creation(self):
        """Test creating a refresh token."""
        token = RefreshToken(
            token_hash="hash123",
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
        )
        
        assert token.client_id == "client-id"
        assert token.user_id == "admin"
        assert token.scope == "mcp:tools"

    def test_is_expired_no_expiry(self):
        """Test is_expired with no expiration."""
        token = RefreshToken(
            token_hash="hash",
            client_id="client",
            user_id="admin",
            scope="mcp:tools",
        )
        
        assert token.is_expired() is False

    def test_is_expired_future(self):
        """Test is_expired with future expiration."""
        token = RefreshToken(
            token_hash="hash",
            client_id="client",
            user_id="admin",
            scope="mcp:tools",
            expires_at=time.time() + 86400,
        )
        
        assert token.is_expired() is False

    def test_is_expired_past(self):
        """Test is_expired with past expiration."""
        token = RefreshToken(
            token_hash="hash",
            client_id="client",
            user_id="admin",
            scope="mcp:tools",
            expires_at=time.time() - 100,
        )
        
        assert token.is_expired() is True


class TestRefreshTokenStore:
    """Tests for RefreshTokenStore."""

    def test_create_token(self):
        """Test creating a refresh token."""
        store = RefreshTokenStore()
        
        token = store.create(
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
        )
        
        assert len(token) > 20

    def test_validate_valid_token(self):
        """Test validating a valid refresh token."""
        store = RefreshTokenStore()
        token = store.create(
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
        )
        
        token_data = store.validate(token)
        
        assert token_data is not None
        assert token_data.client_id == "client-id"
        assert token_data.user_id == "admin"

    def test_validate_invalid_token(self):
        """Test validating invalid token."""
        store = RefreshTokenStore()
        
        token_data = store.validate("invalid-token")
        
        assert token_data is None

    def test_revoke_token(self):
        """Test revoking a refresh token."""
        store = RefreshTokenStore()
        token = store.create(
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
        )
        
        assert store.revoke(token) is True
        assert store.validate(token) is None

    def test_revoke_nonexistent(self):
        """Test revoking non-existent token."""
        store = RefreshTokenStore()
        
        assert store.revoke("nonexistent") is False


# ============================================================================
# JWT Access Token Tests
# ============================================================================

class TestAccessToken:
    """Tests for JWT access token functions."""

    @pytest.fixture(autouse=True)
    def setup_jwt_config(self, monkeypatch):
        """Set up JWT configuration for tests."""
        # JWT secret must be at least 32 characters
        monkeypatch.setenv("VALENCE_OAUTH_JWT_SECRET", "test-secret-for-jwt-testing-must-be-at-least-32-chars")
        monkeypatch.setenv("VALENCE_EXTERNAL_URL", "http://localhost:8420")
        monkeypatch.setenv("VALENCE_OAUTH_ACCESS_TOKEN_EXPIRY", "3600")
        
        import valence.server.config as config_module
        config_module._settings = None
        yield
        config_module._settings = None

    def test_create_access_token(self):
        """Test creating a JWT access token."""
        token = create_access_token(
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
            audience="http://localhost:8420/mcp",
        )
        
        assert len(token) > 50  # JWT should be fairly long
        assert token.count(".") == 2  # JWTs have 3 parts

    def test_verify_valid_token(self):
        """Test verifying a valid access token."""
        token = create_access_token(
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
            audience="http://localhost:8420/mcp",
        )
        
        payload = verify_access_token(token, "http://localhost:8420/mcp")
        
        assert payload is not None
        assert payload["client_id"] == "client-id"
        assert payload["sub"] == "admin"
        assert payload["scope"] == "mcp:tools"

    def test_verify_expired_token(self, monkeypatch):
        """Test verifying an expired token."""
        # Create a token that's already expired
        monkeypatch.setenv("VALENCE_OAUTH_JWT_SECRET", "test-secret-for-jwt-testing-must-be-at-least-32-chars")
        monkeypatch.setenv("VALENCE_EXTERNAL_URL", "http://localhost:8420")
        monkeypatch.setenv("VALENCE_OAUTH_ACCESS_TOKEN_EXPIRY", "-10")
        
        import valence.server.config as config_module
        config_module._settings = None
        
        token = create_access_token(
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
            audience="http://localhost:8420/mcp",
        )
        
        payload = verify_access_token(token, "http://localhost:8420/mcp")
        
        assert payload is None

    def test_verify_wrong_audience(self):
        """Test rejecting token with wrong audience."""
        token = create_access_token(
            client_id="client-id",
            user_id="admin",
            scope="mcp:tools",
            audience="http://localhost:8420/mcp",
        )
        
        payload = verify_access_token(token, "http://wrong-audience.com")
        
        assert payload is None

    def test_verify_invalid_token(self):
        """Test rejecting invalid token."""
        payload = verify_access_token("invalid.token.here", "http://localhost:8420/mcp")
        
        assert payload is None


# ============================================================================
# PKCE Tests
# ============================================================================

class TestPKCE:
    """Tests for PKCE verification."""

    def test_verify_pkce_valid(self):
        """Test valid PKCE verification."""
        import base64
        import hashlib
        
        # Generate a valid verifier and challenge
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        
        assert verify_pkce(verifier, challenge, "S256") is True

    def test_verify_pkce_invalid(self):
        """Test invalid PKCE verification."""
        assert verify_pkce("wrong-verifier", "some-challenge", "S256") is False

    def test_verify_pkce_unsupported_method(self):
        """Test rejecting unsupported PKCE method."""
        assert verify_pkce("verifier", "challenge", "plain") is False


# ============================================================================
# Global Store Accessors
# ============================================================================

class TestGlobalStores:
    """Tests for global store accessor functions."""

    def test_get_client_store_singleton(self, temp_clients_file, monkeypatch):
        """Test client store singleton."""
        monkeypatch.setenv("VALENCE_OAUTH_CLIENTS_FILE", str(temp_clients_file))
        
        import valence.server.config as config_module
        config_module._settings = None
        
        store1 = get_client_store()
        store2 = get_client_store()
        
        assert store1 is store2

    def test_get_code_store_singleton(self):
        """Test code store singleton."""
        store1 = get_code_store()
        store2 = get_code_store()
        
        assert store1 is store2

    def test_get_refresh_store_singleton(self):
        """Test refresh store singleton."""
        store1 = get_refresh_store()
        store2 = get_refresh_store()
        
        assert store1 is store2
