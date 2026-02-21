-- Migration 023: V2 Knowledge System
-- Drops federation/consensus/staking tables, reshapes beliefs→articles,
-- adds provenance tracking, contentions, usage traces, mutation queue.
--
-- Apply via:  psql $DATABASE_URL -f migrations/023_v2_knowledge_system.sql
-- NOTE: This migration is also wrapped in 023_v2_knowledge_system.py for
--       the Python migration runner.

BEGIN;

-- ============================================================================
-- PHASE 1: DROP FEDERATION / CONSENSUS / STAKING / VERIFICATION VIEWS
-- ============================================================================

DROP VIEW IF EXISTS pending_disputes CASCADE;
DROP VIEW IF EXISTS verifier_leaderboard CASCADE;
DROP VIEW IF EXISTS belief_verification_stats CASCADE;
DROP VIEW IF EXISTS sync_status_overview CASCADE;
DROP VIEW IF EXISTS federated_beliefs CASCADE;
DROP VIEW IF EXISTS federation_nodes_with_trust CASCADE;
DROP VIEW IF EXISTS active_shares CASCADE;
DROP VIEW IF EXISTS shares_with_consent CASCADE;

-- Drop old beliefs views (will be replaced with article_ versions)
DROP VIEW IF EXISTS beliefs_current CASCADE;
DROP VIEW IF EXISTS beliefs_with_entities CASCADE;

-- ============================================================================
-- PHASE 2: DROP FEDERATION / CONSENSUS / STAKING / VERIFICATION TABLES
-- ============================================================================

DROP TABLE IF EXISTS consensus_votes CASCADE;
DROP TABLE IF EXISTS tension_resolutions CASCADE;
DROP TABLE IF EXISTS sync_events CASCADE;
DROP TABLE IF EXISTS sync_outbound_queue CASCADE;
DROP TABLE IF EXISTS sync_state CASCADE;
DROP TABLE IF EXISTS aggregation_sources CASCADE;
DROP TABLE IF EXISTS aggregated_beliefs CASCADE;
DROP TABLE IF EXISTS belief_trust_annotations CASCADE;
DROP TABLE IF EXISTS user_node_trust CASCADE;
DROP TABLE IF EXISTS node_trust CASCADE;
DROP TABLE IF EXISTS belief_provenance CASCADE;
DROP TABLE IF EXISTS peer_nodes CASCADE;
DROP TABLE IF EXISTS federation_nodes CASCADE;
DROP TABLE IF EXISTS shares CASCADE;
DROP TABLE IF EXISTS consent_chains CASCADE;
DROP TABLE IF EXISTS stake_positions CASCADE;
DROP TABLE IF EXISTS reputation_events CASCADE;
DROP TABLE IF EXISTS discrepancy_bounties CASCADE;
DROP TABLE IF EXISTS disputes CASCADE;
DROP TABLE IF EXISTS verifications CASCADE;
DROP TABLE IF EXISTS reputations CASCADE;
DROP TABLE IF EXISTS trust_edges CASCADE;
DROP TABLE IF EXISTS extractors CASCADE;

-- ============================================================================
-- PHASE 3: RESHAPE SOURCES
-- ============================================================================

-- Full text content of the source (optional; some sources are just metadata)
ALTER TABLE sources ADD COLUMN IF NOT EXISTS content TEXT;

-- Deduplication fingerprint (e.g. SHA-256 of canonical content)
ALTER TABLE sources ADD COLUMN IF NOT EXISTS fingerprint TEXT;

-- Source reliability score: varies by type
-- document=0.8, code=0.8, web=0.6, conversation=0.5, observation=0.4,
-- tool_output=0.7, user_input=0.75
ALTER TABLE sources ADD COLUMN IF NOT EXISTS reliability NUMERIC(3,2) NOT NULL DEFAULT 0.5;

-- Vector embedding for semantic search (384-dim)
ALTER TABLE sources ADD COLUMN IF NOT EXISTS embedding VECTOR(384);

-- Full-text search index over content
ALTER TABLE sources ADD COLUMN IF NOT EXISTS content_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', COALESCE(content, ''))) STORED;

