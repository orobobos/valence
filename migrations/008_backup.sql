-- ============================================================================
-- Migration 008: Resilient Storage / Backup Tables
-- Adds: backup_sets, backup_shards
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS backup_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief_count INT NOT NULL DEFAULT 0,
    total_size_bytes INT NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    redundancy_level TEXT NOT NULL DEFAULT 'personal' CHECK (redundancy_level IN (
        'minimal', 'personal', 'federation', 'paranoid'
    )),
    encrypted BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN (
        'in_progress', 'completed', 'failed', 'verified', 'corrupted'
    )),
    shard_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_backup_sets_created ON backup_sets (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_sets_status ON backup_sets (status);

CREATE TABLE IF NOT EXISTS backup_shards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id UUID NOT NULL REFERENCES backup_sets(id),
    shard_index INT NOT NULL,
    is_parity BOOLEAN NOT NULL DEFAULT false,
    size_bytes INT NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL DEFAULT '',
    backend_id TEXT NOT NULL DEFAULT 'local',
    location TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_backup_shards_set ON backup_shards (set_id, shard_index);

COMMIT;
