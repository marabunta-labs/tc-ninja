import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from dotenv import load_dotenv
from typing import List, Dict
from fastapi.responses import StreamingResponse
import asyncio
import urllib.parse

from prompts import SYSTEM_PROMPT, DECISION_PROMPT

load_dotenv()

app = FastAPI(title="T&C Ninja API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción pondrás tu URL de Vercel
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializaciones
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
model = SentenceTransformer("all-MiniLM-L6-v2")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    platforms: List[str]  # Cambiado de 'platform' a 'platforms'
    messages: List[Message]
    mode: str = "explicacion"


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
            context_message = f"🔄 Cambiando el contexto: Añadiendo {', '.join(added)} y eliminando {', '.join(removed)}."
        elif added:
            context_message = f"🔄 Cambiando el contexto: Añadiendo {', '.join(added)}."
        elif removed:
            context_message = (
                f"🔄 Cambiando el contexto: Enfocando en {', '.join(final_platforms)}."
            )

    return {"platforms": final_platforms, "message": context_message}


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
            "match_threshold": 0.05,  # Bajamos un poco el umbral para ser más flexibles
            "match_count": 8,  # Traemos 8 fragmentos de CADA una
            "filter_platforms": [
                p
            ],  # Filtramos solo por esta plataforma en esta vuelta
        }
        response = supabase.rpc("match_documents", rpc_params).execute()

        if response.data:
            context_sections[p] = []
            for doc in response.data:
                # Extraemos los metadatos de forma segura (por si hay documentos viejos sin ellos)
                metadata = doc.get("metadata", {})
                url = metadata.get("source_url", "URL no disponible")
                fecha = metadata.get("fetch_date", "Fecha desconocida")

                # Guardamos un diccionario con todo
                context_sections[p].append(
                    {"content": doc["content"], "url": url, "fecha": fecha}
                )

    # Construimos el contexto formateado
    # Construimos el texto formateado que leerá Gemini
    context_formatted = ""
    for p, chunks in context_sections.items():
        context_formatted += f"--- DATOS DE {p.upper()} ---\n"
        for chunk_data in chunks:
            # 1. Limpiamos la URL (quitamos Jina para enviar al usuario a la web real)
            url_real = chunk_data["url"].replace("https://r.jina.ai/", "")

            # 2. Cogemos las primeras 6-7 palabras del fragmento para que el navegador lo busque
            # Separamos por espacios, cogemos las 7 primeras y las volvemos a unir
            palabras = chunk_data["content"].split()
            snippet_busqueda = " ".join(palabras[:7])

            # 3. Codificamos el texto para que sea una URL válida (cambia espacios por %20, etc.)
            texto_codificado = urllib.parse.quote(snippet_busqueda)

            # 4. Creamos el link exacto usando el estándar de Text Fragments
            link_exacto = f"{url_real}#:~:text={texto_codificado}"

            # 5. Se lo pasamos a Gemini
            context_formatted += f"[Fuente: {link_exacto} | Extraído: {chunk_data['fecha']}]\n{chunk_data['content']}\n\n"

    if not context_formatted:
        context_formatted = "No se encontraron fragmentos específicos para las plataformas seleccionadas."
    # 4. Llamada a Gemini con Streaming
    try:
        platforms_str = " y ".join(final_platforms)

        history = []
        for msg in request.messages[:-1]:
            if msg.role != "system":
                history.append(
                    {
                        "role": "user" if msg.role == "user" else "model",
                        "parts": [msg.content],
                    }
                )

        model_name = "models/gemini-3.1-flash-lite-preview"
        gemini_hub = genai.GenerativeModel(model_name)
        chat = gemini_hub.start_chat(history=history)

        from prompts import MODE_INSTRUCTIONS # Asegúrate de importarlo arriba
        mode_instruction = MODE_INSTRUCTIONS.get(request.mode, MODE_INSTRUCTIONS["explicacion"])

        formatted_prompt = SYSTEM_PROMPT.format(
            platform=platforms_str, 
            context=context_formatted,
            mode_instructions=mode_instruction # Inyectamos la personalidad aquí
        )

        full_query = f"{formatted_prompt}\n\nPREGUNTA DEL USUARIO: {last_user_message}"

        # ¡EL SECRETO ESTÁ AQUÍ! Usamos 'await' y 'send_message_async'
        response = await chat.send_message_async(full_query, stream=True)

        async def generador_stream():
            try:
                # Usamos 'async for' para ir recibiendo los datos sin bloquear el servidor
                async for chunk in response:
                    if chunk.text:
                        for letra in chunk.text:
                            yield letra
                            # Retraso casi imperceptible (1 milisegundo) para mantener la fluidez sin atascar
                            await asyncio.sleep(0.001)
            except Exception as e:
                yield f"\n\n[Error de redacción: {str(e)}]"

        return StreamingResponse(generador_stream(), media_type="text/plain")

    except Exception as e:
        mensaje_error = str(e)
        
        # 2. Hacemos el generador asíncrono y usamos nuestra nueva variable
        async def error_gen():
            yield f"Ninja fuera de servicio: {mensaje_error}"
            
        return StreamingResponse(error_gen(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
