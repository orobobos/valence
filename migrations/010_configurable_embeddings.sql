-- Migration 010: Configurable embedding dimensions (#364)
-- Makes procedure signatures dimension-agnostic so VECTOR(N) is enforced
-- only at the column level. This allows changing dimensions without
-- recreating procedures.
--
-- Also adds helper function for embedding dimension migration.

-- 1. Make belief_search dimension-agnostic
CREATE OR REPLACE FUNCTION belief_search(
    p_query TEXT,
    p_query_embedding VECTOR DEFAULT NULL,
    p_domain_filter TEXT[] DEFAULT NULL,
    p_entity_id UUID DEFAULT NULL,
    p_include_superseded BOOLEAN DEFAULT FALSE,
    p_limit INTEGER DEFAULT 20,
    p_semantic_weight FLOAT DEFAULT 0.5
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    confidence JSONB,
    domain_path TEXT[],
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    status TEXT,
    keyword_score FLOAT,
    semantic_score FLOAT,
    final_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    WITH keyword_matches AS (
        SELECT b.id,
               b.content,
               b.confidence,
               b.domain_path,
               b.valid_from,
               b.valid_until,
               b.created_at,
               b.status,
               ts_rank_cd(
                   to_tsvector('english', b.content),
                   plainto_tsquery('english', p_query)
               ) AS kw_score
        FROM beliefs b
        WHERE (p_include_superseded OR b.status = 'active')
          AND (p_domain_filter IS NULL OR b.domain_path && p_domain_filter)
          AND (p_entity_id IS NULL OR EXISTS (
              SELECT 1 FROM belief_entities be WHERE be.belief_id = b.id AND be.entity_id = p_entity_id
          ))
    ),
    semantic_matches AS (
        SELECT b.id,
               CASE
                   WHEN p_query_embedding IS NOT NULL AND b.embedding IS NOT NULL
                   THEN 1 - (b.embedding <=> p_query_embedding)
                   ELSE 0
               END AS sem_score
        FROM beliefs b
        WHERE (p_include_superseded OR b.status = 'active')
          AND (p_domain_filter IS NULL OR b.domain_path && p_domain_filter)
          AND (p_entity_id IS NULL OR EXISTS (
              SELECT 1 FROM belief_entities be WHERE be.belief_id = b.id AND be.entity_id = p_entity_id
          ))
    )
    SELECT km.id,
           km.content,
           km.confidence,
           km.domain_path,
           km.valid_from,
           km.valid_until,
           km.created_at,
           km.status,
           km.kw_score AS keyword_score,
           COALESCE(sm.sem_score, 0) AS semantic_score,
           (km.kw_score * (1 - p_semantic_weight) + COALESCE(sm.sem_score, 0) * p_semantic_weight) AS final_score
    FROM keyword_matches km
    LEFT JOIN semantic_matches sm ON km.id = sm.id
    WHERE km.kw_score > 0 OR COALESCE(sm.sem_score, 0) > 0.3
    ORDER BY (km.kw_score * (1 - p_semantic_weight) + COALESCE(sm.sem_score, 0) * p_semantic_weight) DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- 2. Make belief_set_embedding dimension-agnostic
CREATE OR REPLACE FUNCTION belief_set_embedding(
    p_belief_id UUID,
    p_embedding VECTOR,
    p_embedding_type TEXT DEFAULT 'local_bge_small'
)
RETURNS VOID AS $$
BEGIN
    UPDATE beliefs
    SET embedding = p_embedding,
        modified_at = NOW()
    WHERE id = p_belief_id;

    INSERT INTO embedding_coverage (content_type, content_id, embedding_type_id)
    VALUES ('belief', p_belief_id, p_embedding_type)
    ON CONFLICT (content_type, content_id, embedding_type_id)
    DO UPDATE SET embedded_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- 3. Make exchange_set_embedding dimension-agnostic
CREATE OR REPLACE FUNCTION exchange_set_embedding(
    p_exchange_id UUID,
    p_embedding VECTOR,
    p_embedding_type TEXT DEFAULT 'local_bge_small'
)
RETURNS VOID AS $$
BEGIN
    UPDATE vkb_exchanges
    SET embedding = p_embedding
    WHERE id = p_exchange_id;

    INSERT INTO embedding_coverage (content_type, content_id, embedding_type_id)
    VALUES ('exchange', p_exchange_id, p_embedding_type)
    ON CONFLICT (content_type, content_id, embedding_type_id)
    DO UPDATE SET embedded_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- 4. Helper function to migrate embedding dimensions
-- Usage: SELECT migrate_embedding_dimensions(1536, 'openai_text3_small', 'openai', 'text-embedding-3-small');
CREATE OR REPLACE FUNCTION migrate_embedding_dimensions(
    p_new_dims INTEGER,
    p_type_id TEXT,
    p_provider TEXT,
    p_model TEXT
)
RETURNS TABLE (
    step TEXT,
    detail TEXT
) AS $$
BEGIN
    -- Register new embedding type
    INSERT INTO embedding_types (id, provider, model, dimensions, is_default, status)
    VALUES (p_type_id, p_provider, p_model, p_new_dims, FALSE, 'backfilling')
    ON CONFLICT (id) DO UPDATE SET
        dimensions = p_new_dims,
        model = p_model,
        status = 'backfilling';
    step := 'register_type'; detail := format('Registered %s (%s/%s, %s dims)', p_type_id, p_provider, p_model, p_new_dims);
    RETURN NEXT;

    -- Unset old default
    UPDATE embedding_types SET is_default = FALSE WHERE is_default = TRUE AND id != p_type_id;
    step := 'unset_old_default'; detail := 'Unset previous default embedding type';
    RETURN NEXT;

    -- Set new default
    UPDATE embedding_types SET is_default = TRUE, status = 'active' WHERE id = p_type_id;
    step := 'set_new_default'; detail := format('Set %s as default', p_type_id);
    RETURN NEXT;

    -- Mark old type as deprecated
    UPDATE embedding_types SET status = 'deprecated' WHERE id != p_type_id AND status = 'active';
    step := 'deprecate_old'; detail := 'Deprecated previous active types';
    RETURN NEXT;

    -- Drop existing embedding indexes (they're dimension-specific)
    DROP INDEX IF EXISTS idx_beliefs_embedding;
    DROP INDEX IF EXISTS idx_exchanges_embedding;
    DROP INDEX IF EXISTS idx_patterns_embedding;
    step := 'drop_indexes'; detail := 'Dropped old embedding indexes';
    RETURN NEXT;

    -- Alter column types
    EXECUTE format('ALTER TABLE beliefs ALTER COLUMN embedding TYPE VECTOR(%s)', p_new_dims);
    EXECUTE format('ALTER TABLE vkb_exchanges ALTER COLUMN embedding TYPE VECTOR(%s)', p_new_dims);
    EXECUTE format('ALTER TABLE vkb_patterns ALTER COLUMN embedding TYPE VECTOR(%s)', p_new_dims);
    step := 'alter_columns'; detail := format('Altered VECTOR columns to %s dimensions', p_new_dims);
    RETURN NEXT;

    -- NULL out old embeddings (incompatible dimensions)
    UPDATE beliefs SET embedding = NULL WHERE embedding IS NOT NULL;
    UPDATE vkb_exchanges SET embedding = NULL WHERE embedding IS NOT NULL;
    UPDATE vkb_patterns SET embedding = NULL WHERE embedding IS NOT NULL;
    step := 'null_embeddings'; detail := 'Cleared old embeddings (incompatible dimensions)';
    RETURN NEXT;

    -- Clear old coverage records
    DELETE FROM embedding_coverage WHERE embedding_type_id != p_type_id;
    step := 'clear_coverage'; detail := 'Cleared old embedding coverage records';
    RETURN NEXT;

    -- Recreate indexes with new dimensions using HNSW
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_beliefs_embedding ON beliefs USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)');
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_exchanges_embedding ON vkb_exchanges USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)');
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_patterns_embedding ON vkb_patterns USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)');
    step := 'recreate_indexes'; detail := 'Recreated IVFFlat indexes';
    RETURN NEXT;

    step := 'complete'; detail := format('Migration to %s dimensions complete. Run "valence embeddings backfill --force" to re-embed.', p_new_dims);
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;
