-- Migration 022: Add 'openclaw' to vkb_sessions platform constraint
-- The Platform enum and DB constraint were missing openclaw and other platforms
-- that the DB constraint already allowed (claude-web, claude-desktop, claude-mobile)

ALTER TABLE vkb_sessions DROP CONSTRAINT IF EXISTS vkb_sessions_valid_platform;
ALTER TABLE vkb_sessions ADD CONSTRAINT vkb_sessions_valid_platform
  CHECK (platform = ANY (ARRAY[
    'claude-code', 'matrix', 'api', 'slack',
    'claude-web', 'claude-desktop', 'claude-mobile',
    'openclaw'
  ]));
