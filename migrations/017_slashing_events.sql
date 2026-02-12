-- Migration 017: Slashing events table (#346)
-- Tracks stake forfeiture for slashable offenses.

CREATE TABLE IF NOT EXISTS slashing_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    validator_did TEXT NOT NULL,
    offense TEXT NOT NULL,
    severity TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}',
    stake_at_risk NUMERIC(12,6) NOT NULL DEFAULT 0,
    slash_amount NUMERIC(12,6) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    reported_by TEXT NOT NULL,
    reported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    appeal_deadline TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    appeal_reason TEXT,

    CONSTRAINT slashing_events_valid_status
        CHECK (status IN ('pending', 'appealed', 'executed', 'rejected')),
    CONSTRAINT slashing_events_valid_severity
        CHECK (severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_slashing_events_validator ON slashing_events(validator_did);
CREATE INDEX IF NOT EXISTS idx_slashing_events_status ON slashing_events(status);
CREATE INDEX IF NOT EXISTS idx_slashing_events_deadline ON slashing_events(appeal_deadline)
    WHERE status = 'pending';
