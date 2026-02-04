"""Tests for local embedding provider (sentence-transformers/bge-small-en-v1.5)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ============================================================================
# Model Loading Tests
# ============================================================================

class TestGetModel:
    """Tests for get_model function."""

    def test_lazy_loading(self):
        """Should lazily initialize model on first call."""
        from valence.embeddings.providers import local
        
        # Reset model
        local.reset_model()
        
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_st:
            model = local.get_model()
            
            mock_st.assert_called_once()
            assert model is mock_model

    def test_reuses_cached_model(self):
        """Should reuse cached model on subsequent calls."""
        from valence.embeddings.providers import local
        
        mock_model = MagicMock()
        local._model = mock_model
        
        result = local.get_model()
        
        assert result is mock_model

    def test_respects_device_env(self):
        """Should use VALENCE_EMBEDDING_DEVICE env var."""
        from valence.embeddings.providers import local
        
        local.reset_model()
        
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        
        with patch.dict(os.environ, {"VALENCE_EMBEDDING_DEVICE": "cuda"}):
            with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_st:
                local.get_model()
                
                mock_st.assert_called_once()
                call_kwargs = mock_st.call_args
                assert call_kwargs[1]["device"] == "cuda"

    def test_respects_model_path_env(self):
        """Should use VALENCE_EMBEDDING_MODEL_PATH env var."""
        from valence.embeddings.providers import local
        
        local.reset_model()
        
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        
        custom_model = "custom/model-path"
        with patch.dict(os.environ, {"VALENCE_EMBEDDING_MODEL_PATH": custom_model}):
            with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_st:
                local.get_model()
                
                mock_st.assert_called_once()
                call_args = mock_st.call_args
                assert call_args[0][0] == custom_model


# ============================================================================
# Single Embedding Tests
# ============================================================================

class TestGenerateEmbedding:
    """Tests for generate_embedding function."""

    @pytest.fixture
    def mock_model(self):
        """Create mock model that returns proper embeddings."""
        model = MagicMock()
        # Return normalized 384-dim vector
        normalized_vec = np.random.randn(384).astype(np.float32)
        normalized_vec = normalized_vec / np.linalg.norm(normalized_vec)
        model.encode.return_value = normalized_vec
        model.get_sentence_embedding_dimension.return_value = 384
        return model

    def test_returns_list_of_floats(self, mock_model):
        """Should return list of floats."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        result = local.generate_embedding("test text")
        
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)

    def test_returns_384_dimensions(self, mock_model):
        """Should return 384-dimensional vector for BGE model."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        result = local.generate_embedding("test text")
        
        assert len(result) == 384

    def test_l2_normalized(self, mock_model):
        """Should return L2 normalized embeddings."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        result = local.generate_embedding("test text")
        
        # Check L2 norm is approximately 1
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 0.001, f"L2 norm should be 1.0, got {norm}"

    def test_calls_encode_with_normalize(self, mock_model):
        """Should call encode with normalize_embeddings=True."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        local.generate_embedding("test text")
        
        mock_model.encode.assert_called_once()
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs.get("normalize_embeddings") is True


# ============================================================================
# Batch Embedding Tests
# ============================================================================

class TestGenerateEmbeddingsBatch:
    """Tests for generate_embeddings_batch function."""

    @pytest.fixture
    def mock_model(self):
        """Create mock model that returns proper batch embeddings."""
        model = MagicMock()
        
        def mock_encode(texts, **kwargs):
            # Return normalized vectors for each text
            n = len(texts) if isinstance(texts, list) else 1
            vecs = np.random.randn(n, 384).astype(np.float32)
            # Normalize each row
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            return vecs / norms
        
        model.encode.side_effect = mock_encode
        model.get_sentence_embedding_dimension.return_value = 384
        return model

    def test_returns_list_of_embeddings(self, mock_model):
        """Should return list of embedding lists."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        texts = ["text 1", "text 2", "text 3"]
        result = local.generate_embeddings_batch(texts)
        
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(emb, list) for emb in result)

    def test_each_embedding_384_dimensions(self, mock_model):
        """Each embedding should be 384 dimensions."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        texts = ["text 1", "text 2"]
        result = local.generate_embeddings_batch(texts)
        
        for emb in result:
            assert len(emb) == 384

    def test_respects_batch_size(self, mock_model):
        """Should pass batch_size to encode."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        texts = ["text"] * 10
        local.generate_embeddings_batch(texts, batch_size=5)
        
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs.get("batch_size") == 5

    def test_shows_progress_for_large_batches(self, mock_model):
        """Should show progress bar for >100 texts by default."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        texts = ["text"] * 150
        local.generate_embeddings_batch(texts)
        
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs.get("show_progress_bar") is True

    def test_no_progress_for_small_batches(self, mock_model):
        """Should not show progress bar for <=100 texts by default."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        texts = ["text"] * 50
        local.generate_embeddings_batch(texts)
        
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs.get("show_progress_bar") is False

    def test_explicit_show_progress(self, mock_model):
        """Should respect explicit show_progress parameter."""
        from valence.embeddings.providers import local
        
        local._model = mock_model
        
        texts = ["text"] * 10
        local.generate_embeddings_batch(texts, show_progress=True)
        
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs.get("show_progress_bar") is True


# ============================================================================
# Integration with Service Tests
# ============================================================================

class TestServiceIntegration:
    """Tests for integration with embedding service."""

    def test_local_provider_default(self):
        """Local should be the default provider."""
        from valence.embeddings.service import get_embedding_provider, EmbeddingProvider
        
        # Clear env to test default
        with patch.dict(os.environ, {}, clear=True):
            # Need to clear VALENCE_EMBEDDING_PROVIDER specifically
            os.environ.pop("VALENCE_EMBEDDING_PROVIDER", None)
            
            provider = get_embedding_provider()
            assert provider == EmbeddingProvider.LOCAL

    def test_openai_provider_override(self):
        """Should use OpenAI when explicitly configured."""
        from valence.embeddings.service import get_embedding_provider, EmbeddingProvider
        
        with patch.dict(os.environ, {"VALENCE_EMBEDDING_PROVIDER": "openai"}):
            provider = get_embedding_provider()
            assert provider == EmbeddingProvider.OPENAI

    def test_generate_embedding_uses_local(self):
        """generate_embedding should use local provider by default."""
        from valence.embeddings import service
        from valence.embeddings.providers import local
        
        # Mock the local provider
        mock_embedding = [0.1] * 384
        with patch.object(local, "_model", MagicMock()):
            with patch("valence.embeddings.providers.local.generate_embedding", return_value=mock_embedding):
                with patch.dict(os.environ, {"VALENCE_EMBEDDING_PROVIDER": "local"}):
                    result = service.generate_embedding("test", provider=service.EmbeddingProvider.LOCAL)
                    
                    assert result == mock_embedding


# ============================================================================
# Reset Model Tests
# ============================================================================

class TestResetModel:
    """Tests for reset_model function."""

    def test_clears_cached_model(self):
        """Should clear the cached model."""
        from valence.embeddings.providers import local
        
        local._model = MagicMock()
        
        local.reset_model()
        
        assert local._model is None
