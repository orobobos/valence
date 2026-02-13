-- Migration 020: Schema convergence
-- Closes remaining gaps between schema.sql and the live database.
-- Adds: trust_edges, peer_nodes, shares tables
-- Adds: opt_out_federation, share_policy, extraction_metadata columns
-- Updates: consent_chains to cryptographic chain model

-- ============================================================================
-- 1. Add missing columns to existing tables
-- ============================================================================

-- beliefs
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- federation_nodes
ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS opt_out_federation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS share_policy JSONB;
ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- tensions
ALTER TABLE tensions ADD COLUMN IF NOT EXISTS opt_out_federation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tensions ADD COLUMN IF NOT EXISTS share_policy JSONB;
ALTER TABLE tensions ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- tension_resolutions
ALTER TABLE tension_resolutions ADD COLUMN IF NOT EXISTS opt_out_federation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tension_resolutions ADD COLUMN IF NOT EXISTS share_policy JSONB;
ALTER TABLE tension_resolutions ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- sync_outbound_queue
ALTER TABLE sync_outbound_queue ADD COLUMN IF NOT EXISTS opt_out_federation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE sync_outbound_queue ADD COLUMN IF NOT EXISTS share_policy JSONB;
ALTER TABLE sync_outbound_queue ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- vkb_patterns
ALTER TABLE vkb_patterns ADD COLUMN IF NOT EXISTS opt_out_federation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE vkb_patterns ADD COLUMN IF NOT EXISTS share_policy JSONB;
ALTER TABLE vkb_patterns ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- vkb_sessions
ALTER TABLE vkb_sessions ADD COLUMN IF NOT EXISTS opt_out_federation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE vkb_sessions ADD COLUMN IF NOT EXISTS share_policy JSONB;
ALTER TABLE vkb_sessions ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- ============================================================================
-- 2. Update consent_chains to cryptographic chain model
-- ============================================================================

-- Add new columns (keep old columns for data preservation)
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS origin_sharer TEXT;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS origin_timestamp TIMESTAMPTZ;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS origin_policy JSONB;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS origin_signature BYTEA;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS chain_hash BYTEA;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS hops JSONB NOT NULL DEFAULT '[]';
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS revoked_by TEXT;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS revocation_reason TEXT;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Add new indexes
CREATE INDEX IF NOT EXISTS idx_consent_chains_sharer ON consent_chains(origin_sharer);
CREATE INDEX IF NOT EXISTS idx_consent_chains_created ON consent_chains(created_at DESC);

-- ============================================================================
-- 3. Create peer_nodes table
-- ============================================================================

CREATE TABLE IF NOT EXISTS peer_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL UNIQUE,
    endpoint TEXT NOT NULL,
    trust_level NUMERIC(3,2) NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'discovered',
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT peer_nodes_valid_trust CHECK (trust_level >= 0 AND trust_level <= 1),
    CONSTRAINT peer_nodes_valid_status CHECK (
        status IN ('discovered', 'active', 'suspended', 'unreachable')
    )
);

CREATE INDEX IF NOT EXISTS idx_peer_nodes_node_id ON peer_nodes(node_id);
CREATE INDEX IF NOT EXISTS idx_peer_nodes_status ON peer_nodes(status);
CREATE INDEX IF NOT EXISTS idx_peer_nodes_trust ON peer_nodes(trust_level DESC);
CREATE INDEX IF NOT EXISTS idx_peer_nodes_last_seen ON peer_nodes(last_seen DESC);

-- ============================================================================
-- 4. Create trust_edges table
-- ============================================================================

CREATE TABLE IF NOT EXISTS trust_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_did TEXT NOT NULL,
    target_did TEXT NOT NULL,
    competence NUMERIC(3,2) NOT NULL DEFAULT 0.5,
    integrity NUMERIC(3,2) NOT NULL DEFAULT 0.5,
    confidentiality NUMERIC(3,2) NOT NULL DEFAULT 0.5,
    judgment NUMERIC(3,2) NOT NULL DEFAULT 0.1,
    domain TEXT,
    can_delegate BOOLEAN NOT NULL DEFAULT FALSE,
    delegation_depth INTEGER NOT NULL DEFAULT 0,
    decay_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    decay_model TEXT NOT NULL DEFAULT 'exponential',
    last_refreshed TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    CONSTRAINT trust_edges_valid_competence CHECK (competence >= 0 AND competence <= 1),
    CONSTRAINT trust_edges_valid_integrity CHECK (integrity >= 0 AND integrity <= 1),
    CONSTRAINT trust_edges_valid_confidentiality CHECK (confidentiality >= 0 AND confidentiality <= 1),
    CONSTRAINT trust_edges_valid_judgment CHECK (judgment >= 0 AND judgment <= 1),
    CONSTRAINT trust_edges_valid_decay_rate CHECK (decay_rate >= 0 AND decay_rate <= 1),
    CONSTRAINT trust_edges_valid_decay_model CHECK (
        decay_model IN ('none', 'linear', 'exponential')
    ),
    CONSTRAINT trust_edges_valid_delegation_depth CHECK (delegation_depth >= 0),
    CONSTRAINT trust_edges_no_self_trust CHECK (source_did != target_did)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trust_edges_unique
    ON trust_edges(source_did, target_did, COALESCE(domain, ''));
CREATE INDEX IF NOT EXISTS idx_trust_edges_source ON trust_edges(source_did);
CREATE INDEX IF NOT EXISTS idx_trust_edges_target ON trust_edges(target_did);
CREATE INDEX IF NOT EXISTS idx_trust_edges_domain ON trust_edges(domain) WHERE domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trust_edges_expires ON trust_edges(expires_at)
    WHERE expires_at IS NOT NULL;

