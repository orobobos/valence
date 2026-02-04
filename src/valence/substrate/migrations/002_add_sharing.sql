-- Migration 002: Add sharing tables (Issue #50)
-- Implements consent chains and encrypted shares for DIRECT sharing level

-- ============================================================================
-- CONSENT CHAINS
-- ============================================================================

-- Consent chains track the provenance and permissions for shared beliefs
CREATE TABLE IF NOT EXISTS consent_chains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Link to the shared belief
    belief_id UUID NOT NULL REFERENCES beliefs(id) ON DELETE CASCADE,
    
    -- Origin information (first sharer in the chain)
    origin_sharer TEXT NOT NULL,  -- DID of original sharer
    origin_timestamp TIMESTAMPTZ NOT NULL,
    origin_policy JSONB NOT NULL,  -- SharePolicy as JSON
    origin_signature BYTEA NOT NULL,  -- Ed25519 signature
    
    -- Chain integrity
    chain_hash BYTEA NOT NULL,  -- SHA256(consent_origin + signature)
    hops JSONB NOT NULL DEFAULT '[]',  -- Array of hop records for BOUNDED/CASCADING
    
    -- Status
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,  -- DID
    revocation_reason TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_consent_chains_belief ON consent_chains(belief_id);
CREATE INDEX IF NOT EXISTS idx_consent_chains_sharer ON consent_chains(origin_sharer);
CREATE INDEX IF NOT EXISTS idx_consent_chains_revoked ON consent_chains(revoked);
CREATE INDEX IF NOT EXISTS idx_consent_chains_created ON consent_chains(created_at DESC);

-- ============================================================================
-- SHARES
-- ============================================================================

-- Shares link encrypted content to consent chains and recipients
CREATE TABLE IF NOT EXISTS shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Link to consent chain
    consent_chain_id UUID NOT NULL REFERENCES consent_chains(id) ON DELETE CASCADE,
    
    -- Encrypted content for recipient
    encrypted_envelope JSONB NOT NULL,  -- EncryptionEnvelope as JSON
    
    -- Recipient
    recipient_did TEXT NOT NULL,
    
    -- Access tracking
    accessed_at TIMESTAMPTZ,
    access_count INTEGER NOT NULL DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shares_consent_chain ON shares(consent_chain_id);
CREATE INDEX IF NOT EXISTS idx_shares_recipient ON shares(recipient_did);
CREATE INDEX IF NOT EXISTS idx_shares_created ON shares(created_at DESC);

-- Unique constraint: one share per consent chain per recipient
CREATE UNIQUE INDEX IF NOT EXISTS idx_shares_unique_recipient 
    ON shares(consent_chain_id, recipient_did);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View of shares with consent chain info
CREATE OR REPLACE VIEW shares_with_consent AS
SELECT 
    s.*,
    cc.belief_id,
    cc.origin_sharer,
    cc.origin_timestamp,
    cc.origin_policy,
    cc.revoked as consent_revoked
FROM shares s
JOIN consent_chains cc ON s.consent_chain_id = cc.id;

-- Active shares (not revoked)
CREATE OR REPLACE VIEW active_shares AS
SELECT * FROM shares_with_consent
WHERE NOT consent_revoked;
