import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from duckduckgo_search import DDGS
import ollama

app = FastAPI()

class TextoRequest(BaseModel):
    text: str

def leer_contexto_txt():
    """Lee tu archivo de memoria local (RAG artesanal)."""
    ruta = "contexto_leandro.txt"
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()
    return "Sin contexto previo cargado."

@app.post("/procesar")
async def procesar_solicitud(request: TextoRequest = None, file: UploadFile = File(None)):
    prompt_usuario = ""
    
    if request and request.text:
        prompt_usuario = request.text
    elif file:
        # Acá procesarías el archivo .ogg recibido si lo mandas al microservicio
        prompt_usuario = "Procesamiento de nota de voz recibida."

    contexto = leer_contexto_txt()
    respuesta_final = ""

    # ==========================================
    # INTENTO 1: DuckDuckGo como Inteligencia Principal
    # ==========================================
    try:
        print("🔍 Consultando a DuckDuckGo como motor principal...")
        with DDGS() as ddgs:
            resultados = [r['body'] for r in ddgs.text(prompt_usuario, max_results=3)]
            if resultados:
                respuesta_final = f"🌐 **[DDG Principal]**\n" + "\n".join(resultados)
    except Exception as e:
        print(f"⚠️ Falló DuckDuckGo principal: {str(e)}")

    # ==========================================
    # INTENTO 2: Ollama como Respaldo Local (RAG)
    # ==========================================
    if not respuesta_final:
        try:
            print("🐢 DuckDuckGo no respondió. Activando Ollama local de respaldo...")
            prompt_con_rag = f"""
[CONTEXTO Y PARÁMETROS PROPIOS]:
{contexto}

[CONSULTA ACTUAL]:
{prompt_usuario}
"""
            response = ollama.chat(
                model='llama3', # O el modelo que tengas instalado en tu Ollama local
                messages=[{'role': 'user', 'content': prompt_con_rag}]
            )
            respuesta_final = f"🏠 **[Ollama Respaldo]**\n" + response['message']['content']
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fallaron ambos motores: {str(e)}")

    return {"resultado": respuesta_final}