-- ============================================================================
-- 5. Create shares table
-- ============================================================================

CREATE TABLE IF NOT EXISTS shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    consent_chain_id UUID NOT NULL REFERENCES consent_chains(id) ON DELETE CASCADE,
    encrypted_envelope JSONB NOT NULL,
    recipient_did TEXT NOT NULL,
    accessed_at TIMESTAMPTZ,
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shares_consent_chain ON shares(consent_chain_id);
CREATE INDEX IF NOT EXISTS idx_shares_recipient ON shares(recipient_did);
CREATE INDEX IF NOT EXISTS idx_shares_created ON shares(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shares_unique_recipient
    ON shares(consent_chain_id, recipient_did);

-- ============================================================================
-- 6. Create views
-- ============================================================================

CREATE OR REPLACE VIEW shares_with_consent AS
SELECT
    s.*,
    cc.belief_id,
    cc.origin_sharer,
    cc.origin_timestamp,
    cc.origin_policy,
    cc.revoked as consent_revoked
FROM shares s
JOIN consent_chains cc ON s.consent_chain_id = cc.id;

CREATE OR REPLACE VIEW active_shares AS
SELECT * FROM shares_with_consent
WHERE NOT consent_revoked;

-- ============================================================================
-- 7. Add legacy columns for data compatibility
-- ============================================================================

-- These columns exist in established databases and are needed for data-only
-- restores. They are superseded by JSONB confidence and dedicated corroboration
-- tables, but kept for backward compatibility.

ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS corroboration_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS corroborating_sources JSONB NOT NULL DEFAULT '[]';
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS is_local BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS origin_node_id UUID;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS confidence_source REAL DEFAULT 0.5;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS confidence_method REAL DEFAULT 0.5;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS confidence_consistency REAL DEFAULT 1.0;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS confidence_freshness REAL DEFAULT 1.0;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS confidence_corroboration REAL DEFAULT 0.1;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS confidence_applicability REAL DEFAULT 0.8;

-- Legacy consent_chains columns
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS granted_by TEXT;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS granted_at TIMESTAMPTZ;
ALTER TABLE consent_chains ADD COLUMN IF NOT EXISTS reason TEXT;

-- ============================================================================
-- 8. Recreate views to pick up new columns
-- ============================================================================

-- PostgreSQL expands SELECT * at view creation time, so views must be
-- recreated after adding columns to their base tables.

DROP VIEW IF EXISTS beliefs_current CASCADE;
CREATE VIEW beliefs_current AS
SELECT * FROM beliefs WHERE status = 'active' AND superseded_by_id IS NULL;

DROP VIEW IF EXISTS beliefs_with_entities CASCADE;
CREATE VIEW beliefs_with_entities AS
SELECT b.*,
    array_agg(DISTINCT e.name) FILTER (WHERE be.role = 'subject') as subjects,
    array_agg(DISTINCT e.name) FILTER (WHERE be.role = 'object') as objects,
    array_agg(DISTINCT e.name) FILTER (WHERE be.role = 'context') as contexts
FROM beliefs b
LEFT JOIN belief_entities be ON b.id = be.belief_id
LEFT JOIN entities e ON be.entity_id = e.id
GROUP BY b.id;

DROP VIEW IF EXISTS vkb_patterns_overview CASCADE;
CREATE VIEW vkb_patterns_overview AS
SELECT p.*, array_length(p.evidence, 1) as evidence_count FROM vkb_patterns p;

DROP VIEW IF EXISTS vkb_sessions_overview CASCADE;
CREATE VIEW vkb_sessions_overview AS
SELECT s.*, COUNT(DISTINCT e.id) as exchange_count, COUNT(DISTINCT si.id) as insight_count
FROM vkb_sessions s
LEFT JOIN vkb_exchanges e ON s.id = e.session_id
LEFT JOIN vkb_session_insights si ON s.id = si.session_id
GROUP BY s.id;

DROP VIEW IF EXISTS federation_nodes_with_trust CASCADE;
CREATE VIEW federation_nodes_with_trust AS
SELECT fn.*,
    nt.trust,
    (nt.trust->>'overall')::numeric AS trust_overall,
    nt.beliefs_received,
    nt.beliefs_corroborated,
    unt.trust_preference AS user_preference
FROM federation_nodes fn
LEFT JOIN node_trust nt ON fn.id = nt.node_id
LEFT JOIN user_node_trust unt ON fn.id = unt.node_id;

-- Recreate materialized views
DROP MATERIALIZED VIEW IF EXISTS federation_nodes_with_trust_mat CASCADE;
CREATE MATERIALIZED VIEW federation_nodes_with_trust_mat AS
SELECT * FROM federation_nodes_with_trust;
CREATE UNIQUE INDEX IF NOT EXISTS idx_fed_nodes_trust_mat_id ON federation_nodes_with_trust_mat(id);
CREATE INDEX IF NOT EXISTS idx_fed_nodes_trust_mat_status ON federation_nodes_with_trust_mat(status);

-- ============================================================================
-- 9. Refresh remaining materialized views
-- ============================================================================

DO $$
BEGIN
    BEGIN
        REFRESH MATERIALIZED VIEW CONCURRENTLY beliefs_current_mat;
    EXCEPTION WHEN OTHERS THEN
        BEGIN
            REFRESH MATERIALIZED VIEW beliefs_current_mat;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END;
END $$;
