-- Migration 018: Merkle checkpoints, partition events, and commit-reveal (#351, #353)

-- Merkle checkpoints: periodic snapshots of the belief set Merkle root
CREATE TABLE IF NOT EXISTS merkle_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    root_hash CHAR(64) NOT NULL,
    belief_count INT NOT NULL,
    peer_roots JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_merkle_checkpoints_time ON merkle_checkpoints(created_at DESC);

-- Partition events: detected divergence between local and peer belief sets
CREATE TABLE IF NOT EXISTS partition_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    peer_did TEXT NOT NULL,
    local_root CHAR(64) NOT NULL,
    peer_root CHAR(64) NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,

    CONSTRAINT partition_events_valid_severity
        CHECK (severity IN ('info', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_partition_events_peer ON partition_events(peer_did);
CREATE INDEX IF NOT EXISTS idx_partition_events_unresolved ON partition_events(detected_at)
    WHERE resolved_at IS NULL;

-- Corroboration commitments: commit-reveal for tamper-resistant corroboration
CREATE TABLE IF NOT EXISTS corroboration_commitments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_id UUID NOT NULL REFERENCES beliefs(id) ON DELETE CASCADE,
    committer_did TEXT NOT NULL,
    commitment_hash CHAR(64) NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reveal_window_opens TIMESTAMPTZ NOT NULL,
    reveal_window_closes TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'committed',
    revealed_at TIMESTAMPTZ,
    vote_value TEXT,
    nonce TEXT,

    CONSTRAINT corroboration_commitments_valid_status
        CHECK (status IN ('committed', 'revealed', 'no_reveal', 'penalty'))
);

CREATE INDEX IF NOT EXISTS idx_commitments_belief ON corroboration_commitments(belief_id);
CREATE INDEX IF NOT EXISTS idx_commitments_committer ON corroboration_commitments(committer_did);
CREATE INDEX IF NOT EXISTS idx_commitments_status ON corroboration_commitments(status)
    WHERE status = 'committed';
