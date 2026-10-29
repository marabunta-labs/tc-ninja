-- Migration 003: match_documents_hybrid accepts a NULL query_embedding.
--
-- The backend sends NULL when the embeddings service is unavailable (quota, outage). Without this change
-- the vector half would order by NULL and return arbitrary rows; now it is skipped and only full-text search counts.
-- Safe to run more than once (same signature, CREATE OR REPLACE).

BEGIN;

CREATE OR REPLACE FUNCTION match_documents_hybrid (
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
     WHERE query_embedding IS NOT NULL  -- sin vector (servicio de embeddings caído) solo cuenta el texto completo
       AND (filter_embedding_model IS NULL OR s.embedding_model = filter_embedding_model)
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
