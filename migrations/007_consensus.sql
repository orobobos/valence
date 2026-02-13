-- ============================================================================
-- Migration 007: Consensus Mechanism Tables
-- Adds: belief_consensus_status, corroborations, challenges, layer_transitions
-- Depends on: beliefs table from schema.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- Belief Consensus Status — tracks layer and corroboration for each belief
-- ============================================================================

CREATE TABLE IF NOT EXISTS belief_consensus_status (
    belief_id UUID PRIMARY KEY,
    current_layer TEXT NOT NULL DEFAULT 'l1_personal' CHECK (current_layer IN (
        'l1_personal', 'l2_federated', 'l3_domain', 'l4_communal'
    )),
    corroboration_count INT NOT NULL DEFAULT 0,
    total_corroboration_weight FLOAT NOT NULL DEFAULT 0.0,
    finality TEXT NOT NULL DEFAULT 'tentative' CHECK (finality IN (
        'tentative', 'provisional', 'established', 'settled'
    )),
    last_challenge_at TIMESTAMPTZ,
    elevated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Corroborations — independent verification events between beliefs
-- ============================================================================

CREATE TABLE IF NOT EXISTS corroborations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    primary_belief_id UUID NOT NULL,
    corroborating_belief_id UUID NOT NULL,
    primary_holder TEXT NOT NULL,
    corroborator TEXT NOT NULL,
    semantic_similarity FLOAT NOT NULL CHECK (semantic_similarity >= 0 AND semantic_similarity <= 1),
    independence JSONB NOT NULL DEFAULT '{}',
    effective_weight FLOAT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_corroborations_primary ON corroborations (primary_belief_id);
CREATE INDEX IF NOT EXISTS idx_corroborations_corroborating ON corroborations (corroborating_belief_id);

-- ============================================================================
-- Challenges — challenges to a belief's consensus layer
-- ============================================================================

CREATE TABLE IF NOT EXISTS challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id UUID NOT NULL,
    challenger_id TEXT NOT NULL,
    target_layer TEXT NOT NULL CHECK (target_layer IN (
        'l1_personal', 'l2_federated', 'l3_domain', 'l4_communal'
    )),
    reasoning TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]',
    stake_amount FLOAT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'reviewing', 'upheld', 'rejected', 'expired'
    )),
    resolution_reasoning TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_challenges_belief ON challenges (belief_id, status);

-- ============================================================================
-- Layer Transitions — audit trail of layer changes
-- ============================================================================

CREATE TABLE IF NOT EXISTS layer_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id UUID NOT NULL,
    from_layer TEXT,
    to_layer TEXT NOT NULL CHECK (to_layer IN (
        'l1_personal', 'l2_federated', 'l3_domain', 'l4_communal'
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_layer_transitions_belief ON layer_transitions (belief_id, created_at DESC);

COMMIT;
