"""Migration 023: V2 knowledge system schema migration.

Drops federation/consensus/staking tables, reshapes beliefs→articles,
adds provenance tracking (article_sources, article_mutations), contentions
(renamed from tensions), usage_traces (renamed from belief_retrievals),
mutation queue, and system config.

See migrations/023_v2_knowledge_system.sql for the raw SQL equivalent.
"""

version = "023"
description = "v2_knowledge_system"

# Individual SQL statements executed in order.
# Kept as a tuple of (description, sql) pairs so failures are easy to identify.
_STATEMENTS = [
    # ------------------------------------------------------------------
    # Phase 1: Drop federation/verification views
    # ------------------------------------------------------------------
    ("drop view pending_disputes", "DROP VIEW IF EXISTS pending_disputes CASCADE"),
    ("drop view verifier_leaderboard", "DROP VIEW IF EXISTS verifier_leaderboard CASCADE"),
    ("drop view belief_verification_stats", "DROP VIEW IF EXISTS belief_verification_stats CASCADE"),
    ("drop view sync_status_overview", "DROP VIEW IF EXISTS sync_status_overview CASCADE"),
    ("drop view federated_beliefs", "DROP VIEW IF EXISTS federated_beliefs CASCADE"),
    ("drop view federation_nodes_with_trust", "DROP VIEW IF EXISTS federation_nodes_with_trust CASCADE"),
    ("drop view active_shares", "DROP VIEW IF EXISTS active_shares CASCADE"),
    ("drop view shares_with_consent", "DROP VIEW IF EXISTS shares_with_consent CASCADE"),
    # Drop old beliefs views (replaced by article_ variants)
    ("drop view beliefs_current", "DROP VIEW IF EXISTS beliefs_current CASCADE"),
    ("drop view beliefs_with_entities", "DROP VIEW IF EXISTS beliefs_with_entities CASCADE"),

    # ------------------------------------------------------------------
    # Phase 2: Drop federation/consensus/staking/verification tables
    # ------------------------------------------------------------------
    ("drop table consensus_votes", "DROP TABLE IF EXISTS consensus_votes CASCADE"),
    ("drop table tension_resolutions", "DROP TABLE IF EXISTS tension_resolutions CASCADE"),
    ("drop table sync_events", "DROP TABLE IF EXISTS sync_events CASCADE"),
    ("drop table sync_outbound_queue", "DROP TABLE IF EXISTS sync_outbound_queue CASCADE"),
    ("drop table sync_state", "DROP TABLE IF EXISTS sync_state CASCADE"),
    ("drop table aggregation_sources", "DROP TABLE IF EXISTS aggregation_sources CASCADE"),
    ("drop table aggregated_beliefs", "DROP TABLE IF EXISTS aggregated_beliefs CASCADE"),
    ("drop table belief_trust_annotations", "DROP TABLE IF EXISTS belief_trust_annotations CASCADE"),
    ("drop table user_node_trust", "DROP TABLE IF EXISTS user_node_trust CASCADE"),
    ("drop table node_trust", "DROP TABLE IF EXISTS node_trust CASCADE"),
    ("drop table belief_provenance", "DROP TABLE IF EXISTS belief_provenance CASCADE"),
    ("drop table peer_nodes", "DROP TABLE IF EXISTS peer_nodes CASCADE"),
    ("drop table federation_nodes", "DROP TABLE IF EXISTS federation_nodes CASCADE"),
    ("drop table shares", "DROP TABLE IF EXISTS shares CASCADE"),
    ("drop table consent_chains", "DROP TABLE IF EXISTS consent_chains CASCADE"),
    ("drop table stake_positions", "DROP TABLE IF EXISTS stake_positions CASCADE"),
    ("drop table reputation_events", "DROP TABLE IF EXISTS reputation_events CASCADE"),
    ("drop table discrepancy_bounties", "DROP TABLE IF EXISTS discrepancy_bounties CASCADE"),
    ("drop table disputes", "DROP TABLE IF EXISTS disputes CASCADE"),
    ("drop table verifications", "DROP TABLE IF EXISTS verifications CASCADE"),
    ("drop table reputations", "DROP TABLE IF EXISTS reputations CASCADE"),
    ("drop table trust_edges", "DROP TABLE IF EXISTS trust_edges CASCADE"),
    ("drop table extractors", "DROP TABLE IF EXISTS extractors CASCADE"),

    # ------------------------------------------------------------------
    # Phase 3: Reshape sources
    # ------------------------------------------------------------------
    ("sources add content", "ALTER TABLE sources ADD COLUMN IF NOT EXISTS content TEXT"),
    ("sources add fingerprint", "ALTER TABLE sources ADD COLUMN IF NOT EXISTS fingerprint TEXT"),
    ("sources add reliability", "ALTER TABLE sources ADD COLUMN IF NOT EXISTS reliability NUMERIC(3,2) NOT NULL DEFAULT 0.5"),
    ("sources add embedding", "ALTER TABLE sources ADD COLUMN IF NOT EXISTS embedding VECTOR(384)"),
    (
        "sources add content_tsv",
        """ALTER TABLE sources ADD COLUMN IF NOT EXISTS content_tsv TSVECTOR
            GENERATED ALWAYS AS (to_tsvector('english', COALESCE(content, ''))) STORED""",
    ),
    (
        "sources comment reliability",
        "COMMENT ON COLUMN sources.reliability IS "
        "'Initial reliability: document=0.8, code=0.8, web=0.6, conversation=0.5, observation=0.4, tool_output=0.7, user_input=0.75'",
    ),
    (
        "sources idx embedding",
        "CREATE INDEX IF NOT EXISTS idx_sources_embedding ON sources USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)",
    ),
    ("sources idx tsv", "CREATE INDEX IF NOT EXISTS idx_sources_tsv ON sources USING GIN (content_tsv)"),
    ("sources idx created", "CREATE INDEX IF NOT EXISTS idx_sources_created ON sources(created_at DESC)"),
    (
        "sources idx fingerprint",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_fingerprint ON sources(fingerprint) WHERE fingerprint IS NOT NULL",
    ),

    # ------------------------------------------------------------------
    # Phase 4: Rename beliefs → articles
    # ------------------------------------------------------------------
    ("rename table beliefs to articles", "ALTER TABLE beliefs RENAME TO articles"),
    ("rename pk index", "ALTER INDEX beliefs_pkey RENAME TO articles_pkey"),
    ("rename idx domain", "ALTER INDEX IF EXISTS idx_beliefs_domain RENAME TO idx_articles_domain"),
    ("rename idx status", "ALTER INDEX IF EXISTS idx_beliefs_status RENAME TO idx_articles_status"),
    ("rename idx created", "ALTER INDEX IF EXISTS idx_beliefs_created RENAME TO idx_articles_created"),
    ("rename idx tsv", "ALTER INDEX IF EXISTS idx_beliefs_tsv RENAME TO idx_articles_tsv"),
    ("rename idx source", "ALTER INDEX IF EXISTS idx_beliefs_source RENAME TO idx_articles_source"),
    ("rename idx embedding", "ALTER INDEX IF EXISTS idx_beliefs_embedding RENAME TO idx_articles_embedding"),
    ("rename idx holder", "ALTER INDEX IF EXISTS idx_beliefs_holder RENAME TO idx_articles_holder"),
    ("rename idx content_hash", "ALTER INDEX IF EXISTS idx_beliefs_content_hash RENAME TO idx_articles_content_hash"),
    ("rename idx archival", "ALTER INDEX IF EXISTS idx_beliefs_archival_candidates RENAME TO idx_articles_archival_candidates"),
    ("rename idx archived", "ALTER INDEX IF EXISTS idx_beliefs_archived RENAME TO idx_articles_archived"),

    # Add article-specific columns
    ("articles add title", "ALTER TABLE articles ADD COLUMN IF NOT EXISTS title TEXT"),
    (
        "articles add author_type",
        "ALTER TABLE articles ADD COLUMN IF NOT EXISTS author_type TEXT NOT NULL DEFAULT 'system' "
        "CHECK (author_type IN ('system', 'operator', 'agent'))",
    ),
    ("articles add pinned", "ALTER TABLE articles ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE"),
    ("articles add size_tokens", "ALTER TABLE articles ADD COLUMN IF NOT EXISTS size_tokens INTEGER"),
    ("articles add compiled_at", "ALTER TABLE articles ADD COLUMN IF NOT EXISTS compiled_at TIMESTAMPTZ"),
    ("articles add usage_score", "ALTER TABLE articles ADD COLUMN IF NOT EXISTS usage_score NUMERIC(8,4) NOT NULL DEFAULT 0"),

    # Drop federation columns from articles
    ("articles drop opt_out_federation", "ALTER TABLE articles DROP COLUMN IF EXISTS opt_out_federation"),
    ("articles drop share_policy", "ALTER TABLE articles DROP COLUMN IF EXISTS share_policy"),
    ("articles drop visibility", "ALTER TABLE articles DROP COLUMN IF EXISTS visibility"),
    ("articles drop is_local", "ALTER TABLE articles DROP COLUMN IF EXISTS is_local"),
    ("articles drop origin_node_id", "ALTER TABLE articles DROP COLUMN IF EXISTS origin_node_id"),

    # ------------------------------------------------------------------
    # Phase 5: Rename belief_entities → article_entities
    # ------------------------------------------------------------------
    ("rename table belief_entities", "ALTER TABLE belief_entities RENAME TO article_entities"),
    ("rename idx article_entities", "ALTER INDEX IF EXISTS idx_belief_entities_entity RENAME TO idx_article_entities_entity"),

    # ------------------------------------------------------------------
    # Phase 6: Create article_sources
    # ------------------------------------------------------------------
    (
        "create article_sources",
        """CREATE TABLE IF NOT EXISTS article_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            relationship TEXT NOT NULL
                CHECK (relationship IN ('originates', 'confirms', 'supersedes', 'contradicts', 'contends')),
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes TEXT,
            UNIQUE(article_id, source_id, relationship)
        )""",
    ),
    ("idx article_sources_article", "CREATE INDEX IF NOT EXISTS idx_article_sources_article ON article_sources(article_id)"),
    ("idx article_sources_source", "CREATE INDEX IF NOT EXISTS idx_article_sources_source ON article_sources(source_id)"),
    ("idx article_sources_rel", "CREATE INDEX IF NOT EXISTS idx_article_sources_rel ON article_sources(relationship)"),

    # ------------------------------------------------------------------
    # Phase 6b: Create article_mutations
    # ------------------------------------------------------------------
    (
        "create article_mutations",
        """CREATE TABLE IF NOT EXISTS article_mutations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            mutation_type TEXT NOT NULL
                CHECK (mutation_type IN ('created', 'updated', 'split', 'merged', 'archived')),
            article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
            related_article_id UUID REFERENCES articles(id) ON DELETE SET NULL,
            trigger_source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
            summary TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
    ),
    ("idx article_mutations_article", "CREATE INDEX IF NOT EXISTS idx_article_mutations_article ON article_mutations(article_id)"),
    ("idx article_mutations_type", "CREATE INDEX IF NOT EXISTS idx_article_mutations_type ON article_mutations(mutation_type)"),

    # ------------------------------------------------------------------
    # Phase 7: Rename tensions → contentions
    # ------------------------------------------------------------------
    ("rename table tensions to contentions", "ALTER TABLE tensions RENAME TO contentions"),
    ("rename idx contentions_status", "ALTER INDEX IF EXISTS idx_tensions_status RENAME TO idx_contentions_status"),
    ("rename idx contentions_severity", "ALTER INDEX IF EXISTS idx_tensions_severity RENAME TO idx_contentions_severity"),
    ("rename idx contentions_belief_a", "ALTER INDEX IF EXISTS idx_tensions_belief_a RENAME TO idx_contentions_belief_a"),
    ("rename idx contentions_belief_b", "ALTER INDEX IF EXISTS idx_tensions_belief_b RENAME TO idx_contentions_belief_b"),
    ("contentions add materiality", "ALTER TABLE contentions ADD COLUMN IF NOT EXISTS materiality NUMERIC(3,2) DEFAULT 0.5"),

    # ------------------------------------------------------------------
    # Phase 8: Rename belief_retrievals → usage_traces
    # ------------------------------------------------------------------
    ("rename table belief_retrievals to usage_traces", "ALTER TABLE belief_retrievals RENAME TO usage_traces"),
    ("rename idx usage_traces_belief", "ALTER INDEX IF EXISTS idx_belief_retrievals_belief RENAME TO idx_usage_traces_belief"),
    ("rename idx usage_traces_time", "ALTER INDEX IF EXISTS idx_belief_retrievals_time RENAME TO idx_usage_traces_time"),
    ("usage_traces add source_id", "ALTER TABLE usage_traces ADD COLUMN IF NOT EXISTS source_id UUID REFERENCES sources(id) ON DELETE SET NULL"),
    (
        "create view article_usage",
        """CREATE OR REPLACE VIEW article_usage AS
            SELECT
                belief_id AS article_id,
                query_text,
                tool_name,
                retrieved_at,
                final_score,
                session_id
            FROM usage_traces
            WHERE belief_id IS NOT NULL""",
    ),

    # ------------------------------------------------------------------
    # Phase 9: Mutation queue
    # ------------------------------------------------------------------
    (
        "create mutation_queue",
        """CREATE TABLE IF NOT EXISTS mutation_queue (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            operation TEXT NOT NULL
                CHECK (operation IN ('split', 'merge_candidate', 'recompile', 'decay_check')),
            article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
            priority INTEGER NOT NULL DEFAULT 5,
            payload JSONB DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ
        )""",
    ),
    ("idx mutation_queue_status", "CREATE INDEX IF NOT EXISTS idx_mutation_queue_status ON mutation_queue(status, priority)"),
    ("idx mutation_queue_article", "CREATE INDEX IF NOT EXISTS idx_mutation_queue_article ON mutation_queue(article_id)"),

    # ------------------------------------------------------------------
    # Phase 10: Updated views
    # ------------------------------------------------------------------
    (
        "create view articles_current",
        """CREATE OR REPLACE VIEW articles_current AS
            SELECT * FROM articles
            WHERE status = 'active'
              AND superseded_by_id IS NULL""",
    ),
    (
        "create view articles_with_sources",
        """CREATE OR REPLACE VIEW articles_with_sources AS
            SELECT
                a.*,
                COUNT(DISTINCT asrc.source_id) AS source_count,
                array_agg(DISTINCT asrc.relationship) FILTER (WHERE asrc.relationship IS NOT NULL) AS relationship_types,
                bool_or(asrc.relationship = 'contradicts' OR asrc.relationship = 'contends') AS has_contention
            FROM articles a
            LEFT JOIN article_sources asrc ON a.id = asrc.article_id
            WHERE a.status = 'active'
            GROUP BY a.id""",
    ),

    # ------------------------------------------------------------------
    # Phase 11: System config
    # ------------------------------------------------------------------
    (
        "create system_config",
        """CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
    ),
    (
        "system_config defaults",
        """INSERT INTO system_config (key, value) VALUES
            ('bounded_memory',       '{"max_articles": 10000, "max_sources": 100000}'),
            ('right_sizing',         '{"max_tokens": 4000, "min_tokens": 200, "target_tokens": 2000}'),
            ('reliability_defaults', '{"document": 0.8, "code": 0.8, "web": 0.6, "conversation": 0.5, "observation": 0.4, "tool_output": 0.7, "user_input": 0.75}'),
            ('freshness',            '{"decay_rate": 0.01, "staleness_days": 90}'),
            ('contention',           '{"materiality_threshold": 0.3}')
        ON CONFLICT (key) DO NOTHING""",
    ),

    # ------------------------------------------------------------------
    # Phase 12: Data backfill
    # ------------------------------------------------------------------
    (
        "backfill article_sources from source_id",
        """INSERT INTO article_sources (article_id, source_id, relationship)
            SELECT id, source_id, 'originates'
            FROM articles
            WHERE source_id IS NOT NULL
            ON CONFLICT (article_id, source_id, relationship) DO NOTHING""",
    ),
]


