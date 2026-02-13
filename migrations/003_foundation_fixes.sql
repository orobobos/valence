-- Migration 003: Foundation Fixes
-- Phase 1.1: Case-insensitive entity deduplication
-- Phase 1.5: Add missing platforms to vkb_sessions constraint

-- ============================================================================
-- 1.1: Case-insensitive entity deduplication
-- ============================================================================

-- Drop the old case-sensitive unique index
DROP INDEX IF EXISTS idx_entities_unique_canonical;

-- Create new case-insensitive unique index
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_unique_canonical
    ON entities(LOWER(name), type)
    WHERE canonical_id IS NULL;

-- ============================================================================
-- 1.5: Add missing platforms to vkb_sessions constraint
-- ============================================================================

-- Drop old constraint and recreate with all platforms
ALTER TABLE vkb_sessions DROP CONSTRAINT IF EXISTS vkb_sessions_valid_platform;
ALTER TABLE vkb_sessions ADD CONSTRAINT vkb_sessions_valid_platform
    CHECK (platform IN (
        'claude-code', 'matrix', 'api', 'slack',
        'claude-web', 'claude-desktop', 'claude-mobile'
    ));
