-- Migration 009: Fix VECTOR dimension mismatch in stored procedures
-- procedures.sql had VECTOR(1536) while schema.sql uses VECTOR(384)
-- Also fixes default embedding_type from 'openai_text3_small' to 'local_bge_small'

-- Fix belief_search: VECTOR(1536) -> VECTOR(384)
CREATE OR REPLACE FUNCTION belief_search(
    p_query TEXT,
    p_query_embedding VECTOR(384) DEFAULT NULL,
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

-- Fix belief_set_embedding: VECTOR(1536) -> VECTOR(384), default type -> local_bge_small
CREATE OR REPLACE FUNCTION belief_set_embedding(
    p_belief_id UUID,
    p_embedding VECTOR(384),
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

-- Fix exchange_set_embedding: VECTOR(1536) -> VECTOR(384), default type -> local_bge_small
CREATE OR REPLACE FUNCTION exchange_set_embedding(
    p_exchange_id UUID,
    p_embedding VECTOR(384),
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
