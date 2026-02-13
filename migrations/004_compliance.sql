-- Migration 004: Compliance infrastructure
-- Phase 2.1: Consent records table
-- Phase 2.4: Audit log table

-- ============================================================================
-- 2.1: Consent Records
-- ============================================================================

CREATE TABLE IF NOT EXISTS consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    holder_did TEXT NOT NULL,
    purpose TEXT NOT NULL,
    -- Purposes: data_processing, federation_sharing, analytics, backup
    scope TEXT NOT NULL DEFAULT 'all',
    -- Scopes: all, beliefs, sessions, patterns

    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,

    -- GDPR: 7-year minimum retention
    retention_until TIMESTAMPTZ NOT NULL,

    metadata JSONB DEFAULT '{}',

    CONSTRAINT consent_records_valid_purpose CHECK (
        purpose IN ('data_processing', 'federation_sharing', 'analytics', 'backup')
    ),
    CONSTRAINT consent_records_valid_scope CHECK (
        scope IN ('all', 'beliefs', 'sessions', 'patterns')
    )
);

CREATE INDEX IF NOT EXISTS idx_consent_records_holder ON consent_records(holder_did);
CREATE INDEX IF NOT EXISTS idx_consent_records_purpose ON consent_records(holder_did, purpose);
CREATE INDEX IF NOT EXISTS idx_consent_records_active ON consent_records(holder_did)
    WHERE revoked_at IS NULL;

-- ============================================================================
-- 2.4: Audit Log
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    actor_did TEXT,

    action TEXT NOT NULL,
    -- Actions: belief_create, belief_supersede, belief_archive,
    --          belief_share, share_revoke,
    --          tension_resolve,
    --          consent_grant, consent_revoke,
    --          data_access, data_export, data_delete,
    --          session_start, session_end,
    --          verification_submit, dispute_submit, dispute_resolve

    resource_type TEXT NOT NULL,
    -- Types: belief, share, consent, tension, session, verification, dispute

    resource_id TEXT,

    details JSONB DEFAULT '{}',

    ip_address TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_time ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(actor_did) WHERE actor_did IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id);
