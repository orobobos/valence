-- Migration 004: Add sharing intent tracking to shares table
--
-- Adds:
-- - intent column to shares (tracks which SharingIntent was used)
-- - belief_id column to shares (denormalized for join-free list queries)
-- - Backfills belief_id from consent_chains for existing shares

-- Add intent tracking to shares
ALTER TABLE shares ADD COLUMN IF NOT EXISTS intent TEXT;
ALTER TABLE shares ADD COLUMN IF NOT EXISTS belief_id UUID REFERENCES beliefs(id);

-- Backfill belief_id from consent_chains for existing shares
UPDATE shares s SET belief_id = cc.belief_id
FROM consent_chains cc WHERE s.consent_chain_id = cc.id AND s.belief_id IS NULL;

-- Index for listing shares by belief
CREATE INDEX IF NOT EXISTS idx_shares_belief ON shares(belief_id);
CREATE INDEX IF NOT EXISTS idx_shares_intent ON shares(intent);
