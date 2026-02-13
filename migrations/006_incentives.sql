-- ============================================================================
-- Migration 006: Incentive System Tables
-- Adds: rewards, transfers, calibration_snapshots, velocity_tracking
-- Depends on: 005_verification.sql (reputations, verifications tables)
-- ============================================================================

BEGIN;

-- ============================================================================
-- Rewards Table — earned but unclaimed reputation rewards
-- ============================================================================

CREATE TABLE IF NOT EXISTS rewards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id TEXT NOT NULL,
    amount FLOAT NOT NULL CHECK (amount > 0),
    reward_type TEXT NOT NULL CHECK (reward_type IN (
        'verification', 'contribution', 'calibration', 'dispute_won',
        'bounty_claimed', 'service', 'referral'
    )),
    source_id UUID,  -- verification_id, dispute_id, belief_id, etc.
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'expired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rewards_identity_status ON rewards (identity_id, status);
CREATE INDEX IF NOT EXISTS idx_rewards_created ON rewards (created_at DESC);

-- ============================================================================
-- Transfers Table — system-initiated reputation movements
-- ============================================================================

CREATE TABLE IF NOT EXISTS transfers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_identity_id TEXT NOT NULL,
    to_identity_id TEXT NOT NULL,
    amount FLOAT NOT NULL CHECK (amount > 0),
    transfer_type TEXT NOT NULL CHECK (transfer_type IN (
        'stake_forfeiture', 'bounty_payout', 'dispute_settlement',
        'calibration_bonus', 'system_adjustment'
    )),
    source_id UUID,  -- verification_id, dispute_id, etc.
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transfers_from ON transfers (from_identity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transfers_to ON transfers (to_identity_id, created_at DESC);

-- ============================================================================
-- Calibration Snapshots — monthly calibration score history
-- ============================================================================

CREATE TABLE IF NOT EXISTS calibration_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    brier_score FLOAT NOT NULL CHECK (brier_score >= 0 AND brier_score <= 1),
    sample_size INT NOT NULL DEFAULT 0,
    reward_earned FLOAT NOT NULL DEFAULT 0,
    penalty_applied FLOAT NOT NULL DEFAULT 0,
    consecutive_well_calibrated INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (identity_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_calibration_identity ON calibration_snapshots (identity_id, period_start DESC);

-- ============================================================================
-- Velocity Tracking — daily/weekly gain tracking for anti-gaming
-- ============================================================================

CREATE TABLE IF NOT EXISTS velocity_tracking (
    identity_id TEXT NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('daily', 'weekly')),
    period_start DATE NOT NULL,
    total_gain FLOAT NOT NULL DEFAULT 0,
    verification_count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (identity_id, period_type, period_start)
);

CREATE INDEX IF NOT EXISTS idx_velocity_identity_period ON velocity_tracking (identity_id, period_type, period_start DESC);

COMMIT;
