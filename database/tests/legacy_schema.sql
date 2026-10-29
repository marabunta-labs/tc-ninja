DROP FUNCTION IF EXISTS match_documents;
DROP TABLE IF EXISTS documents;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id bigserial primary key,
  platform text,
  language text,
  content text,
  metadata jsonb,
  embedding vector(384)
);

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow read access to documents" 
ON documents 
FOR SELECT 
USING (true);

CREATE OR REPLACE FUNCTION match_documents (
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
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    documents.id,
    documents.content,
    documents.platform,
    documents.language,
    documents.metadata,
    1 - (documents.embedding <=> query_embedding) AS similarity
  FROM documents
  WHERE 1 - (documents.embedding <=> query_embedding) > match_threshold
    AND documents.platform = ANY(filter_platforms)
    AND documents.language = filter_language
    AND (filter_version IS NULL OR documents.metadata->>'version' = filter_version)
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$;