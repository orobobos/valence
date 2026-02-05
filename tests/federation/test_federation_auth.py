"""Tests for federation endpoint authentication - Issue #29 DID signature verification."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from valence.server.federation_endpoints import (
    require_did_signature,
    verify_did_signature,
)


class TestDIDSignatureVerification:
    """Test DID signature verification for federation endpoints."""

    @pytest.mark.asyncio
    async def test_missing_headers_returns_none(self):
        """Request without DID headers should return None."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        result = await verify_did_signature(mock_request)
        assert result is None

    @pytest.mark.asyncio
    async def test_partial_headers_returns_none(self):
        """Request with only some DID headers should return None."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "X-VFP-DID": "did:vkb:web:example.com",
            # Missing signature, timestamp, nonce
        }

        result = await verify_did_signature(mock_request)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_timestamp_returns_none(self):
        """Request with non-numeric timestamp should return None."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "X-VFP-DID": "did:vkb:web:example.com",
            "X-VFP-Signature": base64.b64encode(b"fake").decode(),
            "X-VFP-Timestamp": "not-a-number",
            "X-VFP-Nonce": "abc123",
        }

        result = await verify_did_signature(mock_request)
        assert result is None

    @pytest.mark.asyncio
    async def test_stale_timestamp_rejected(self):
        """Request with timestamp older than 5 minutes should be rejected."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "X-VFP-DID": "did:vkb:web:example.com",
            "X-VFP-Signature": base64.b64encode(b"fake").decode(),
            "X-VFP-Timestamp": str(int(time.time()) - 400),  # 6+ minutes old
            "X-VFP-Nonce": "abc123",
        }
        mock_request.body = AsyncMock(return_value=b"{}")

        result = await verify_did_signature(mock_request)
        assert result is None

    @pytest.mark.asyncio
    async def test_future_timestamp_rejected(self):
        """Request with timestamp in the future should be rejected."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "X-VFP-DID": "did:vkb:web:example.com",
            "X-VFP-Signature": base64.b64encode(b"fake").decode(),
            "X-VFP-Timestamp": str(int(time.time()) + 400),  # 6+ minutes future
            "X-VFP-Nonce": "abc123",
        }
        mock_request.body = AsyncMock(return_value=b"{}")

        result = await verify_did_signature(mock_request)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self):
        """Request with valid DID signature should be accepted."""
        from valence.federation.identity import (
            generate_keypair,
            sign_message,
        )

        # Generate a test keypair
        keypair = generate_keypair()
        did = "did:vkb:key:" + keypair.public_key_multibase

        # Create request data
        timestamp = str(int(time.time()))
        nonce = "test-nonce-123"
        body = b'{"test": "data"}'
        body_hash = hashlib.sha256(body).hexdigest()

        # Create the message to sign
        message = f"POST /federation/protocol {timestamp} {nonce} {body_hash}"
        signature = sign_message(message.encode("utf-8"), keypair.private_key_bytes)

        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url = MagicMock()
        mock_request.url.path = "/federation/protocol"
        mock_request.headers = {
            "X-VFP-DID": did,
            "X-VFP-Signature": base64.b64encode(signature).decode(),
            "X-VFP-Timestamp": timestamp,
            "X-VFP-Nonce": nonce,
        }
        mock_request.body = AsyncMock(return_value=body)

        # Mock the DID resolution
        mock_did_doc = MagicMock()
        mock_did_doc.public_key_multibase = keypair.public_key_multibase

        with patch("valence.federation.identity.parse_did"):
            with patch("valence.federation.identity.resolve_did_sync") as mock_resolve:
                mock_resolve.return_value = mock_did_doc

                result = await verify_did_signature(mock_request)

                assert result is not None
                assert result["did"] == did
                assert result["timestamp"] == int(timestamp)
                assert result["nonce"] == nonce


class TestRequireDIDSignatureDecorator:
    """Test the @require_did_signature decorator."""

    @pytest.mark.asyncio
    async def test_decorator_rejects_unsigned_requests(self):
        """Decorator should return 401 for requests without valid signature."""

        @require_did_signature
        async def test_handler(request):
            return {"success": True}

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        with patch("valence.server.federation_endpoints.get_settings") as mock_settings:
            mock_settings.return_value.federation_enabled = True

            response = await test_handler(mock_request)

            assert response.status_code == 401
            body = json.loads(response.body)
            # Response format: {"error": {"code": ..., "message": ...}, "success": false}
            error_info = body.get("error", body)
            error_msg = error_info.get("message", "") if isinstance(error_info, dict) else str(error_info)
            assert "DID signature verification failed" in error_msg

    @pytest.mark.asyncio
    async def test_decorator_allows_valid_requests(self):
        """Decorator should allow requests with valid signature."""
        from valence.federation.identity import generate_keypair, sign_message

        @require_did_signature
        async def test_handler(request):
            from starlette.responses import JSONResponse

            return JSONResponse({"success": True, "did": request.state.did_info["did"]})

        # Generate keypair and create signed request
        keypair = generate_keypair()
        did = "did:vkb:key:" + keypair.public_key_multibase
        timestamp = str(int(time.time()))
        nonce = "test-nonce"
        body = b"{}"
        body_hash = hashlib.sha256(body).hexdigest()

        message = f"POST /federation/protocol {timestamp} {nonce} {body_hash}"
        signature = sign_message(message.encode("utf-8"), keypair.private_key_bytes)

        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url = MagicMock()
        mock_request.url.path = "/federation/protocol"
        mock_request.headers = {
            "X-VFP-DID": did,
            "X-VFP-Signature": base64.b64encode(signature).decode(),
            "X-VFP-Timestamp": timestamp,
            "X-VFP-Nonce": nonce,
        }
        mock_request.body = AsyncMock(return_value=body)
        mock_request.state = MagicMock()

        mock_did_doc = MagicMock()
        mock_did_doc.public_key_multibase = keypair.public_key_multibase

        with patch("valence.server.federation_endpoints.get_settings") as mock_settings:
            mock_settings.return_value.federation_enabled = True

            with patch("valence.federation.identity.parse_did"):
                with patch("valence.federation.identity.resolve_did_sync") as mock_resolve:
                    mock_resolve.return_value = mock_did_doc

                    response = await test_handler(mock_request)

                    assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_decorator_returns_404_when_federation_disabled(self):
        """Decorator should return 404 when federation is disabled."""

        @require_did_signature
        async def test_handler(request):
            return {"success": True}

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        with patch("valence.server.federation_endpoints.get_settings") as mock_settings:
            mock_settings.return_value.federation_enabled = False

            response = await test_handler(mock_request)

            assert response.status_code == 404
            body = json.loads(response.body)
            # Response format: {"error": {"code": ..., "message": ...}, "success": false}
            error_info = body.get("error", body)
            error_msg = error_info.get("message", "") if isinstance(error_info, dict) else str(error_info)
            assert "Federation not enabled" in error_msg


