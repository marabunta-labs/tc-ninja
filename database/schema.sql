-- T&C Ninja — database schema (fresh install).
--
-- This file is NON-destructive: it can be re-run safely. To upgrade a database
-- created with the previous schema (no document_versions table), run
-- database/migrations/001_document_versions.sql and then 002_hybrid_search_and_changes.sql.
--
-- Versioning model
-- ----------------
-- Every scrape of a (platform, language) pair that changed the T&C creates one
-- row in document_versions. Its chunks live in documents (version_id).
--
--   pending     → being inserted; never returned by searches
--   current     → the T&C in force today (exactly one per platform+language)
--   superseded  → deprecated by a newer version; kept only for comparisons
--                 until the scraper purges it

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_versions (
  id bigserial PRIMARY KEY,
  platform text NOT NULL,
  language text NOT NULL,
  version text NOT NULL,                      -- human tag: YYYY-MM-DD (or YYYY-MM-DD.2 …)
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'current', 'superseded')),
  content_hash text NOT NULL,                 -- hash of the cleaned text of all sources
  source_hashes jsonb NOT NULL DEFAULT '{}',  -- {source_url: hash}, to tell what changed
  stats jsonb NOT NULL DEFAULT '{}',          -- {chunks, chars, sources}
  fetched_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  superseded_at timestamptz,
  UNIQUE (platform, language, version)
);

-- At most one "current" version per platform+language.
CREATE UNIQUE INDEX IF NOT EXISTS document_versions_one_current
  ON document_versions (platform, language) WHERE status = 'current';

CREATE TABLE IF NOT EXISTS documents (
  id bigserial PRIMARY KEY,
  platform text,
  language text,
  content text,
  metadata jsonb,
  embedding vector(384),
  version_id bigint REFERENCES document_versions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS documents_version_id_idx ON documents (version_id);
CREATE INDEX IF NOT EXISTS documents_platform_language_idx ON documents (platform, language);

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow read access to documents" ON documents;
CREATE POLICY "Allow read access to documents"
ON documents FOR SELECT USING (true);

DROP POLICY IF EXISTS "Allow read access to document_versions" ON document_versions;
CREATE POLICY "Allow read access to document_versions"
ON document_versions FOR SELECT USING (true);

-- Semantic search.
--   filter_version NULL  → only the CURRENT version (deprecated T&C are never mixed in)
--   filter_version 'tag' → exactly that version, whatever its status (comparisons)
DROP FUNCTION IF EXISTS match_documents(vector, float, int, text[], text, text);

CREATE FUNCTION match_documents (
  query_embedding vector(384),
  match_threshold float,
  match_count int,
  filter_platforms text[],
  filter_language text,
  filter_version text DEFAULT NULL
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
BEGIN
  RETURN QUERY
  SELECT
    documents.id,
    documents.content,
    documents.platform,
    documents.language,
    documents.metadata,
    1 - (documents.embedding <=> query_embedding) AS similarity,
    dv.version,
    dv.status
  FROM documents
  JOIN document_versions dv ON dv.id = documents.version_id
  WHERE documents.platform = ANY(filter_platforms)
    AND documents.language = filter_language
    AND (
      (filter_version IS NULL AND dv.status = 'current')
      OR (filter_version IS NOT NULL AND dv.version = filter_version AND dv.status <> 'pending')
    )
    AND 1 - (documents.embedding <=> query_embedding) > match_threshold
  ORDER BY documents.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- Atomically promote a pending version to "current" and deprecate the previous
-- current one, in a single transaction (searches never see zero or two).
CREATE OR REPLACE FUNCTION activate_document_version(p_version_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v document_versions%ROWTYPE;
BEGIN
  SELECT * INTO v FROM document_versions WHERE id = p_version_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'document version % not found', p_version_id;
  END IF;

  UPDATE document_versions
     SET status = 'superseded', superseded_at = now()
   WHERE platform = v.platform
     AND language = v.language
     AND status = 'current'
     AND id <> p_version_id;

  UPDATE document_versions
     SET status = 'current', activated_at = now()
   WHERE id = p_version_id;
END;
$$;

-- Only the scraper (service role) may promote versions.
REVOKE ALL ON FUNCTION activate_document_version(bigint) FROM PUBLIC, anon, authenticated;

-- ---- Hybrid search, embedding-model tracking, change summaries (same as migrations/002) ----

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
