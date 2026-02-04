-- ============================================================================
-- Migration 007: Federation Tables
-- ============================================================================
-- Implements peer-to-peer federation for distributed Valence networks.
-- Allows beliefs to be shared and synchronized across trusted peer nodes.
--
-- Tables:
--   - federation_nodes: Known peer nodes in the federation network
--   - sync_state: Tracks sync progress with each peer
--
-- Adds to beliefs:
--   - is_local: Whether belief originated locally
--   - origin_node_id: Source node for federated beliefs
-- ============================================================================

-- ============================================================================
-- PHASE 1: ENUM TYPES
-- ============================================================================

-- Federation node status
DO $$ BEGIN
    CREATE TYPE federation_node_status AS ENUM (
        'pending',    -- Awaiting approval
        'active',     -- Approved and operational
        'suspended',  -- Temporarily disabled
        'revoked'     -- Permanently removed
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Sync state status
DO $$ BEGIN
    CREATE TYPE sync_status AS ENUM (
        'idle',       -- No sync in progress
        'syncing',    -- Sync currently active
        'error'       -- Last sync failed
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- PHASE 2: FEDERATION_NODES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS federation_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Identity
    did TEXT UNIQUE NOT NULL,              -- Decentralized Identifier
    name TEXT,                              -- Human-readable name
    endpoint TEXT NOT NULL,                 -- API endpoint URL
    public_key TEXT,                        -- Node's public key for verification
    
    -- Status and trust
    status federation_node_status NOT NULL DEFAULT 'pending',
    capabilities TEXT[] DEFAULT '{}',       -- Supported protocol features
    trust_score REAL NOT NULL DEFAULT 0.5   -- 0.0-1.0, adjusts based on behavior
        CHECK (trust_score >= 0.0 AND trust_score <= 1.0),
    
    -- Tracking
    last_seen TIMESTAMPTZ,                  -- Last successful communication
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for federation_nodes
CREATE INDEX IF NOT EXISTS idx_federation_nodes_did 
    ON federation_nodes(did);
CREATE INDEX IF NOT EXISTS idx_federation_nodes_status 
    ON federation_nodes(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_federation_nodes_trust 
    ON federation_nodes(trust_score DESC) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_federation_nodes_last_seen 
    ON federation_nodes(last_seen DESC NULLS LAST);

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_federation_nodes_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_federation_nodes_updated_at ON federation_nodes;
CREATE TRIGGER trg_federation_nodes_updated_at
    BEFORE UPDATE ON federation_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_federation_nodes_updated_at();

-- ============================================================================
-- PHASE 3: SYNC_STATE TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Reference to peer node
    node_id UUID NOT NULL REFERENCES federation_nodes(id) ON DELETE CASCADE,
    
    -- Cursor tracking for incremental sync
    last_received_cursor TEXT,              -- Last cursor received from peer
    last_sent_cursor TEXT,                  -- Last cursor sent to peer
    
    -- Vector clock for conflict detection
    vector_clock JSONB NOT NULL DEFAULT '{}',
    
    -- Status
    status sync_status NOT NULL DEFAULT 'idle',
    
    -- Statistics
    beliefs_sent INTEGER NOT NULL DEFAULT 0,
    beliefs_received INTEGER NOT NULL DEFAULT 0,
    last_sync_duration_ms INTEGER,
    
    -- Error tracking
    last_error TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    
    -- Scheduling
    last_sync_at TIMESTAMPTZ,
    next_sync_scheduled TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Each node has exactly one sync state record
    CONSTRAINT sync_state_node_unique UNIQUE (node_id)
);

-- Indexes for sync_state
CREATE INDEX IF NOT EXISTS idx_sync_state_node 
    ON sync_state(node_id);
CREATE INDEX IF NOT EXISTS idx_sync_state_status 
    ON sync_state(status);
CREATE INDEX IF NOT EXISTS idx_sync_state_next_sync 
    ON sync_state(next_sync_scheduled ASC NULLS LAST) 
    WHERE status != 'error';
CREATE INDEX IF NOT EXISTS idx_sync_state_errors 
    ON sync_state(error_count DESC) 
    WHERE error_count > 0;

-- Trigger to update modified_at
CREATE OR REPLACE FUNCTION update_sync_state_modified_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modified_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_state_modified_at ON sync_state;
CREATE TRIGGER trg_sync_state_modified_at
    BEFORE UPDATE ON sync_state
    FOR EACH ROW
    EXECUTE FUNCTION update_sync_state_modified_at();

-- ============================================================================
-- PHASE 4: ADD FEDERATION COLUMNS TO BELIEFS
-- ============================================================================

-- Flag for locally-originated beliefs
ALTER TABLE beliefs 
    ADD COLUMN IF NOT EXISTS is_local BOOLEAN NOT NULL DEFAULT TRUE;

-- Reference to origin node for federated beliefs
ALTER TABLE beliefs 
    ADD COLUMN IF NOT EXISTS origin_node_id UUID REFERENCES federation_nodes(id) ON DELETE SET NULL;

-- Index for finding federated beliefs
CREATE INDEX IF NOT EXISTS idx_beliefs_is_local 
    ON beliefs(is_local) WHERE is_local = FALSE;
CREATE INDEX IF NOT EXISTS idx_beliefs_origin_node 
    ON beliefs(origin_node_id) WHERE origin_node_id IS NOT NULL;

-- ============================================================================
-- PHASE 5: HELPER FUNCTIONS
-- ============================================================================

-- Get active federation nodes for sync
CREATE OR REPLACE FUNCTION get_active_federation_nodes()
RETURNS TABLE (
    id UUID,
    did TEXT,
    name TEXT,
    endpoint TEXT,
    trust_score REAL,
    last_seen TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        fn.id,
        fn.did,
        fn.name,
        fn.endpoint,
        fn.trust_score,
        fn.last_seen
    FROM federation_nodes fn
    WHERE fn.status = 'active'
    ORDER BY fn.trust_score DESC;
END;
$$ LANGUAGE plpgsql STABLE;

-- Get nodes due for sync
CREATE OR REPLACE FUNCTION get_nodes_due_for_sync()
RETURNS TABLE (
    node_id UUID,
    did TEXT,
    endpoint TEXT,
    last_sync_at TIMESTAMPTZ,
    next_sync_scheduled TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        fn.id,
        fn.did,
        fn.endpoint,
        ss.last_sync_at,
        ss.next_sync_scheduled
    FROM federation_nodes fn
    JOIN sync_state ss ON ss.node_id = fn.id
    WHERE fn.status = 'active'
      AND ss.status != 'syncing'
      AND (ss.next_sync_scheduled IS NULL OR ss.next_sync_scheduled <= NOW())
    ORDER BY ss.next_sync_scheduled ASC NULLS FIRST;
END;
$$ LANGUAGE plpgsql STABLE;

-- Record sync start
CREATE OR REPLACE FUNCTION sync_start(p_node_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE sync_state
    SET status = 'syncing',
        modified_at = NOW()
    WHERE node_id = p_node_id;
    
    -- Create sync_state if doesn't exist
    INSERT INTO sync_state (node_id, status)
    VALUES (p_node_id, 'syncing')
    ON CONFLICT (node_id) DO UPDATE
    SET status = 'syncing', modified_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Record sync completion
CREATE OR REPLACE FUNCTION sync_complete(
    p_node_id UUID,
    p_sent INTEGER,
    p_received INTEGER,
    p_duration_ms INTEGER,
    p_sent_cursor TEXT,
    p_received_cursor TEXT,
    p_next_sync TIMESTAMPTZ DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE sync_state
    SET status = 'idle',
        beliefs_sent = beliefs_sent + p_sent,
        beliefs_received = beliefs_received + p_received,
        last_sync_duration_ms = p_duration_ms,
        last_sent_cursor = COALESCE(p_sent_cursor, last_sent_cursor),
        last_received_cursor = COALESCE(p_received_cursor, last_received_cursor),
        last_sync_at = NOW(),
        next_sync_scheduled = p_next_sync,
        last_error = NULL,
        error_count = 0,
        modified_at = NOW()
    WHERE node_id = p_node_id;
    
    -- Update node last_seen
    UPDATE federation_nodes
    SET last_seen = NOW()
    WHERE id = p_node_id;
END;
$$ LANGUAGE plpgsql;

-- Record sync error
CREATE OR REPLACE FUNCTION sync_error(
    p_node_id UUID,
    p_error TEXT,
    p_retry_at TIMESTAMPTZ DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE sync_state
    SET status = 'error',
        last_error = p_error,
        error_count = error_count + 1,
        next_sync_scheduled = COALESCE(p_retry_at, NOW() + INTERVAL '5 minutes' * POWER(2, LEAST(error_count, 6))),
        modified_at = NOW()
    WHERE node_id = p_node_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PHASE 6: COMMENTS
-- ============================================================================

COMMENT ON TABLE federation_nodes IS 'Known peer nodes in the federation network';
COMMENT ON COLUMN federation_nodes.did IS 'Decentralized Identifier (DID) for the node';
COMMENT ON COLUMN federation_nodes.trust_score IS 'Dynamic trust score based on node behavior (0.0-1.0)';
COMMENT ON COLUMN federation_nodes.capabilities IS 'Protocol features supported by this node';

COMMENT ON TABLE sync_state IS 'Tracks synchronization state with each federation peer';
COMMENT ON COLUMN sync_state.vector_clock IS 'Lamport vector clock for causal ordering';
COMMENT ON COLUMN sync_state.last_received_cursor IS 'Cursor for incremental pull from peer';
COMMENT ON COLUMN sync_state.last_sent_cursor IS 'Cursor for incremental push to peer';

COMMENT ON COLUMN beliefs.is_local IS 'TRUE if belief originated locally, FALSE if received via federation';
COMMENT ON COLUMN beliefs.origin_node_id IS 'Source federation node for beliefs received via sync';
