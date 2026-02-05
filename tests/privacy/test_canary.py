"""Tests for canary token system."""

from datetime import UTC, datetime

import pytest
from valence.privacy.canary import (
    ZERO_WIDTH_JOINER,
    ZERO_WIDTH_NON_JOINER,
    ZERO_WIDTH_SPACE,
    CanaryRegistry,
    CanaryToken,
    EmbeddingStrategy,
    LeakReport,
    _decode_from_zero_width,
    _encode_to_zero_width,
    detect_canaries,
    embed_canary,
    strip_canaries,
)


class TestCanaryToken:
    """Tests for CanaryToken dataclass."""

    def test_generate_creates_unique_tokens(self):
        """Each generated token should have a unique ID."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        token1 = CanaryToken.generate(secret_key)
        token2 = CanaryToken.generate(secret_key)

        assert token1.token_id != token2.token_id
        assert token1.signature != token2.signature

    def test_generate_with_recipient_id(self):
        """Token should store recipient_id."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        token = CanaryToken.generate(secret_key, recipient_id="user-123")

        assert token.recipient_id == "user-123"

    def test_generate_with_content_hash(self):
        """Token should hash content for correlation."""
        secret_key = b"test-secret-key-32-bytes-long!!"
        content = "This is sensitive content"

        token = CanaryToken.generate(secret_key, content=content)

        assert token.content_hash is not None
        assert len(token.content_hash) == 16  # Truncated SHA256

    def test_generate_with_metadata(self):
        """Token should store metadata."""
        secret_key = b"test-secret-key-32-bytes-long!!"
        metadata = {"purpose": "test", "version": "1.0"}

        token = CanaryToken.generate(secret_key, metadata=metadata)

        assert token.metadata == metadata

    def test_verify_valid_signature(self):
        """Valid signature should verify."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        token = CanaryToken.generate(secret_key)

        assert token.verify(secret_key) is True

    def test_verify_invalid_signature(self):
        """Invalid signature should not verify."""
        secret_key = b"test-secret-key-32-bytes-long!!"
        wrong_key = b"wrong-secret-key-32-bytes-long!"

        token = CanaryToken.generate(secret_key)

        assert token.verify(wrong_key) is False

    def test_verify_tampered_token(self):
        """Tampered token should not verify."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        token = CanaryToken.generate(secret_key)
        token.token_id = "canary_tampered_id"

        assert token.verify(secret_key) is False

    def test_to_marker(self):
        """Token should convert to compact marker string."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        token = CanaryToken.generate(secret_key)
        marker = token.to_marker()

        assert marker.startswith("canary_")
        assert ":" in marker
        parts = marker.split(":")
        assert len(parts) == 2
        assert len(parts[1]) == 16  # Truncated signature

    def test_from_marker_valid(self):
        """Valid marker should reconstruct token."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        original = CanaryToken.generate(secret_key)
        marker = original.to_marker()

        reconstructed = CanaryToken.from_marker(marker, secret_key)

        assert reconstructed is not None
        assert reconstructed.token_id == original.token_id
        assert reconstructed.verify(secret_key) is True

    def test_from_marker_invalid(self):
        """Invalid marker should return None."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        result = CanaryToken.from_marker("invalid-marker", secret_key)
        assert result is None

        result = CanaryToken.from_marker("canary_fake:wrongsig", secret_key)
        assert result is None

    def test_created_at_timestamp(self):
        """Token should have creation timestamp."""
        secret_key = b"test-secret-key-32-bytes-long!!"

        before = datetime.now(UTC)
        token = CanaryToken.generate(secret_key)
        after = datetime.now(UTC)

        assert before <= token.created_at <= after


class TestZeroWidthEncoding:
    """Tests for zero-width unicode encoding."""

    def test_encode_decode_simple(self):
        """Simple string should encode and decode."""
        original = "hello"

        encoded = _encode_to_zero_width(original)
        decoded = _decode_from_zero_width(encoded)

        assert decoded == original

    def test_encode_decode_marker(self):
        """Token marker should encode and decode."""
        marker = "canary_abc123def456_12345678:abcdef0123456789"

        encoded = _encode_to_zero_width(marker)
        decoded = _decode_from_zero_width(encoded)

        assert decoded == marker

    def test_encoded_uses_zero_width_chars(self):
        """Encoded string should only use zero-width characters."""
        encoded = _encode_to_zero_width("test")

        allowed = {ZERO_WIDTH_SPACE, ZERO_WIDTH_NON_JOINER, ZERO_WIDTH_JOINER}
        for char in encoded:
            assert char in allowed

    def test_encoded_is_invisible(self):
        """Encoded string should have zero visible width."""
        original = "test"
        encoded = _encode_to_zero_width(original)

        # When displayed, these characters have no width
        # We can't test visual width, but we can verify the characters
        assert len(encoded) > 0
        assert all(ord(c) in (0x200B, 0x200C, 0x200D) for c in encoded)

    def test_decode_empty_returns_none(self):
        """Empty or invalid input should return None."""
        assert _decode_from_zero_width("") is None
        assert _decode_from_zero_width("regular text") is None


class TestEmbedCanary:
    """Tests for embed_canary function."""

    @pytest.fixture
    def token(self):
        """Create a test token."""
        return CanaryToken.generate(b"test-secret-key-32-bytes-long!!")

    def test_embed_visible_end(self, token):
        """Visible embedding at end."""
        content = "This is the content."

        result = embed_canary(content, token, EmbeddingStrategy.VISIBLE, "end")

        assert content in result
        assert "[CANARY:" in result
        assert result.endswith(f"[CANARY:{token.to_marker()}]")

    def test_embed_visible_start(self, token):
        """Visible embedding at start."""
        content = "This is the content."

        result = embed_canary(content, token, EmbeddingStrategy.VISIBLE, "start")

        assert content in result
        assert result.startswith(f"[CANARY:{token.to_marker()}]")

    def test_embed_visible_distributed(self, token):
        """Visible embedding distributed in content."""
        content = "Line 1\nLine 2\nLine 3\nLine 4"

        result = embed_canary(content, token, EmbeddingStrategy.VISIBLE, "distributed")

        assert "CANARY:" in result
        assert "<!--" in result  # Should be in HTML comment

    def test_embed_invisible_end(self, token):
        """Invisible embedding at end."""
        content = "This is the content."

        result = embed_canary(content, token, EmbeddingStrategy.INVISIBLE, "end")

        # Content should appear unchanged to naked eye
        assert result.startswith(content)
        # But should be longer due to invisible characters
        assert len(result) > len(content)

    def test_embed_invisible_start(self, token):
        """Invisible embedding at start."""
        content = "This is the content."

        result = embed_canary(content, token, EmbeddingStrategy.INVISIBLE, "start")

        # Content should appear at end
        assert result.endswith(content)
        assert len(result) > len(content)

    def test_embed_invisible_distributed(self, token):
        """Invisible embedding distributed across words."""
        content = "This is a longer piece of content with many words."

        result = embed_canary(content, token, EmbeddingStrategy.INVISIBLE, "distributed")

        # Should contain invisible characters
        zero_width_chars = {ZERO_WIDTH_SPACE, ZERO_WIDTH_NON_JOINER, ZERO_WIDTH_JOINER}
        has_invisible = any(c in zero_width_chars for c in result)
        assert has_invisible

    def test_default_is_invisible_end(self, token):
        """Default embedding should be invisible at end."""
        content = "This is the content."

        result = embed_canary(content, token)

        assert result.startswith(content)
        assert len(result) > len(content)


class TestDetectCanaries:
    """Tests for detect_canaries function."""

    @pytest.fixture
    def secret_key(self):
        return b"test-secret-key-32-bytes-long!!"

    @pytest.fixture
    def token(self, secret_key):
        return CanaryToken.generate(secret_key)

    def test_detect_visible_marker(self, token, secret_key):
        """Detect visible canary markers."""
        content = f"Some text [CANARY:{token.to_marker()}] more text"

        detected = detect_canaries(content, secret_key)

        assert len(detected) == 1
        assert detected[0].token_id == token.token_id

    def test_detect_html_comment_marker(self, token, secret_key):
        """Detect HTML comment canary markers."""
        content = f"Some text <!-- [CANARY:{token.to_marker()}] --> more text"

        detected = detect_canaries(content, secret_key)

        assert len(detected) == 1
        assert detected[0].token_id == token.token_id

    def test_detect_invisible_marker(self, token, secret_key):
        """Detect invisible canary markers."""
        content = "This is content."
        embedded = embed_canary(content, token, EmbeddingStrategy.INVISIBLE)

        detected = detect_canaries(embedded, secret_key)

        assert len(detected) == 1
        assert detected[0].token_id == token.token_id

    def test_detect_multiple_markers(self, secret_key):
        """Detect multiple canary markers in same content."""
        token1 = CanaryToken.generate(secret_key)
        token2 = CanaryToken.generate(secret_key)

        content = f"[CANARY:{token1.to_marker()}] text [CANARY:{token2.to_marker()}]"

        detected = detect_canaries(content, secret_key)

        assert len(detected) == 2
        token_ids = {d.token_id for d in detected}
        assert token1.token_id in token_ids
        assert token2.token_id in token_ids

    def test_detect_without_secret_key(self, token):
        """Detect without verification (no secret key)."""
        content = f"[CANARY:{token.to_marker()}]"

        detected = detect_canaries(content)  # No secret key

        assert len(detected) == 1
        assert detected[0].token_id == token.token_id

    def test_detect_no_canaries(self, secret_key):
        """Return empty list when no canaries present."""
        content = "This is normal content without any markers."

        detected = detect_canaries(content, secret_key)

        assert len(detected) == 0

    def test_detect_invalid_signature_rejected(self, secret_key):
        """Invalid signatures should be rejected when key provided."""
        # Create marker with wrong signature
        content = "[CANARY:canary_fake12345678_12345678:0000000000000000]"

        detected = detect_canaries(content, secret_key)

        assert len(detected) == 0

    def test_roundtrip_visible(self, token, secret_key):
        """Embed and detect visible marker."""
        content = "Original content here."

        embedded = embed_canary(content, token, EmbeddingStrategy.VISIBLE)
        detected = detect_canaries(embedded, secret_key)

        assert len(detected) == 1
        assert detected[0].token_id == token.token_id
        assert detected[0].verify(secret_key)

    def test_roundtrip_invisible(self, token, secret_key):
        """Embed and detect invisible marker."""
        content = "Original content here."

        embedded = embed_canary(content, token, EmbeddingStrategy.INVISIBLE)
        detected = detect_canaries(embedded, secret_key)

        assert len(detected) == 1
        assert detected[0].token_id == token.token_id
        assert detected[0].verify(secret_key)


class TestStripCanaries:
    """Tests for strip_canaries function."""

    @pytest.fixture
    def token(self):
        return CanaryToken.generate(b"test-secret-key-32-bytes-long!!")

    def test_strip_visible_marker(self, token):
        """Strip visible canary markers."""
        original = "Clean content."
        embedded = embed_canary(original, token, EmbeddingStrategy.VISIBLE)

        stripped = strip_canaries(embedded)

        assert "[CANARY:" not in stripped
        assert original in stripped.strip()

    def test_strip_html_comment_marker(self, token):
        """Strip HTML comment canary markers."""
        content = f"Some text <!-- [CANARY:{token.to_marker()}] --> more text"

        stripped = strip_canaries(content)

        assert "[CANARY:" not in stripped
        assert "<!--" not in stripped

    def test_strip_invisible_marker(self, token):
        """Strip invisible canary markers."""
        original = "Clean content."
        embedded = embed_canary(original, token, EmbeddingStrategy.INVISIBLE)

        stripped = strip_canaries(embedded)

        # Should be back to original length (or close)
        zero_width_chars = {ZERO_WIDTH_SPACE, ZERO_WIDTH_NON_JOINER, ZERO_WIDTH_JOINER}
        has_invisible = any(c in zero_width_chars for c in stripped)
        assert not has_invisible

    def test_strip_multiple_markers(self):
        """Strip multiple canary markers."""
        token1 = CanaryToken.generate(b"test-secret-key-32-bytes-long!!")
        token2 = CanaryToken.generate(b"test-secret-key-32-bytes-long!!")

        content = f"[CANARY:{token1.to_marker()}] text [CANARY:{token2.to_marker()}]"

        stripped = strip_canaries(content)

        assert "[CANARY:" not in stripped
        assert "text" in stripped

    def test_strip_preserves_clean_content(self):
        """Stripping clean content should not alter it."""
        original = "This is clean content without any markers."

        stripped = strip_canaries(original)

        assert stripped == original


class TestCanaryRegistry:
    """Tests for CanaryRegistry class."""

    @pytest.fixture
    def registry(self):
        return CanaryRegistry()

    def test_issue_token(self, registry):
        """Registry should issue and track tokens."""
        token = registry.issue_token(recipient_id="user-123")

        assert token.token_id is not None
        assert token.recipient_id == "user-123"
        assert token.verify(registry.secret_key)

    def test_get_token(self, registry):
        """Registry should retrieve tokens by ID."""
        token = registry.issue_token()

        retrieved = registry.get_token(token.token_id)

        assert retrieved is not None
        assert retrieved.token_id == token.token_id

    def test_get_nonexistent_token(self, registry):
        """Getting nonexistent token returns None."""
        result = registry.get_token("nonexistent")
        assert result is None

    def test_list_tokens(self, registry):
        """List all registered tokens."""
        token1 = registry.issue_token(recipient_id="user-1")
        token2 = registry.issue_token(recipient_id="user-2")

        tokens = registry.list_tokens()

        assert len(tokens) == 2
        token_ids = {t.token_id for t in tokens}
        assert token1.token_id in token_ids
        assert token2.token_id in token_ids

    def test_list_tokens_by_recipient(self, registry):
        """List tokens filtered by recipient."""
        registry.issue_token(recipient_id="user-1")
        token2 = registry.issue_token(recipient_id="user-2")
        registry.issue_token(recipient_id="user-1")

        tokens = registry.list_tokens(recipient_id="user-2")

        assert len(tokens) == 1
        assert tokens[0].token_id == token2.token_id

    def test_scan_for_leaks(self, registry):
        """Scan content for leaked tokens."""
        token = registry.issue_token(recipient_id="user-123")
        content = f"Leaked content [CANARY:{token.to_marker()}] here"

        reports = registry.scan_for_leaks(content, source="pastebin.com")

        assert len(reports) == 1
        assert reports[0].token.token_id == token.token_id
        assert reports[0].source == "pastebin.com"
        assert reports[0].verified is True

    def test_scan_detects_unregistered_token(self, registry):
        """Scan detects tokens not in registry (forged or from other registry)."""
        other_token = CanaryToken.generate(b"other-secret-key-here!!!!!!!!!!!")
        content = f"Content [CANARY:{other_token.to_marker()}]"

        # Without secret key verification, it will still be detected
        # but not verified
        reports = registry.scan_for_leaks(content, source="unknown")

        # It won't match because signature verification fails with wrong key
        assert len(reports) == 0

    def test_get_leaks(self, registry):
        """Get recorded leak reports."""
        token = registry.issue_token(recipient_id="user-123")
        content = f"[CANARY:{token.to_marker()}]"

        registry.scan_for_leaks(content, source="source1")
        registry.scan_for_leaks(content, source="source2")

        leaks = registry.get_leaks()
        assert len(leaks) == 2

        leaks = registry.get_leaks(token_id=token.token_id)
        assert len(leaks) == 2

    def test_get_leaks_by_recipient(self, registry):
        """Get leaks filtered by recipient."""
        token1 = registry.issue_token(recipient_id="user-1")
        token2 = registry.issue_token(recipient_id="user-2")

        registry.scan_for_leaks(f"[CANARY:{token1.to_marker()}]", source="s1")
        registry.scan_for_leaks(f"[CANARY:{token2.to_marker()}]", source="s2")

        leaks = registry.get_leaks(recipient_id="user-1")

        assert len(leaks) == 1
        assert leaks[0].token.recipient_id == "user-1"

    def test_revoke_token(self, registry):
        """Revoke a token."""
        token = registry.issue_token()

        result = registry.revoke_token(token.token_id)

        assert result is True
        assert registry.get_token(token.token_id) is None

    def test_revoke_nonexistent_token(self, registry):
        """Revoking nonexistent token returns False."""
        result = registry.revoke_token("nonexistent")
        assert result is False

    def test_export_import_state(self, registry):
        """Export and import registry state."""
        token = registry.issue_token(
            recipient_id="user-123",
            content="test content",
            metadata={"key": "value"},
        )
        registry.scan_for_leaks(f"[CANARY:{token.to_marker()}]", source="test")

        state = registry.export_state()

        # Create new registry from state
        restored = CanaryRegistry.from_state(state, registry.secret_key)

        # Verify tokens restored
        restored_token = restored.get_token(token.token_id)
        assert restored_token is not None
        assert restored_token.recipient_id == "user-123"
        assert restored_token.metadata == {"key": "value"}

        # Verify leaks restored
        leaks = restored.get_leaks()
        assert len(leaks) == 1
        assert leaks[0].source == "test"


class TestLeakReport:
    """Tests for LeakReport dataclass."""

    def test_leak_report_creation(self):
        """Create a leak report."""
        token = CanaryToken.generate(b"test-secret-key-32-bytes-long!!")

        report = LeakReport(
            token=token,
            detected_at=datetime.now(UTC),
            source="pastebin.com",
            context="...leaked content...",
            verified=True,
        )

        assert report.token.token_id == token.token_id
        assert report.source == "pastebin.com"
        assert report.verified is True


class TestIntegrationScenarios:
    """Integration tests for realistic scenarios."""

    def test_document_sharing_tracking(self):
        """Track document sharing to multiple recipients."""
        registry = CanaryRegistry()
        document = "Confidential: Q4 financial results..."

        # Share to multiple recipients
        recipients = ["alice", "bob", "charlie"]
        shared_docs = {}

        for recipient in recipients:
            token = registry.issue_token(
                recipient_id=recipient,
                content=document,
                metadata={"document_type": "financial"},
            )
            shared_docs[recipient] = embed_canary(document, token, EmbeddingStrategy.INVISIBLE)

        # Simulate leak detection
        leaked_content = shared_docs["bob"]  # Bob leaked the document

        reports = registry.scan_for_leaks(
            leaked_content,
            source="suspicious-forum.com",
        )

        assert len(reports) == 1
        assert reports[0].token.recipient_id == "bob"
        assert reports[0].verified is True

    def test_multiple_embedding_strategies(self):
        """Test both embedding strategies in same workflow."""
        registry = CanaryRegistry()
        content = "This is sensitive information."

        # Internal use: visible markers for debugging
        internal_token = registry.issue_token(
            recipient_id="internal-team",
            metadata={"visibility": "visible"},
        )
        internal_doc = embed_canary(content, internal_token, EmbeddingStrategy.VISIBLE)

        # External use: invisible markers
        external_token = registry.issue_token(
            recipient_id="external-partner",
            metadata={"visibility": "invisible"},
        )
        external_doc = embed_canary(content, external_token, EmbeddingStrategy.INVISIBLE)

        # Both should be detectable
        internal_detected = detect_canaries(internal_doc, registry.secret_key)
        external_detected = detect_canaries(external_doc, registry.secret_key)

        assert len(internal_detected) == 1
        assert len(external_detected) == 1
        assert internal_detected[0].token_id == internal_token.token_id
        assert external_detected[0].token_id == external_token.token_id

    def test_stripping_attack_detection(self):
        """Detect when someone tries to strip canaries."""
        registry = CanaryRegistry()

        # Original document with canary
        token = registry.issue_token(recipient_id="user")
        original = "Confidential document content."
        embedded = embed_canary(original, token, EmbeddingStrategy.INVISIBLE)

        # Attacker strips canaries
        stripped = strip_canaries(embedded)

        # Original embedded version is detectable
        assert len(detect_canaries(embedded, registry.secret_key)) == 1

        # Stripped version has no canaries
        assert len(detect_canaries(stripped, registry.secret_key)) == 0

        # Note: Detection of stripping requires out-of-band verification
        # (e.g., comparing content hash with registered token)
