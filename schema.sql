-- Valence Knowledge Base Schema
-- Modular and composable: core is required, modules attach as needed

-- Core table: every entry has these
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- belief, decision, reference, artifact, principle, unknown, etc.
    content TEXT NOT NULL,
    summary TEXT,  -- optional short version
    created_at TEXT NOT NULL,  -- when the thing came into being (ISO 8601)
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),  -- when we learned about it
    modified_at TEXT NOT NULL DEFAULT (datetime('now')),  -- when KB entry last changed
    confidence REAL DEFAULT 1.0,  -- 0.0 to 1.0
    source TEXT,  -- where it came from
    source_type TEXT,  -- conversation, document, inference, etc.
    parent_id TEXT REFERENCES entries(id),  -- hierarchical relationship
    CONSTRAINT valid_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

-- Tags for flexible categorization
CREATE TABLE IF NOT EXISTS tags (
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);

-- Relationships between entries
CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    to_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    type TEXT NOT NULL,  -- derived_from, supports, contradicts, supersedes, relates_to, etc.
    strength REAL DEFAULT 1.0,  -- 0.0 to 1.0
    reasoning TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT valid_strength CHECK (strength >= 0.0 AND strength <= 1.0)
);

-- Module: Contestation (for disputed or evolving beliefs)
CREATE TABLE IF NOT EXISTS contestation (
    entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',  -- active, contested, resolved, superseded
    contested_by TEXT,  -- what/who contests this
    alternatives TEXT,  -- JSON array of alternative positions
    resolution TEXT,
    resolved_at TEXT
);

-- Module: Scope (for visibility and ownership)
CREATE TABLE IF NOT EXISTS scope (
    entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    visibility TEXT NOT NULL DEFAULT 'private',  -- private, project, shared, public
    owned_by TEXT,
    shared_with TEXT  -- JSON array of entities
);

-- Module: Lifecycle (for review and expiration)
CREATE TABLE IF NOT EXISTS lifecycle (
    entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',  -- draft, active, review, archived, expired
    reviewed_at TEXT,
    review_interval_days INTEGER,
    expires_at TEXT
);

-- Module: Artifacts (for tracking external files)
CREATE TABLE IF NOT EXISTS artifacts (
    entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    filepath TEXT NOT NULL,
    filehash TEXT,  -- for detecting changes
    last_synced_at TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(type);
CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
CREATE INDEX IF NOT EXISTS idx_entries_parent ON entries(parent_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_id);
CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(type);

-- View: entries with their tags
CREATE VIEW IF NOT EXISTS entries_with_tags AS
SELECT 
    e.*,
    GROUP_CONCAT(t.tag, ', ') as tags
FROM entries e
LEFT JOIN tags t ON e.id = t.entry_id
GROUP BY e.id;
