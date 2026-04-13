import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from dotenv import load_dotenv
from typing import List, Dict

from prompts import SYSTEM_PROMPT, DECISION_PROMPT

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
    platforms: List[str]  # Cambiado de 'platform' a 'platforms'
    messages: List[Message]
    
class DetectRequest(BaseModel):
    message: str
    current_platforms: List[str]

def detectar_plataformas(pregunta: str, plataformas_actuales: List[str]) -> List[str]:
    # Le pasamos también la cantidad de plataformas actuales para que pueda tomar la decisión
    clasificador_prompt = DECISION_PROMPT.format(pregunta=pregunta, plataformas_actuales=plataformas_actuales)
    
    model_lite = genai.GenerativeModel('models/gemini-3.1-flash-lite-preview')
    response = model_lite.generate_content(clasificador_prompt)
    
    resultado = response.text.strip()
    
    detecciones = [p.strip() for p in resultado.split(",")]
    return [p for p in detecciones if p in ["Instagram", "TikTok", "X-Twitter"]]

@app.post("/detect-context")
async def detect_context(request: DetectRequest):
    auto_detected = detectar_plataformas(request.message, request.current_platforms)
    
    context_message = None
    final_platforms = request.current_platforms

    if auto_detected:
        final_platforms = auto_detected
        added = [p for p in final_platforms if p not in request.current_platforms]
        removed = [p for p in request.current_platforms if p not in final_platforms]
        
        if added and removed:
            context_message = f"🔄 Cambiando el contexto: Añadiendo {', '.join(final_platforms)}."
        elif added:
            context_message = f"🔄 Cambiando el contexto: Añadiendo {', '.join(added)}."
        elif removed:
            context_message = f"🔄 Cambiando el contexto: Enfocando en {', '.join(final_platforms)}."
    
    return {
        "platforms": final_platforms,
        "message": context_message
    }

# 2. ENDPOINT MODIFICADO: Ya no detecta, solo busca y responde
@app.post("/ask")
async def ask_ninja(request: ChatRequest):
    last_user_message = request.messages[-1].content
    query_vector = model.encode(last_user_message).tolist()
    
    # Ahora confiamos ciegamente en las plataformas que manda el frontend
    final_platforms = request.platforms
    # 1. Búsqueda en Supabase
    context_sections = {}
    
    # Buscamos de forma independiente para cada plataforma seleccionada
    for p in final_platforms:
        rpc_params = {
            "query_embedding": query_vector,
            "match_threshold": 0.05, # Bajamos un poco el umbral para ser más flexibles
            "match_count": 8,        # Traemos 8 fragmentos de CADA una
            "filter_platforms": [p]  # Filtramos solo por esta plataforma en esta vuelta
        }
        response = supabase.rpc("match_documents", rpc_params).execute()
        
        if response.data:
            context_sections[p] = [doc['content'] for doc in response.data]

    # Construimos el contexto formateado
    context_formatted = ""
    for p, chunks in context_sections.items():
        context_formatted += f"--- DATOS DE {p.upper()} ---\n"
        context_formatted += "\n".join(chunks) + "\n\n"

    if not context_formatted:
        context_formatted = "No se encontraron fragmentos específicos para las plataformas seleccionadas."

    try:
        # Formateamos los nombres de las plataformas para el prompt (ej: "Instagram y TikTok")
        platforms_str = " y ".join(request.platforms)
        
        history = []
        for msg in request.messages[:-1]:
            history.append({"role": "user" if msg.role == "user" else "model", "parts": [msg.content]})

        model_name = 'models/gemini-3.1-flash-lite-preview'
        gemini_hub = genai.GenerativeModel(model_name)
        chat = gemini_hub.start_chat(history=history)

        # Inyectamos las plataformas y el contexto agrupado
        formatted_prompt = SYSTEM_PROMPT.format(
            platform=platforms_str,
            context=context_formatted
        )

        full_query = f"{formatted_prompt}\n\nPREGUNTA DEL USUARIO: {last_user_message}"
        result = chat.send_message(full_query)

        return {
            "answer": result.text
        }
        
    except Exception as e:
        # Si falla el nombre del modelo, intentamos con el de 2026
        # Si la cuota de 3.1 falla, intentamos con 2.5 flash lite
        print(f"Fallo 3.1, intentando 2.5: {e}")
        try:
            backup_model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
            result = backup_model.generate_content(full_query)
            return {
                "answer": result.text
            }
        except Exception as e2:
            return {"answer": f"Ninja fuera de servicio: {str(e2)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
