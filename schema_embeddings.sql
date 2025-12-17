-- Valence Embeddings Module
-- Multi-provider embedding support with registry and lazy table creation

-- Registry of embedding types
CREATE TABLE IF NOT EXISTS embedding_types (
    id TEXT PRIMARY KEY,  -- e.g., 'openai_text3_small', 'claude_opus_4_5'
    provider TEXT NOT NULL,  -- 'openai', 'anthropic', 'aws', 'local'
    model TEXT NOT NULL,  -- 'text-embedding-3-small', 'claude-opus-4-5-20251101'
    version TEXT,  -- additional version info if needed
    dimensions INTEGER NOT NULL,
    is_fallback INTEGER NOT NULL DEFAULT 0,  -- 1 if this is the semantic fallback
    status TEXT NOT NULL DEFAULT 'active',  -- 'active', 'deprecated', 'backfilling'
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CONSTRAINT valid_status CHECK (status IN ('active', 'deprecated', 'backfilling'))
);

-- Track what content has been embedded with which types
-- This is the junction table - actual vectors live in provider-specific tables
CREATE TABLE IF NOT EXISTS embedding_coverage (
    content_type TEXT NOT NULL,  -- 'entry', 'session', 'exchange', 'pattern', 'thought'
    content_id TEXT NOT NULL,
    embedding_type_id TEXT NOT NULL REFERENCES embedding_types(id),
    embedded_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (content_type, content_id, embedding_type_id)
);

-- Backfill queue for async embedding generation
CREATE TABLE IF NOT EXISTS embedding_backfill_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type TEXT NOT NULL,
    content_id TEXT NOT NULL,
    embedding_type_id TEXT NOT NULL REFERENCES embedding_types(id),
    priority INTEGER NOT NULL DEFAULT 0,  -- higher = more urgent
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    queued_at INTEGER NOT NULL DEFAULT (unixepoch()),
    completed_at INTEGER,
    UNIQUE (content_type, content_id, embedding_type_id)
);

-- Template for embedding tables (created dynamically per type)
-- Example: embeddings_openai_text3_small, embeddings_claude_opus_4_5
--
-- CREATE TABLE IF NOT EXISTS embeddings_{type_id} (
--     content_type TEXT NOT NULL,
--     content_id TEXT NOT NULL,
--     vector BLOB NOT NULL,  -- serialized float array
--     embedded_at INTEGER NOT NULL DEFAULT (unixepoch()),
--     model_response_id TEXT,  -- for provenance, if available from API
--     PRIMARY KEY (content_type, content_id)
-- );

-- Indexes
CREATE INDEX IF NOT EXISTS idx_embedding_coverage_type ON embedding_coverage(embedding_type_id);
CREATE INDEX IF NOT EXISTS idx_embedding_coverage_content ON embedding_coverage(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_backfill_queue_status ON embedding_backfill_queue(status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_backfill_queue_type ON embedding_backfill_queue(embedding_type_id);

-- View: embedding coverage summary
CREATE VIEW IF NOT EXISTS embedding_coverage_summary AS
SELECT
    et.id as embedding_type,
    et.provider,
    et.model,
    et.status,
    COUNT(ec.content_id) as content_count,
    MAX(ec.embedded_at) as last_embedded_at
FROM embedding_types et
LEFT JOIN embedding_coverage ec ON et.id = ec.embedding_type_id
GROUP BY et.id;

-- View: backfill queue status
CREATE VIEW IF NOT EXISTS backfill_queue_status AS
SELECT
    embedding_type_id,
    status,
    COUNT(*) as count
FROM embedding_backfill_queue
GROUP BY embedding_type_id, status;