COMMENT ON COLUMN sources.reliability IS
    'Initial reliability: document=0.8, code=0.8, web=0.6, conversation=0.5, observation=0.4, tool_output=0.7, user_input=0.75';

CREATE INDEX IF NOT EXISTS idx_sources_embedding
    ON sources USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200);
CREATE INDEX IF NOT EXISTS idx_sources_tsv ON sources USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS idx_sources_created ON sources(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_fingerprint ON sources(fingerprint) WHERE fingerprint IS NOT NULL;

-- ============================================================================
-- PHASE 4: CREATE ARTICLES (renamed from beliefs)
-- ============================================================================

-- Rename beliefs → articles, preserving all rows
ALTER TABLE beliefs RENAME TO articles;

-- Rename the primary key index
ALTER INDEX beliefs_pkey RENAME TO articles_pkey;

-- Rename secondary indexes to match new table name
ALTER INDEX IF EXISTS idx_beliefs_domain RENAME TO idx_articles_domain;
ALTER INDEX IF EXISTS idx_beliefs_status RENAME TO idx_articles_status;
ALTER INDEX IF EXISTS idx_beliefs_created RENAME TO idx_articles_created;
ALTER INDEX IF EXISTS idx_beliefs_tsv RENAME TO idx_articles_tsv;
ALTER INDEX IF EXISTS idx_beliefs_source RENAME TO idx_articles_source;
ALTER INDEX IF EXISTS idx_beliefs_embedding RENAME TO idx_articles_embedding;
ALTER INDEX IF EXISTS idx_beliefs_holder RENAME TO idx_articles_holder;
ALTER INDEX IF EXISTS idx_beliefs_content_hash RENAME TO idx_articles_content_hash;
ALTER INDEX IF EXISTS idx_beliefs_archival_candidates RENAME TO idx_articles_archival_candidates;
ALTER INDEX IF EXISTS idx_beliefs_archived RENAME TO idx_articles_archived;

-- Add article-specific columns
ALTER TABLE articles ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS author_type TEXT NOT NULL DEFAULT 'system'
    CHECK (author_type IN ('system', 'operator', 'agent'));
ALTER TABLE articles ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS size_tokens INTEGER;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS compiled_at TIMESTAMPTZ;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS usage_score NUMERIC(8,4) NOT NULL DEFAULT 0;

-- Drop federation-specific columns from articles
ALTER TABLE articles DROP COLUMN IF EXISTS opt_out_federation;
ALTER TABLE articles DROP COLUMN IF EXISTS share_policy;
ALTER TABLE articles DROP COLUMN IF EXISTS visibility;
ALTER TABLE articles DROP COLUMN IF EXISTS is_local;
ALTER TABLE articles DROP COLUMN IF EXISTS origin_node_id;

-- ============================================================================
-- PHASE 5: RENAME belief_entities → article_entities
-- ============================================================================

ALTER TABLE belief_entities RENAME TO article_entities;

ALTER INDEX IF EXISTS idx_belief_entities_entity RENAME TO idx_article_entities_entity;

-- ============================================================================
-- PHASE 6: ARTICLE PROVENANCE TABLES
-- ============================================================================

-- article_sources: tracks which sources contributed to each article
CREATE TABLE IF NOT EXISTS article_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL
        CHECK (relationship IN ('originates', 'confirms', 'supersedes', 'contradicts', 'contends')),
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT,
    UNIQUE(article_id, source_id, relationship)
);

CREATE INDEX IF NOT EXISTS idx_article_sources_article ON article_sources(article_id);
CREATE INDEX IF NOT EXISTS idx_article_sources_source ON article_sources(source_id);
CREATE INDEX IF NOT EXISTS idx_article_sources_rel ON article_sources(relationship);

-- article_mutations: history of splits, merges, and updates
CREATE TABLE IF NOT EXISTS article_mutations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mutation_type TEXT NOT NULL
        CHECK (mutation_type IN ('created', 'updated', 'split', 'merged', 'archived')),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    related_article_id UUID REFERENCES articles(id) ON DELETE SET NULL,
    trigger_source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_article_mutations_article ON article_mutations(article_id);
