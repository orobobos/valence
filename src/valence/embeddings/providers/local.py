"""Local embedding provider using sentence-transformers.

Uses BAAI/bge-small-en-v1.5 by default - a high-quality, compact model
that produces 384-dimensional embeddings with excellent semantic similarity.

Configuration via environment variables:
- VALENCE_EMBEDDING_MODEL_PATH: Model name or local path (default: BAAI/bge-small-en-v1.5)
- VALENCE_EMBEDDING_DEVICE: Device to use (cpu|cuda, default: cpu)

The model is lazily loaded on first use and cached for subsequent calls.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Model singleton (lazy loaded)
_model: "SentenceTransformer | None" = None

# Default model - bge-small-en-v1.5 is excellent for semantic similarity
# 384 dimensions, ~33M params, fast inference
MODEL_NAME = "BAAI/bge-small-en-v1.5"

# BGE models produce 384-dimensional embeddings
EMBEDDING_DIMENSIONS = 384


def get_model() -> "SentenceTransformer":
    """Get or initialize the sentence transformer model.
    
    The model is lazily loaded and cached for reuse.
    
    Environment variables:
        VALENCE_EMBEDDING_MODEL_PATH: Model name/path (default: BAAI/bge-small-en-v1.5)
        VALENCE_EMBEDDING_DEVICE: Device to run on (cpu|cuda, default: cpu)
    
    Returns:
        Loaded SentenceTransformer model
    """
    global _model
    
    if _model is None:
        from sentence_transformers import SentenceTransformer
        
        model_path = os.environ.get("VALENCE_EMBEDDING_MODEL_PATH", MODEL_NAME)
        device = os.environ.get("VALENCE_EMBEDDING_DEVICE", "cpu")
        
        logger.info(f"Loading embedding model {model_path} on {device}...")
        _model = SentenceTransformer(model_path, device=device)
        logger.info(f"Embedding model ready (dim={_model.get_sentence_embedding_dimension()})")
    
    return _model


def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding for text.
    
    Uses BGE model which produces L2-normalized embeddings by default
    when normalize_embeddings=True.
    
    Args:
        text: Text to embed
        
    Returns:
        384-dimensional embedding vector (L2 normalized)
    """
    model = get_model()
    
    # BGE models work best with a query prefix for retrieval tasks,
    # but for storage we embed without prefix
    embedding = model.encode(text, normalize_embeddings=True)
    
    return embedding.tolist()


def generate_embeddings_batch(
    texts: list[str],
    batch_size: int = 32,
    show_progress: bool | None = None,
) -> list[list[float]]:
    """Generate embeddings for multiple texts efficiently.
    
    Uses batching for better throughput on GPU/CPU.
    Shows progress bar for large batches (>100 texts).
    
    Args:
        texts: List of texts to embed
        batch_size: Batch size for processing (default: 32)
        show_progress: Show progress bar (default: True if >100 texts)
        
    Returns:
        List of 384-dimensional embedding vectors (L2 normalized)
    """
    model = get_model()
    
    if show_progress is None:
        show_progress = len(texts) > 100
    
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=show_progress,
    )
    
    return embeddings.tolist()


def reset_model() -> None:
    """Reset the cached model (useful for testing)."""
    global _model
    _model = None
