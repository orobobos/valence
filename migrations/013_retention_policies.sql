-- Migration 013: Retention policies and tombstones table (#358)
-- Adds tombstones table for GDPR-compliant deletions and
-- retention policy enforcement functions.

-- Tombstones: track what was deleted and why (GDPR requires this)
CREATE TABLE IF NOT EXISTS tombstones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_type TEXT NOT NULL,
    content_id UUID NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason TEXT NOT NULL DEFAULT 'retention_policy',
    -- reason values: retention_policy, user_request, gdpr_erasure, admin_action
    metadata JSONB DEFAULT '{}',
    -- metadata can include: original_created_at, domain_path, content_hash
    retention_until TIMESTAMPTZ,
    -- tombstone itself has retention (7 years for GDPR audit trail)

    CONSTRAINT tombstones_valid_reason CHECK (
        reason IN ('retention_policy', 'user_request', 'gdpr_erasure', 'admin_action')
    )
);

CREATE INDEX IF NOT EXISTS idx_tombstones_content ON tombstones(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_tombstones_deleted ON tombstones(deleted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tombstones_retention ON tombstones(retention_until)
    WHERE retention_until IS NOT NULL;

-- Apply retention policies: delete old data from specified tables
-- audit_log is NEVER deleted (7-year GDPR minimum)
CREATE OR REPLACE FUNCTION apply_retention_policies(
    p_belief_retrievals_days INTEGER DEFAULT 90,
    p_sync_events_days INTEGER DEFAULT 90,
    p_embedding_coverage_days INTEGER DEFAULT NULL,  -- NULL = keep forever
    p_dry_run BOOLEAN DEFAULT FALSE
)
RETURNS TABLE (
    table_name TEXT,
    deleted_count BIGINT
) AS $$
DECLARE
    v_count BIGINT;
    v_threshold TIMESTAMPTZ;
BEGIN
    -- belief_retrievals: query tracking
    v_threshold := NOW() - (p_belief_retrievals_days || ' days')::INTERVAL;
    IF p_dry_run THEN
        SELECT COUNT(*) INTO v_count FROM belief_retrievals WHERE retrieved_at < v_threshold;
    ELSE
        WITH deleted AS (
            DELETE FROM belief_retrievals WHERE retrieved_at < v_threshold RETURNING 1
        ) SELECT COUNT(*) INTO v_count FROM deleted;
    END IF;
    table_name := 'belief_retrievals'; deleted_count := v_count;
    RETURN NEXT;

    -- sync_events: federation sync history
    v_threshold := NOW() - (p_sync_events_days || ' days')::INTERVAL;
    IF p_dry_run THEN
        SELECT COUNT(*) INTO v_count FROM sync_events WHERE synced_at < v_threshold;
    ELSE
        -- Record tombstones before deleting
        INSERT INTO tombstones (content_type, content_id, reason, metadata)
        SELECT 'sync_event', id, 'retention_policy',
               jsonb_build_object('synced_at', synced_at, 'event_type', event_type)
        FROM sync_events WHERE synced_at < v_threshold;

        WITH deleted AS (
            DELETE FROM sync_events WHERE synced_at < v_threshold RETURNING 1
        ) SELECT COUNT(*) INTO v_count FROM deleted;
    END IF;
    table_name := 'sync_events'; deleted_count := v_count;
    RETURN NEXT;

    -- embedding_coverage: optional cleanup
    IF p_embedding_coverage_days IS NOT NULL THEN
        v_threshold := NOW() - (p_embedding_coverage_days || ' days')::INTERVAL;
        IF p_dry_run THEN
            SELECT COUNT(*) INTO v_count FROM embedding_coverage WHERE embedded_at < v_threshold;
        ELSE
            WITH deleted AS (
                DELETE FROM embedding_coverage WHERE embedded_at < v_threshold RETURNING 1
            ) SELECT COUNT(*) INTO v_count FROM deleted;
        END IF;
        table_name := 'embedding_coverage'; deleted_count := v_count;
        RETURN NEXT;
    END IF;

    -- NOTE: audit_log is NEVER deleted (GDPR 7-year retention requirement)
    -- NOTE: consent_chains are NEVER deleted (legal audit trail)
    table_name := 'audit_log'; deleted_count := 0;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Clean up expired tombstones (tombstones themselves have retention)
CREATE OR REPLACE FUNCTION cleanup_expired_tombstones(
    p_dry_run BOOLEAN DEFAULT FALSE
)
RETURNS BIGINT AS $$
DECLARE
    v_count BIGINT;
BEGIN
    IF p_dry_run THEN
        SELECT COUNT(*) INTO v_count
        FROM tombstones
        WHERE retention_until IS NOT NULL AND retention_until < NOW();
    ELSE
        WITH deleted AS (
            DELETE FROM tombstones
            WHERE retention_until IS NOT NULL AND retention_until < NOW()
            RETURNING 1
        ) SELECT COUNT(*) INTO v_count FROM deleted;
    END IF;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;
