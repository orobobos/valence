# Federation Embedding Standard

> Ensuring semantic compatibility across the Valence network.

---

## Overview

For cross-node semantic queries to work correctly, all federation nodes must use compatible embeddings. This document specifies the federation embedding standard.

## The Standard

| Property | Value |
|----------|-------|
| **Model** | `BAAI/bge-small-en-v1.5` |
| **Dimensions** | 384 |
| **Normalization** | L2 (unit vectors) |
| **Type Identifier** | `bge_small_en_v15` |
| **Version** | 1.0 |

### Why bge-small-en-v1.5?

1. **Quality** — Excellent semantic similarity scores, competitive with larger models
2. **Efficiency** — Only 33M parameters, fast inference on CPU
3. **Open** — Apache 2.0 license, no API costs
4. **Privacy** — Can run entirely locally, no data leaves the node
5. **Standard** — Widely supported by embedding libraries

## Protocol Requirements

### Outbound Beliefs

When sharing beliefs via federation, nodes SHOULD include embeddings:

```json
{
  "belief_id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "PostgreSQL supports JSONB for semi-structured data",
  "confidence": 0.85,
  "embedding": [0.0234, -0.0156, ...],  // 384 floats
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "embedding_dims": 384,
  "embedding_type": "bge_small_en_v15"
}
```

### Inbound Validation

Receiving nodes MUST validate incoming embeddings:

1. **Dimension check** — Must be exactly 384 dimensions
2. **Normalization check** — Must be L2 normalized (magnitude ≈ 1.0)
3. **Model check** — If metadata provided, must match standard

Invalid embeddings are rejected with error:
```json
{
  "error_code": "INVALID_REQUEST",
  "message": "Invalid federation embedding: Embedding dimensions mismatch: expected 384, got 1536"
}
```

### Missing Embeddings

If a belief arrives without an embedding:
- The receiving node generates one locally
- This ensures all stored beliefs have searchable embeddings
- No rejection occurs for missing embeddings

## Implementation

### Python API

```python
from valence.embeddings.federation import (
    get_federation_standard,
    is_federation_compatible,
    validate_federation_embedding,
    prepare_belief_for_federation,
)

# Get the standard
standard = get_federation_standard()
print(f"Model: {standard['model']}")  # BAAI/bge-small-en-v1.5
print(f"Dims: {standard['dimensions']}")  # 384

# Check compatibility
if is_federation_compatible("bge_small_en_v15", 384):
    print("Compatible!")

# Validate an embedding
is_valid, error = validate_federation_embedding(embedding_vector)
if not is_valid:
    print(f"Invalid: {error}")

# Prepare belief for federation (async)
belief_data = await prepare_belief_for_federation(belief_id)
# Includes embedding, embedding_model, embedding_dims, embedding_type
```

### Generating Embeddings

```python
from valence.embeddings.providers.local import generate_embedding

# Generate a federation-compatible embedding
embedding = generate_embedding("Your text here")
assert len(embedding) == 384  # Always 384 dimensions
```

### Environment Configuration

```bash
# Use default model (recommended)
# No configuration needed

# Custom model path (air-gapped environments)
export VALENCE_EMBEDDING_MODEL_PATH=/opt/models/bge-small-en-v1.5

# Force CPU (default)
export VALENCE_EMBEDDING_DEVICE=cpu

# Use GPU if available
export VALENCE_EMBEDDING_DEVICE=cuda
```

## Migration

### Existing Beliefs

Beliefs with non-standard embeddings (e.g., OpenAI's text-embedding-3-small) work fine locally but need conversion for federation:

```bash
# Re-embed all beliefs with federation standard
valence embeddings backfill --type bge_small_en_v15 --force
```

The `prepare_belief_for_federation()` function handles this automatically — it checks if the belief has a compatible embedding and generates one if needed.

### Gradual Rollout

1. **Phase 1**: Update nodes to support federation embeddings (this release)
2. **Phase 2**: Enable embedding validation in federation sync
3. **Phase 3**: Require embeddings for semantic federation queries

## Semantic Queries Across Federation

With standardized embeddings, cross-node semantic search works seamlessly:

```bash
# Query your local beliefs + federated peers
valence query "PostgreSQL performance tips" --scope federated
```

The query embedding is generated locally using the same model, ensuring comparable similarity scores across all nodes.

## Security Considerations

1. **Embeddings are derived** — They don't leak more than the content itself
2. **No model drift** — Fixed model version ensures consistency
3. **Local generation** — Embeddings never sent to external APIs
4. **Validation** — Malformed embeddings are rejected

## Future Compatibility

### Version 2.0 (Planned)

The federation standard may be upgraded in the future:

- Larger models with better performance
- Multilingual support
- Domain-specific embeddings

Version negotiation will be handled via the federation handshake, allowing gradual migration while maintaining backward compatibility.

---

## Related Documentation

- [Local Embedding Provider](../../src/valence/embeddings/providers/local.py)
- [Federation Protocol](../FEDERATION_PROTOCOL.md)
- [Federation README](./README.md)

---

*"Semantic compatibility through standardization."*
