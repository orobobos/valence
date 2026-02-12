-- Migration 012: Belief archival infrastructure (#361)
-- Archive superseded beliefs older than a configurable threshold.
-- Archived beliefs: status='archived', embedding=NULL (saves storage),
-- archived_at timestamp set. Chain traversal still works.

-- Add archived_at column
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Index for finding archival candidates
CREATE INDEX IF NOT EXISTS idx_beliefs_archival_candidates
    ON beliefs(modified_at)
    WHERE status = 'superseded';

-- Index for archived beliefs
CREATE INDEX IF NOT EXISTS idx_beliefs_archived
    ON beliefs(archived_at DESC)
    WHERE status = 'archived';

-- Archive superseded beliefs older than threshold
-- Returns count of archived beliefs
CREATE OR REPLACE FUNCTION archive_stale_beliefs(
    p_older_than_days INTEGER DEFAULT 180,
    p_batch_size INTEGER DEFAULT 1000,
    p_dry_run BOOLEAN DEFAULT FALSE
)
RETURNS TABLE (
    archived_count INTEGER,
    freed_embeddings INTEGER
) AS $$
DECLARE
    v_threshold TIMESTAMPTZ;
    v_archived INTEGER := 0;
    v_freed INTEGER := 0;
BEGIN
    v_threshold := NOW() - (p_older_than_days || ' days')::INTERVAL;

    IF p_dry_run THEN
        -- Count candidates without modifying
        SELECT COUNT(*), COUNT(embedding)
        INTO v_archived, v_freed
        FROM beliefs
        WHERE status = 'superseded'
          AND modified_at < v_threshold;
    ELSE
        -- Archive and NULL embeddings
        WITH archived AS (
            UPDATE beliefs
            SET status = 'archived',
                archived_at = NOW(),
                embedding = NULL,
                modified_at = NOW()
            WHERE status = 'superseded'
              AND modified_at < v_threshold
            RETURNING id, (CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS had_embedding
        )
        SELECT COUNT(*)::INTEGER, COALESCE(SUM(had_embedding), 0)::INTEGER
        INTO v_archived, v_freed
        FROM archived;

        -- Remove embedding coverage for archived beliefs
        IF v_archived > 0 THEN
            DELETE FROM embedding_coverage
            WHERE content_type = 'belief'
              AND content_id IN (
                  SELECT id FROM beliefs WHERE status = 'archived' AND archived_at >= NOW() - INTERVAL '1 minute'
              );
        END IF;
    END IF;

    archived_count := v_archived;
    freed_embeddings := v_freed;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;