def up(conn) -> None:
    """Apply the v2 knowledge system migration."""
    cur = conn.cursor()
    try:
        for description, sql in _STATEMENTS:
            try:
                cur.execute(sql)
            except Exception as exc:
                raise RuntimeError(f"Migration 023 step '{description}' failed: {exc}") from exc
    finally:
        cur.close()


def down(conn) -> None:
    """Partial rollback for v2 knowledge system migration.

    NOTE: This rollback is intentionally incomplete.  The DROP TABLE statements
    in up() are irreversible without a backup; this down() only reverses the
    additive changes (new tables and columns) so that the migration runner can
    track state correctly in development environments.

    Production rollback requires restoring from a pre-migration backup.
    """
    cur = conn.cursor()
    try:
        # Drop new tables / views
        cur.execute("DROP VIEW IF EXISTS articles_with_sources CASCADE")
        cur.execute("DROP VIEW IF EXISTS articles_current CASCADE")
        cur.execute("DROP VIEW IF EXISTS article_usage CASCADE")
        cur.execute("DROP TABLE IF EXISTS system_config CASCADE")
        cur.execute("DROP TABLE IF EXISTS mutation_queue CASCADE")
        cur.execute("DROP TABLE IF EXISTS article_mutations CASCADE")
        cur.execute("DROP TABLE IF EXISTS article_sources CASCADE")

        # Rename usage_traces back to belief_retrievals
        cur.execute("ALTER TABLE IF EXISTS usage_traces RENAME TO belief_retrievals")

        # Rename contentions back to tensions
        cur.execute("ALTER TABLE IF EXISTS contentions RENAME TO tensions")

        # Rename article_entities back to belief_entities
        cur.execute("ALTER TABLE IF EXISTS article_entities RENAME TO belief_entities")

        # Rename articles back to beliefs
        cur.execute("ALTER TABLE IF EXISTS articles RENAME TO beliefs")
        cur.execute("ALTER INDEX IF EXISTS articles_pkey RENAME TO beliefs_pkey")

        # Drop added source columns
        cur.execute("ALTER TABLE sources DROP COLUMN IF EXISTS content_tsv")
        cur.execute("ALTER TABLE sources DROP COLUMN IF EXISTS embedding")
        cur.execute("ALTER TABLE sources DROP COLUMN IF EXISTS reliability")
        cur.execute("ALTER TABLE sources DROP COLUMN IF EXISTS fingerprint")
        cur.execute("ALTER TABLE sources DROP COLUMN IF EXISTS content")
    finally:
        cur.close()
