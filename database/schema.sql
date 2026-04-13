-- 1. Habilitar la extensión de vectores
create extension if not exists vector;

-- 2. Crear la tabla de documentos
create or replace table documents (
  id bigserial primary key,
  platform text,
  content text,
  metadata jsonb,
  embedding vector(384) -- 384 es la dimensión de all-MiniLM-L6-v2
);

-- 3. Crear una función de búsqueda (para el backend más adelante)
DROP FUNCTION IF EXISTS match_documents;

CREATE OR REPLACE FUNCTION match_documents (
  query_embedding vector(384),
  match_threshold float,
  match_count int,
  filter_platforms text[] -- <--- Nuevo parámetro: array de plataformas
)
RETURNS TABLE (
  id bigint,
  content text,
  platform text,
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
    documents.metadata,
    1 - (documents.embedding <=> query_embedding) AS similarity
  FROM documents
  WHERE 1 - (documents.embedding <=> query_embedding) > match_threshold
    AND documents.platform = ANY(filter_platforms) -- <--- Filtramos aquí mismo
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$;