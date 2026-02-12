-- Migration 011: Replace IVFFlat with HNSW indexes (#360)
-- HNSW provides better recall, doesn't need training data, and handles
-- growing datasets without reindexing. Trade-off: slightly more memory.
--
-- Parameters: m=16 (connections per layer), ef_construction=200 (build quality)
-- These are good defaults for datasets up to ~1M vectors.

-- Drop old IVFFlat indexes
DROP INDEX IF EXISTS idx_beliefs_embedding;
DROP INDEX IF EXISTS idx_exchanges_embedding;
DROP INDEX IF EXISTS idx_patterns_embedding;

-- Create HNSW indexes
CREATE INDEX IF NOT EXISTS idx_beliefs_embedding
    ON beliefs USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_exchanges_embedding
    ON vkb_exchanges USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_patterns_embedding
    ON vkb_patterns USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
