-- Migration 015: Materialized views for expensive queries (#362)
-- Materialize frequently-accessed views that involve joins/aggregations.
-- Unique indexes enable REFRESH CONCURRENTLY (no read lock during refresh).

-- ============================================================================
-- beliefs_current_mat: Active non-superseded beliefs
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS beliefs_current_mat AS
SELECT * FROM beliefs
WHERE status = 'active'
  AND superseded_by_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_beliefs_current_mat_id ON beliefs_current_mat(id);
CREATE INDEX IF NOT EXISTS idx_beliefs_current_mat_domain ON beliefs_current_mat USING GIN(domain_path);
CREATE INDEX IF NOT EXISTS idx_beliefs_current_mat_created ON beliefs_current_mat(created_at DESC);

-- ============================================================================
-- federation_nodes_with_trust_mat: Nodes with trust scores
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS federation_nodes_with_trust_mat AS
SELECT
    fn.id,
    fn.did,
    fn.federation_endpoint,
    fn.status,
    fn.last_seen_at,
    fn.discovered_at,
    nt.trust,
    (nt.trust->>'overall')::NUMERIC AS trust_overall,
    nt.beliefs_received,
    nt.beliefs_corroborated,
    unt.trust_preference AS user_preference
FROM federation_nodes fn
LEFT JOIN node_trust nt ON fn.id = nt.node_id
LEFT JOIN user_node_trust unt ON fn.id = unt.node_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_fed_nodes_trust_mat_id ON federation_nodes_with_trust_mat(id);
CREATE INDEX IF NOT EXISTS idx_fed_nodes_trust_mat_status ON federation_nodes_with_trust_mat(status);
CREATE INDEX IF NOT EXISTS idx_fed_nodes_trust_mat_score ON federation_nodes_with_trust_mat(trust_overall DESC NULLS LAST);

-- ============================================================================
-- vkb_sessions_overview_mat: Sessions with exchange counts
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS vkb_sessions_overview_mat AS
SELECT
    s.id,
    s.platform,
    s.status,
    s.project_context,
    s.started_at,
    s.ended_at,
    s.summary,
    s.themes,
    COUNT(e.id) AS exchange_count,
    MAX(e.created_at) AS last_exchange_at
FROM vkb_sessions s
LEFT JOIN vkb_exchanges e ON s.id = e.session_id
GROUP BY s.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_vkb_sessions_mat_id ON vkb_sessions_overview_mat(id);
CREATE INDEX IF NOT EXISTS idx_vkb_sessions_mat_status ON vkb_sessions_overview_mat(status);
CREATE INDEX IF NOT EXISTS idx_vkb_sessions_mat_started ON vkb_sessions_overview_mat(started_at DESC);

-- ============================================================================
-- domain_statistics: Belief counts and confidence per domain
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS domain_statistics AS
SELECT
    unnest(domain_path) AS domain,
    COUNT(*) AS belief_count,
    AVG((confidence->>'overall')::NUMERIC) AS avg_confidence,
    MIN(created_at) AS earliest_belief,
    MAX(created_at) AS latest_belief,
    COUNT(CASE WHEN status = 'active' THEN 1 END) AS active_count,
    COUNT(CASE WHEN status = 'superseded' THEN 1 END) AS superseded_count,
    COUNT(CASE WHEN status = 'archived' THEN 1 END) AS archived_count
FROM beliefs
GROUP BY unnest(domain_path);

CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_stats_domain ON domain_statistics(domain);
CREATE INDEX IF NOT EXISTS idx_domain_stats_count ON domain_statistics(belief_count DESC);

-- ============================================================================
-- reputation_summary: Per-node reputation aggregation
-- (Only created if reputations table exists - requires verification schema)
-- ============================================================================
DO $body$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'reputations') THEN
        EXECUTE $sql$
            CREATE MATERIALIZED VIEW IF NOT EXISTS reputation_summary AS
            SELECT
                r.identity_id AS did,
                r.overall,
                r.by_domain,
                r.verification_count,
                r.discrepancy_finds,
                r.stake_at_risk,
                r.modified_at AS last_activity
            FROM reputations r
        $sql$;
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS idx_reputation_summary_did ON reputation_summary(did)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_reputation_summary_score ON reputation_summary(overall DESC)';
    END IF;
END $body$;

-- ============================================================================
-- Refresh function: refresh all materialized views concurrently
-- ============================================================================
CREATE OR REPLACE FUNCTION refresh_materialized_views(p_concurrent BOOLEAN DEFAULT TRUE)
RETURNS TABLE (
    view_name TEXT,
    refreshed BOOLEAN,
    error_msg TEXT
) AS $$
DECLARE
    v_views TEXT[] := ARRAY[
        'beliefs_current_mat',
        'federation_nodes_with_trust_mat',
        'vkb_sessions_overview_mat',
        'domain_statistics'
    ];
    v_view TEXT;
BEGIN
    -- Add reputation_summary if it exists
    IF EXISTS (SELECT 1 FROM pg_matviews WHERE matviewname = 'reputation_summary') THEN
        v_views := array_append(v_views, 'reputation_summary');
    END IF;

    FOREACH v_view IN ARRAY v_views LOOP
        BEGIN
            IF p_concurrent THEN
                EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %I', v_view);
            ELSE
                EXECUTE format('REFRESH MATERIALIZED VIEW %I', v_view);
            END IF;
            view_name := v_view;
            refreshed := TRUE;
            error_msg := NULL;
            RETURN NEXT;
        EXCEPTION WHEN OTHERS THEN
            view_name := v_view;
            refreshed := FALSE;
            error_msg := SQLERRM;
            RETURN NEXT;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
