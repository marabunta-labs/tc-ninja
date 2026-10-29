-- Migration 002: hybrid (vector + full-text) search, embedding-model tracking and
-- stored change summaries. Run AFTER 001_document_versions.sql.
--
-- * documents.fts          full-text index (Spanish/English per row), over section + content
-- * match_documents_hybrid vector + full-text fused with Reciprocal Rank Fusion
-- * document_versions      embedding_model, full_text (to diff the next version), changes
--
-- Existing rows were embedded with paraphrase-multilingual-MiniLM-L12-v2; new versions use
-- multilingual-e5-small. The hybrid function only uses the vector half for rows embedded
-- with the model of the query, so old rows stay reachable through full-text search.

BEGIN;

ALTER TABLE document_versions
  ADD COLUMN IF NOT EXISTS embedding_model text,
  ADD COLUMN IF NOT EXISTS full_text text,
  ADD COLUMN IF NOT EXISTS changes jsonb;

UPDATE document_versions
   SET embedding_model = 'paraphrase-multilingual-MiniLM-L12-v2'
 WHERE embedding_model IS NULL;

ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS fts tsvector
  GENERATED ALWAYS AS (
    to_tsvector(
      CASE language WHEN 'es' THEN 'spanish'::regconfig ELSE 'english'::regconfig END,
      coalesce(metadata->>'section', '') || ' ' || coalesce(content, '')
    )
  ) STORED;

CREATE INDEX IF NOT EXISTS documents_fts_idx ON documents USING gin (fts);

DROP FUNCTION IF EXISTS match_documents_hybrid(vector, text, int, text[], text, text, text, int);

CREATE FUNCTION match_documents_hybrid (
  query_embedding vector(384),
  query_text text,
  match_count int,
  filter_platforms text[],
  filter_language text,
  filter_version text DEFAULT NULL,
  filter_embedding_model text DEFAULT NULL,
  pool_size int DEFAULT 30
)
RETURNS TABLE (
  id bigint,
  content text,
  platform text,
  language text,
  metadata jsonb,
  similarity float,
  version text,
  version_status text
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  cfg regconfig := CASE filter_language WHEN 'es' THEN 'spanish'::regconfig ELSE 'english'::regconfig END;
  ts_query tsquery;
BEGIN
  -- OR-of-terms query (a natural-language question must not need ALL its words to match).
  -- Lexemes are restricted to alphanumerics so the tsquery can never be malformed.
  SELECT to_tsquery(cfg, string_agg(l, ' | '))
    INTO ts_query
    FROM unnest(tsvector_to_array(to_tsvector(cfg, coalesce(query_text, '')))) AS l
   WHERE l ~ '^[[:alnum:]]+$';

  RETURN QUERY
  WITH scope AS (
    SELECT d.id, d.content, d.platform, d.language, d.metadata, d.embedding, d.fts,
           dv.version, dv.status, dv.embedding_model
      FROM documents d
      JOIN document_versions dv ON dv.id = d.version_id
     WHERE d.platform = ANY(filter_platforms)
       AND d.language = filter_language
       AND (
         (filter_version IS NULL AND dv.status = 'current')
         OR (filter_version IS NOT NULL AND dv.version = filter_version AND dv.status <> 'pending')
       )
  ),
  vec AS (
    SELECT s.id, row_number() OVER (ORDER BY s.embedding <=> query_embedding) AS rnk
      FROM scope s
     WHERE filter_embedding_model IS NULL OR s.embedding_model = filter_embedding_model
     ORDER BY s.embedding <=> query_embedding
     LIMIT pool_size
  ),
  lex AS (
    SELECT s.id, row_number() OVER (ORDER BY ts_rank_cd(s.fts, ts_query) DESC) AS rnk
      FROM scope s
     WHERE ts_query IS NOT NULL AND s.fts @@ ts_query
     ORDER BY ts_rank_cd(s.fts, ts_query) DESC
     LIMIT pool_size
  ),
  fused AS (
    SELECT COALESCE(v.id, l.id) AS id,
           COALESCE(1.0 / (60 + v.rnk), 0) + COALESCE(1.0 / (60 + l.rnk), 0) AS score
      FROM vec v
      FULL OUTER JOIN lex l ON l.id = v.id
  )
  SELECT s.id, s.content, s.platform, s.language, s.metadata,
         f.score::float AS similarity, s.version, s.status
    FROM fused f
    JOIN scope s ON s.id = f.id
   ORDER BY f.score DESC
   LIMIT match_count;
END;
$$;

COMMIT;