CREATE INDEX IF NOT EXISTS idx_article_mutations_type ON article_mutations(mutation_type);

-- ============================================================================
-- PHASE 7: CONTENTIONS (renamed from tensions)
-- ============================================================================

ALTER TABLE tensions RENAME TO contentions;

ALTER INDEX IF EXISTS idx_tensions_status RENAME TO idx_contentions_status;
ALTER INDEX IF EXISTS idx_tensions_severity RENAME TO idx_contentions_severity;
ALTER INDEX IF EXISTS idx_tensions_belief_a RENAME TO idx_contentions_belief_a;
ALTER INDEX IF EXISTS idx_tensions_belief_b RENAME TO idx_contentions_belief_b;

-- Add materiality score (importance of the contention)
ALTER TABLE contentions ADD COLUMN IF NOT EXISTS materiality NUMERIC(3,2) DEFAULT 0.5;

-- ============================================================================
-- PHASE 8: USAGE TRACES (renamed from belief_retrievals)
-- ============================================================================

ALTER TABLE belief_retrievals RENAME TO usage_traces;

ALTER INDEX IF EXISTS idx_belief_retrievals_belief RENAME TO idx_usage_traces_belief;
ALTER INDEX IF EXISTS idx_belief_retrievals_time RENAME TO idx_usage_traces_time;

-- Add source context to usage traces
ALTER TABLE usage_traces ADD COLUMN IF NOT EXISTS source_id UUID REFERENCES sources(id) ON DELETE SET NULL;

-- Alias view for cleaner article-centric querying
-- (belief_id column kept for backward compat; conceptually it's article_id)
CREATE OR REPLACE VIEW article_usage AS
SELECT
    belief_id AS article_id,
    query_text,
    tool_name,
    retrieved_at,
    final_score,
    session_id
FROM usage_traces
WHERE belief_id IS NOT NULL;

-- ============================================================================
-- PHASE 9: MUTATION QUEUE (deferred follow-ups per DR-6)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mutation_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation TEXT NOT NULL
        CHECK (operation IN ('split', 'merge_candidate', 'recompile', 'decay_check')),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 5,
    payload JSONB DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_mutation_queue_status ON mutation_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_mutation_queue_article ON mutation_queue(article_id);

-- ============================================================================
-- PHASE 10: UPDATED VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW articles_current AS
SELECT * FROM articles
WHERE status = 'active'
  AND superseded_by_id IS NULL;

CREATE OR REPLACE VIEW articles_with_sources AS
SELECT
    a.*,
    COUNT(DISTINCT asrc.source_id) AS source_count,
    array_agg(DISTINCT asrc.relationship) FILTER (WHERE asrc.relationship IS NOT NULL) AS relationship_types,
    bool_or(asrc.relationship = 'contradicts' OR asrc.relationship = 'contends') AS has_contention
FROM articles a
LEFT JOIN article_sources asrc ON a.id = asrc.article_id
WHERE a.status = 'active'
GROUP BY a.id;

-- ============================================================================
-- PHASE 11: SYSTEM CONFIG (bounded memory parameters)
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO system_config (key, value) VALUES
    ('bounded_memory',     '{"max_articles": 10000, "max_sources": 100000}'),
    ('right_sizing',       '{"max_tokens": 4000, "min_tokens": 200, "target_tokens": 2000}'),
    ('reliability_defaults', '{"document": 0.8, "code": 0.8, "web": 0.6, "conversation": 0.5, "observation": 0.4, "tool_output": 0.7, "user_input": 0.75}'),
    ('freshness',          '{"decay_rate": 0.01, "staleness_days": 90}'),
    ('contention',         '{"materiality_threshold": 0.3}')
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- PHASE 12: DATA BACKFILL — migrate source_id into article_sources
-- ============================================================================

-- For every article that has a source_id set, create an article_sources
-- row with relationship='originates'.  The source_id column stays on articles
-- for now (backward compat); it can be dropped in a future migration.
INSERT INTO article_sources (article_id, source_id, relationship)
SELECT id, source_id, 'originates'
FROM articles
WHERE source_id IS NOT NULL
ON CONFLICT (article_id, source_id, relationship) DO NOTHING;

COMMIT;
