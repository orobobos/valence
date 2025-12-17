-- Valence Conversation Module
-- Captures conversations at multiple scales for agent memory

-- Sessions: Meso-scale, one per conversation session
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at INTEGER NOT NULL DEFAULT (unixepoch()),
    ended_at INTEGER,
    platform TEXT,  -- claude-code, api, etc.
    project_context TEXT,  -- which project this was about
    summary TEXT,  -- curated summary (populated during/after)
    themes TEXT,  -- JSON array of identified themes
    status TEXT NOT NULL DEFAULT 'active',  -- active, completed, abandoned
    CONSTRAINT valid_status CHECK (status IN ('active', 'completed', 'abandoned'))
);

-- Exchanges: Micro-scale, individual turns within a session
CREATE TABLE IF NOT EXISTS exchanges (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,  -- order within session
    role TEXT NOT NULL,  -- user, assistant, system
    content TEXT NOT NULL,
    timestamp INTEGER NOT NULL DEFAULT (unixepoch()),
    tokens_approx INTEGER,  -- rough token count for context management
    CONSTRAINT valid_role CHECK (role IN ('user', 'assistant', 'system'))
);

-- Curated Insights: extracted from sessions, link to main entries table
-- These become first-class entries with full provenance
CREATE TABLE IF NOT EXISTS session_insights (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    extraction_method TEXT,  -- manual, auto, hybrid
    extracted_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE(session_id, entry_id)
);

-- Patterns: Macro-scale, emergent across multiple sessions
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- topic_recurrence, preference, working_style, etc.
    description TEXT NOT NULL,
    evidence TEXT,  -- JSON array of session_ids that support this
    first_observed_at INTEGER NOT NULL DEFAULT (unixepoch()),
    last_observed_at INTEGER NOT NULL DEFAULT (unixepoch()),
    occurrence_count INTEGER DEFAULT 1,
    confidence REAL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'emerging',  -- emerging, established, fading
    CONSTRAINT valid_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0),
    CONSTRAINT valid_status CHECK (status IN ('emerging', 'established', 'fading'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_context);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_exchanges_session ON exchanges(session_id);
CREATE INDEX IF NOT EXISTS idx_exchanges_timestamp ON exchanges(timestamp);
CREATE INDEX IF NOT EXISTS idx_exchanges_role ON exchanges(role);
CREATE INDEX IF NOT EXISTS idx_session_insights_session ON session_insights(session_id);
CREATE INDEX IF NOT EXISTS idx_session_insights_entry ON session_insights(entry_id);
CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(type);
CREATE INDEX IF NOT EXISTS idx_patterns_status ON patterns(status);

-- View: sessions with exchange count and insight count
CREATE VIEW IF NOT EXISTS sessions_overview AS
SELECT
    s.*,
    datetime(s.started_at, 'unixepoch') as started_at_iso,
    datetime(s.ended_at, 'unixepoch') as ended_at_iso,
    COUNT(DISTINCT e.id) as exchange_count,
    COUNT(DISTINCT si.id) as insight_count
FROM sessions s
LEFT JOIN exchanges e ON s.id = e.session_id
LEFT JOIN session_insights si ON s.id = si.session_id
GROUP BY s.id;

-- View: patterns with readable timestamps
CREATE VIEW IF NOT EXISTS patterns_readable AS
SELECT
    p.*,
    datetime(p.first_observed_at, 'unixepoch') as first_observed_iso,
    datetime(p.last_observed_at, 'unixepoch') as last_observed_iso
FROM patterns p;
