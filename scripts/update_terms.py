import os
import requests
import datetime
import hashlib
from sentence_transformers import SentenceTransformer
from supabase import create_client
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Esto permite que funcione en local con .env y en GitHub con sus Secrets
load_dotenv() 

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Modelo de embeddings gratuito (corre en tu CPU/GH Actions)
model = SentenceTransformer('all-MiniLM-L6-v2')

SOURCES = {
    "Instagram": "https://r.jina.ai/https://help.instagram.com/581066165581870",
    "TikTok": "https://r.jina.ai/https://www.tiktok.com/legal/terms-of-service",
    "X-Twitter": "https://r.jina.ai/https://x.com/en/tos"
}

def get_chunks(text, size=1000, overlap=150):
    # Corta de forma inteligente priorizando párrafos y puntos, manteniendo 150 caracteres de solapamiento
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    return splitter.split_text(text)

def process_source(name, url):
    print(f"🥷 Ninja analizando: {name}...")
    response = requests.get(url)
    if response.status_code != 200:
        print(f"❌ Error accediendo a {name}")
        return

    full_text = response.text
    chunks = get_chunks(full_text)

    current_date = datetime.date.today().isoformat()

    for i, chunk in enumerate(chunks):
        # Generar vector
        embedding = model.encode(chunk).tolist()

        # Subir a Supabase
        data = {
            "platform": name,
            "content": chunk,
            "embedding": embedding,
            "metadata": {
                "chunk_index": i, 
                "source_url": url,
                "fetch_date": current_date,
                "version": "2026-04" 
            }
        }
        supabase.table("documents").insert(data).execute()

    print(f"✅ {name} actualizado con éxito ({len(chunks)} fragmentos).")

if __name__ == "__main__":
    for name, url in SOURCES.items():
        process_source(name, url)