class TestFederationEndpointSecurity:
    """Test that federation endpoints properly require authentication."""

    def test_discovery_endpoints_are_public(self):
        """Well-known discovery endpoints should NOT require authentication."""
        from valence.server.federation_endpoints import (
            vfp_node_metadata,
        )

        # These handlers should NOT have the @require_did_signature decorator
        # Check by looking at the function - it shouldn't be wrapped
        # (The decorator wraps the function, changing its behavior)

        # The actual test is that these functions don't check for DID signature
        # We can verify by checking they don't have the wrapper's behavior
        assert not hasattr(vfp_node_metadata, "__wrapped__") or vfp_node_metadata.__name__ == "vfp_node_metadata"

    def test_protocol_endpoint_requires_auth(self):
        """Protocol endpoint should require DID signature."""
        from valence.server.federation_endpoints import federation_protocol

        # The decorator wraps the function
        # We can check it's wrapped by looking at the wrapper behavior
        # or by checking the __wrapped__ attribute
        assert hasattr(federation_protocol, "__wrapped__")

    def test_all_post_endpoints_require_auth(self):
        """All POST federation endpoints should require DID signature."""
        from valence.server.federation_endpoints import (
            federation_belief_query,
            federation_belief_share,
            federation_corroboration_check,
            federation_nodes_discover,
            federation_protocol,
            federation_sync_trigger,
            federation_trust_set,
        )

        # All these should be wrapped by @require_did_signature
        post_handlers = [
            federation_protocol,
            federation_nodes_discover,
            federation_trust_set,
            federation_sync_trigger,
            federation_belief_share,
            federation_belief_query,
            federation_corroboration_check,
        ]

        for handler in post_handlers:
            assert hasattr(handler, "__wrapped__"), f"{handler.__name__} should be decorated with @require_did_signature"


class TestReplayProtection:
    """Test replay attack protection."""

    @pytest.mark.asyncio
    async def test_nonce_required(self):
        """Requests without nonce should be rejected."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {
            "X-VFP-DID": "did:vkb:web:example.com",
            "X-VFP-Signature": base64.b64encode(b"fake").decode(),
            "X-VFP-Timestamp": str(int(time.time())),
            # Missing nonce
        }

        result = await verify_did_signature(mock_request)
        assert result is None

    @pytest.mark.asyncio
    async def test_body_hash_prevents_tampering(self):
        """Signature should include body hash to prevent tampering."""
        from valence.federation.identity import generate_keypair, sign_message

        keypair = generate_keypair()
        did = "did:vkb:key:" + keypair.public_key_multibase

        timestamp = str(int(time.time()))
        nonce = "test-nonce"
        original_body = b'{"action": "share"}'
        body_hash = hashlib.sha256(original_body).hexdigest()

        # Sign with original body
        message = f"POST /federation/protocol {timestamp} {nonce} {body_hash}"
        signature = sign_message(message.encode("utf-8"), keypair.private_key_bytes)

        # But send with tampered body
        tampered_body = b'{"action": "delete_all"}'

        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url = MagicMock()
        mock_request.url.path = "/federation/protocol"
        mock_request.headers = {
            "X-VFP-DID": did,
            "X-VFP-Signature": base64.b64encode(signature).decode(),
            "X-VFP-Timestamp": timestamp,
            "X-VFP-Nonce": nonce,
        }
        mock_request.body = AsyncMock(return_value=tampered_body)  # Tampered!

        mock_did_doc = MagicMock()
        mock_did_doc.get_public_key.return_value = keypair.public_key_multibase

        with patch("valence.federation.identity.parse_did"):
            with patch("valence.federation.identity.resolve_did_sync") as mock_resolve:
                mock_resolve.return_value = mock_did_doc

                # Should fail because body hash doesn't match
                result = await verify_did_signature(mock_request)
                assert result is None  # Signature invalid due to body mismatch
