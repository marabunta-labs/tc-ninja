-- Migration 001: explicit T&C versioning (current / superseded / pending).
--
-- Run ONCE in the Supabase SQL editor, BEFORE deploying the new backend and
-- scraper. Existing chunks are kept: each distinct metadata->>'version' becomes
-- a document_versions row; the newest per (platform, language) is "current",
-- the rest "superseded". Runs in a single transaction.

BEGIN;

CREATE TABLE IF NOT EXISTS document_versions (
  id bigserial PRIMARY KEY,
  platform text NOT NULL,
  language text NOT NULL,
  version text NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'current', 'superseded')),
  content_hash text NOT NULL,
  source_hashes jsonb NOT NULL DEFAULT '{}',
  stats jsonb NOT NULL DEFAULT '{}',
  fetched_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  superseded_at timestamptz,
  UNIQUE (platform, language, version)
);

ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS version_id bigint REFERENCES document_versions(id) ON DELETE CASCADE;

-- Backfill from the legacy metadata.
INSERT INTO document_versions
  (platform, language, version, status, content_hash, fetched_at, activated_at, superseded_at)
SELECT
  platform,
  language,
  version,
  CASE WHEN rn = 1 THEN 'current' ELSE 'superseded' END,
  content_hash,
  fetched_at,
  fetched_at,
  CASE WHEN rn = 1 THEN NULL ELSE now() END
FROM (
  SELECT
    d.platform,
    d.language,
    COALESCE(d.metadata->>'version', 'legacy') AS version,
    COALESCE(max(d.metadata->>'content_hash'), '') AS content_hash,
    COALESCE(
      min(CASE WHEN d.metadata->>'fetch_date' ~ '^\d{4}-\d{2}-\d{2}$'
               THEN (d.metadata->>'fetch_date')::timestamptz END),
      now()
    ) AS fetched_at,
    row_number() OVER (
      PARTITION BY d.platform, d.language ORDER BY max(d.id) DESC
    ) AS rn
  FROM documents d
  WHERE d.platform IS NOT NULL AND d.language IS NOT NULL
  GROUP BY d.platform, d.language, COALESCE(d.metadata->>'version', 'legacy')
) AS legacy;

UPDATE documents d
   SET version_id = dv.id
  FROM document_versions dv
 WHERE d.version_id IS NULL
   AND dv.platform = d.platform
   AND dv.language = d.language
   AND dv.version = COALESCE(d.metadata->>'version', 'legacy');

CREATE UNIQUE INDEX IF NOT EXISTS document_versions_one_current
  ON document_versions (platform, language) WHERE status = 'current';
CREATE INDEX IF NOT EXISTS documents_version_id_idx ON documents (version_id);
CREATE INDEX IF NOT EXISTS documents_platform_language_idx ON documents (platform, language);

ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow read access to document_versions" ON document_versions;
CREATE POLICY "Allow read access to document_versions"
ON document_versions FOR SELECT USING (true);

-- New search function (adds version / version_status to the result).
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

REVOKE ALL ON FUNCTION activate_document_version(bigint) FROM PUBLIC, anon, authenticated;

COMMIT;
