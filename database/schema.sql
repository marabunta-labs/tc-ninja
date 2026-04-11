-- 1. Habilitar la extensión de vectores
create extension if not exists vector;

-- 2. Crear la tabla de documentos
create table documents (
  id bigserial primary key,
  platform text,
  content text,
  metadata jsonb,
  embedding vector(384) -- 384 es la dimensión de all-MiniLM-L6-v2
);

-- 3. Crear una función de búsqueda (para el backend más adelante)
create or replace function match_documents (
  query_embedding vector(384),
  match_threshold float,
  match_count int
)
returns table (
  id bigint,
  platform text,
  content text,
  metadata jsonb,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    documents.id,
    documents.platform,
    documents.content,
    documents.metadata,
    1 - (documents.embedding <=> query_embedding) as similarity
  from documents
  where 1 - (documents.embedding <=> query_embedding) > match_threshold
  order by documents.embedding <=> query_embedding
  limit match_count;
end;
$$;