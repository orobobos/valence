"""Tests for embedding provider configuration (Issue #26, #122).

Verifies:
- VALENCE_EMBEDDING_PROVIDER environment variable support
- Local provider (default, uses bge-small-en-v1.5)
- OpenAI provider (optional, requires API key)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from valence.core.config import clear_config_cache
from valence.embeddings.service import (
    EmbeddingProvider,
    generate_embedding,
    generate_local_embedding,
    get_embedding_provider,
)


class TestEmbeddingProvider:
    """Test EmbeddingProvider enum."""

    def test_openai_provider(self):
        """OpenAI should be a valid provider."""
        assert EmbeddingProvider.OPENAI == "openai"

    def test_local_provider(self):
        """Local should be a valid provider."""
        assert EmbeddingProvider.LOCAL == "local"


class TestGetEmbeddingProvider:
    """Test provider detection from environment."""

    def test_default_is_local(self):
        """Default provider should be LOCAL (privacy-first)."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove VALENCE_EMBEDDING_PROVIDER if set
            os.environ.pop("VALENCE_EMBEDDING_PROVIDER", None)
            clear_config_cache()
            try:
                provider = get_embedding_provider()
                assert provider == EmbeddingProvider.LOCAL
            finally:
                clear_config_cache()

    def test_openai_from_env(self):
        """Should detect OpenAI from env."""
        with patch.dict(os.environ, {"VALENCE_EMBEDDING_PROVIDER": "openai"}):
            clear_config_cache()
            try:
                provider = get_embedding_provider()
                assert provider == EmbeddingProvider.OPENAI
            finally:
                clear_config_cache()

    def test_local_from_env(self):
        """Should detect local from env."""
        with patch.dict(os.environ, {"VALENCE_EMBEDDING_PROVIDER": "local"}):
            clear_config_cache()
            try:
                provider = get_embedding_provider()
                assert provider == EmbeddingProvider.LOCAL
            finally:
                clear_config_cache()

    def test_case_insensitive(self):
        """Should handle case variations."""
        test_cases = ["LOCAL", "Local", "LOCAL"]
        for value in test_cases:
            with patch.dict(os.environ, {"VALENCE_EMBEDDING_PROVIDER": value}):
                clear_config_cache()
                try:
                    provider = get_embedding_provider()
                    assert provider == EmbeddingProvider.LOCAL
                finally:
                    clear_config_cache()

    def test_unknown_defaults_to_local(self):
        """Unknown provider should default to LOCAL with warning."""
        with patch.dict(os.environ, {"VALENCE_EMBEDDING_PROVIDER": "unknown-provider"}):
            clear_config_cache()
            try:
                provider = get_embedding_provider()
                assert provider == EmbeddingProvider.LOCAL
            finally:
                clear_config_cache()


class TestLocalEmbedding:
    """Test local embedding provider (bge-small-en-v1.5)."""

    @pytest.fixture
    def mock_local_model(self):
        """Mock the local model to avoid loading it in tests."""
        import numpy as np
        from valence.embeddings.providers import local

        mock_model = MagicMock()
        # Return normalized 384-dim vector
        normalized_vec = np.random.randn(384).astype(np.float32)
        normalized_vec = normalized_vec / np.linalg.norm(normalized_vec)
        mock_model.encode.return_value = normalized_vec
        mock_model.get_sentence_embedding_dimension.return_value = 384

        local._model = mock_model
        yield mock_model
        local.reset_model()

    def test_local_embedding_returns_384_dimensions(self, mock_local_model):
        """Local embeddings should return 384 dimensions."""
        result = generate_local_embedding("test text")

        assert len(result) == 384

    def test_local_embedding_calls_encode(self, mock_local_model):
        """Local embeddings should call model.encode."""
        generate_local_embedding("test text")

        mock_local_model.encode.assert_called_once()


class TestGenerateEmbedding:
    """Test generate_embedding with provider routing."""

    @pytest.fixture
    def mock_openai(self):
        """Mock OpenAI client."""
        with patch("valence.embeddings.service.get_openai_client") as mock:
            client = MagicMock()
            mock.return_value = client

            # Mock response
            response = MagicMock()
            response.data = [MagicMock(embedding=[0.1] * 1536)]
            client.embeddings.create.return_value = response

            yield client

    @pytest.fixture
    def mock_local_model(self):
        """Mock local model."""
        import numpy as np
        from valence.embeddings.providers import local

        mock_model = MagicMock()
        normalized_vec = np.random.randn(384).astype(np.float32)
        normalized_vec = normalized_vec / np.linalg.norm(normalized_vec)
        mock_model.encode.return_value = normalized_vec
        mock_model.get_sentence_embedding_dimension.return_value = 384

        local._model = mock_model
        yield mock_model
        local.reset_model()

    def test_uses_local_by_default(self, mock_local_model):
        """Should use LOCAL when no provider specified."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("VALENCE_EMBEDDING_PROVIDER", None)
            result = generate_embedding("test text")

            assert len(result) == 384
            mock_local_model.encode.assert_called_once()

    def test_explicit_openai_provider(self, mock_openai):
        """Should use OpenAI when explicitly specified."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            result = generate_embedding("test text", provider=EmbeddingProvider.OPENAI)

            assert len(result) == 1536

    def test_explicit_local_provider(self, mock_local_model):
        """Should use local when explicitly specified."""
        result = generate_embedding("test", provider=EmbeddingProvider.LOCAL)

        assert len(result) == 384
        mock_local_model.encode.assert_called_once()

    def test_truncates_long_text(self, mock_openai):
        """Should truncate text over 8000 chars."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            long_text = "a" * 10000
            generate_embedding(long_text, provider=EmbeddingProvider.OPENAI)

            # Check that truncated text was sent
            call_args = mock_openai.embeddings.create.call_args
            sent_text = call_args.kwargs.get("input") or call_args[1].get("input")
            assert len(sent_text) == 8000


class TestBeliefOptOut:
    """Test belief federation opt-out flag (Issue #26)."""

    def test_belief_create_accepts_opt_out(self):
        """belief_create should accept opt_out_federation parameter."""
        # This tests the function signature accepts the parameter
        # Full integration test would require database
        import inspect

        from valence.substrate.tools import belief_create

        sig = inspect.signature(belief_create)
        params = list(sig.parameters.keys())

        assert "opt_out_federation" in params

    def test_belief_create_schema_includes_opt_out(self):
        """Tool schema should include opt_out_federation."""
        from valence.substrate.tools import SUBSTRATE_TOOLS

        belief_create_tool = next(t for t in SUBSTRATE_TOOLS if t.name == "belief_create")

        schema = belief_create_tool.inputSchema
        assert "opt_out_federation" in schema["properties"]
        assert schema["properties"]["opt_out_federation"]["type"] == "boolean"
