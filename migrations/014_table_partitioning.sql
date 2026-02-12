-- Migration 014: Table partitioning for high-volume tables (#357)
-- Converts audit_log, belief_retrievals, sync_events
-- to RANGE partitions by timestamp (monthly).
--
-- Safe to run on fresh databases (handles missing tables).
-- Post-migration: Run create_monthly_partitions() to extend future partitions.

-- ============================================================================
-- HELPER: Create monthly partitions for a table
-- ============================================================================
CREATE OR REPLACE FUNCTION create_monthly_partitions(
    p_table_name TEXT,
    p_months_ahead INTEGER DEFAULT 3,
    p_months_behind INTEGER DEFAULT 1,
    p_partition_column TEXT DEFAULT NULL
)
RETURNS TABLE (
    partition_name TEXT,
    range_start DATE,
    range_end DATE,
    created BOOLEAN
) AS $$
DECLARE
    v_start DATE;
    v_end DATE;
    v_partition TEXT;
    v_exists BOOLEAN;
BEGIN
    FOR i IN (-p_months_behind)..p_months_ahead LOOP
        v_start := date_trunc('month', CURRENT_DATE + (i || ' months')::INTERVAL)::DATE;
        v_end := (v_start + INTERVAL '1 month')::DATE;
        v_partition := p_table_name || '_' || to_char(v_start, 'YYYY_MM');

        SELECT EXISTS(
            SELECT 1 FROM pg_class WHERE relname = v_partition
        ) INTO v_exists;

        IF NOT v_exists THEN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
                v_partition, p_table_name, v_start, v_end
            );
            partition_name := v_partition;
            range_start := v_start;
            range_end := v_end;
            created := TRUE;
            RETURN NEXT;
        ELSE
            partition_name := v_partition;
            range_start := v_start;
            range_end := v_end;
            created := FALSE;
            RETURN NEXT;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- AUDIT_LOG: Create partitioned table
-- ============================================================================
DO $$
BEGIN
    -- Drop old non-partitioned table if it exists (and is NOT a view)
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'audit_log' AND relkind = 'r') THEN
        -- It's a regular table - rename, migrate data, drop
        ALTER TABLE audit_log RENAME TO audit_log_old;
        DROP INDEX IF EXISTS idx_audit_log_time;
        DROP INDEX IF EXISTS idx_audit_log_action;
        DROP INDEX IF EXISTS idx_audit_log_actor;
        DROP INDEX IF EXISTS idx_audit_log_resource;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS audit_log_partitioned (
    id UUID DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_did TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    details JSONB DEFAULT '{}',
    ip_address TEXT,
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

CREATE INDEX IF NOT EXISTS idx_audit_log_p_time ON audit_log_partitioned(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_p_action ON audit_log_partitioned(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_p_actor ON audit_log_partitioned(actor_did) WHERE actor_did IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_log_p_resource ON audit_log_partitioned(resource_type, resource_id);

SELECT * FROM create_monthly_partitions('audit_log_partitioned', 3, 1, 'timestamp');
CREATE TABLE IF NOT EXISTS audit_log_partitioned_default PARTITION OF audit_log_partitioned DEFAULT;

-- Migrate data if old table exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'audit_log_old') THEN
        INSERT INTO audit_log_partitioned SELECT * FROM audit_log_old;
        DROP TABLE audit_log_old;
    END IF;
END $$;

-- Backward-compatible view (simple updatable view - inserts pass through with defaults)
DROP VIEW IF EXISTS audit_log CASCADE;
CREATE OR REPLACE VIEW audit_log AS SELECT * FROM audit_log_partitioned;

-- ============================================================================
-- BELIEF_RETRIEVALS: Create partitioned table
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'belief_retrievals' AND relkind = 'r') THEN
        ALTER TABLE belief_retrievals RENAME TO belief_retrievals_old;
        DROP INDEX IF EXISTS idx_belief_retrievals_belief;
        DROP INDEX IF EXISTS idx_belief_retrievals_time;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS belief_retrievals_partitioned (
    id UUID DEFAULT gen_random_uuid(),
    belief_id UUID NOT NULL,
    query_text TEXT,
    tool_name TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    final_score NUMERIC,
    session_id UUID,
    PRIMARY KEY (id, retrieved_at)
) PARTITION BY RANGE (retrieved_at);

CREATE INDEX IF NOT EXISTS idx_belief_retrievals_p_belief ON belief_retrievals_partitioned(belief_id);
CREATE INDEX IF NOT EXISTS idx_belief_retrievals_p_time ON belief_retrievals_partitioned(retrieved_at DESC);

SELECT * FROM create_monthly_partitions('belief_retrievals_partitioned', 3, 1, 'retrieved_at');
CREATE TABLE IF NOT EXISTS belief_retrievals_partitioned_default PARTITION OF belief_retrievals_partitioned DEFAULT;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'belief_retrievals_old') THEN
        INSERT INTO belief_retrievals_partitioned SELECT * FROM belief_retrievals_old;
        DROP TABLE belief_retrievals_old;
    END IF;
END $$;

DROP VIEW IF EXISTS belief_retrievals CASCADE;
CREATE OR REPLACE VIEW belief_retrievals AS SELECT * FROM belief_retrievals_partitioned;

-- ============================================================================
-- SYNC_EVENTS: Create partitioned table
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'sync_events' AND relkind = 'r') THEN
        ALTER TABLE sync_events RENAME TO sync_events_old;
        DROP INDEX IF EXISTS idx_sync_events_node;
        DROP INDEX IF EXISTS idx_sync_events_time;
        DROP INDEX IF EXISTS idx_sync_events_type;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS sync_events_partitioned (
    id UUID DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    direction TEXT NOT NULL DEFAULT 'inbound',
    belief_id UUID,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, synced_at),
    CONSTRAINT sync_events_p_valid_direction CHECK (direction IN ('inbound', 'outbound'))
) PARTITION BY RANGE (synced_at);

CREATE INDEX IF NOT EXISTS idx_sync_events_p_node ON sync_events_partitioned(node_id);
CREATE INDEX IF NOT EXISTS idx_sync_events_p_time ON sync_events_partitioned(synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_events_p_type ON sync_events_partitioned(event_type);

SELECT * FROM create_monthly_partitions('sync_events_partitioned', 3, 1, 'synced_at');
CREATE TABLE IF NOT EXISTS sync_events_partitioned_default PARTITION OF sync_events_partitioned DEFAULT;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'sync_events_old') THEN
        INSERT INTO sync_events_partitioned SELECT * FROM sync_events_old;
        DROP TABLE sync_events_old;
    END IF;
END $$;

DROP VIEW IF EXISTS sync_events CASCADE;
CREATE OR REPLACE VIEW sync_events AS SELECT * FROM sync_events_partitioned;
