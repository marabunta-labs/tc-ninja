import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="T&C Ninja API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción pondrás tu URL de Vercel
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializaciones
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
model = SentenceTransformer('all-MiniLM-L6-v2')
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class ChatRequest(BaseModel):
    platform: str
    question: str

# ... (código anterior)

@app.post("/ask")
async def ask_ninja(request: ChatRequest):
    # 1. Convertir pregunta a vector
    query_vector = model.encode(request.question).tolist()

    # 2. Búsqueda en Supabase (BAJAMOS EL UMBRAL A 0.1 para capturar más contexto)
    rpc_params = {
        "query_embedding": query_vector,
        "match_threshold": 0.1, 
        "match_count": 8  # Subimos a 8 para darle más "leña" a la IA
    }
    
    response = supabase.rpc("match_documents", rpc_params).execute()
    
    # 3. Filtrado flexible de plataforma
    relevant_chunks = [
        doc['content'] for doc in response.data 
        if request.platform.lower() in doc['platform'].lower()
    ]
    
    context = "\n\n".join(relevant_chunks)

    # Si no hay contexto, le pedimos a Gemini que responda con su conocimiento general 
    # pero aclarando que no encontró el texto específico
    if not context:
        context = "No se encontraron fragmentos específicos en la base de datos."

    # 4. CAMBIO DE MODELO AQUÍ
    # Probamos con 'gemini-1.5-flash' o 'gemini-2.0-flash' 
    # Añadimos un try-except por si acaso
    try:
        gemini_model = genai.GenerativeModel('models/gemini-3.1-flash-lite-preview') # Intenta este primero
        
        prompt = f"""
        Eres 'T&C Ninja'. 
        Contexto legal encontrado:
        {context}
        
        Pregunta: {request.question}
        
        Si el contexto está vacío, responde usando tu conocimiento general sobre {request.platform} 
        pero advierte que los documentos oficiales no están cargados. 
        Si hay contexto, priorízalo.
        """
        
        result = gemini_model.generate_content(prompt)
        return {"answer": result.text}
        
    except Exception as e:
        # Si falla el nombre del modelo, intentamos con el de 2026
        # Si la cuota de 3.1 falla, intentamos con 2.5 flash lite
        print(f"Fallo 3.1, intentando 2.5: {e}")
        try:
            backup_model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
            result = backup_model.generate_content(prompt)
            return {"answer": result.text}
        except Exception as e2:
            return {"answer": f"Ninja fuera de servicio: {str(e2)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
