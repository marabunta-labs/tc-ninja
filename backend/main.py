import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from dotenv import load_dotenv
from typing import List, Dict

from prompts import SYSTEM_PROMPT

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

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    platform: str
    messages: List[Message]

@app.post("/ask")
async def ask_ninja(request: ChatRequest):
    # 1. La última pregunta es la que usamos para buscar en Supabase (RAG)
    last_user_message = request.messages[-1].content
    query_vector = model.encode(last_user_message).tolist()

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
        # 2. Construimos el historial para Gemini
        # Convertimos nuestros mensajes al formato que entiende Gemini
        history = []
        for msg in request.messages[:-1]: # Todos menos el último
            history.append({"role": "user" if msg.role == "user" else "model", "parts": [msg.content]})

        # 3. Iniciamos el chat con memoria de Gemini
        model_name = 'models/gemini-3.1-flash-lite-preview'
        gemini_hub = genai.GenerativeModel(model_name)
        chat = gemini_hub.start_chat(history=history)

        formatted_prompt = SYSTEM_PROMPT.format(
            platform=request.platform,
            context=context if context else "No se encontraron fragmentos específicos en la DB."
        )

        full_query = f"{formatted_prompt}\n\nPREGUNTA DEL USUARIO: {last_user_message}"

        result = chat.send_message(full_query)

        return {"answer": result.text}

    except Exception as e:
        # Si falla el nombre del modelo, intentamos con el de 2026
        # Si la cuota de 3.1 falla, intentamos con 2.5 flash lite
        print(f"Fallo 3.1, intentando 2.5: {e}")
        try:
            backup_model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
            result = backup_model.generate_content(full_query)
            return {"answer": result.text}
        except Exception as e2:
            return {"answer": f"Ninja fuera de servicio: {str(e2)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
