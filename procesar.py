import json
import os
import re
from duckduckgo_search import DDGS
import requests


# ---------------------------------------------------------
# 1. BÚSQUEDA WEB CONDICIONAL
# ---------------------------------------------------------
def evaluar_y_buscar_web(orden):
    """Busca en DuckDuckGo si detecta intención explícita en la orden."""
    keywords = ["busc", "web", "internet", "google", "link", "repo", "url", "noticia"]
    if not any(k in orden.lower() for k in keywords):
        return ""

    print("🔍 Ejecutando búsqueda web en DuckDuckGo...")
    resultados = ""
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(orden, max_results=3))
            for r in res:
                resultados += f"- [{r.get('title', '')}]({r.get('href', '')}): {r.get('body', '')}\n"
    except Exception as e:
        print(f"⚠️ Error en DuckDuckGo: {e}")

    return f"\n\nINFORMACIÓN EXTRAÍDA DE LA WEB:\n{resultados}" if resultados else ""


# ---------------------------------------------------------
# 2. LLAMADA A OLLAMA EN HUGGING FACE SPACE (GPU)
# ---------------------------------------------------------
def llamar_ollama_gpu_space(messages, retries=3):
    """
    Se conecta al servidor de Ollama alojado en Hugging Face Spaces.
    """
    base_url = os.environ.get("OLLAMA_URL", "").strip().rstrip("/")
    if not base_url:
        print("❌ Error: No se encontró la variable OLLAMA_URL en las variables de entorno.")
        return ""

    url = f"{base_url}/api/chat"
    headers = {"Content-Type": "application/json"}

    payload = {
        "model": "llama3.2",
        "messages": messages,
        "stream": False
    }

    for intento in range(retries):
        try:
            print(f"📡 Consultando Ollama GPU Space ({url}, intento {intento + 1}/{retries})...")
            res = requests.post(url, json=payload, headers=headers, timeout=60)

            if res.status_code == 200:
                data = res.json()
                if "message" in data and "content" in data["message"]:
                    return data["message"]["content"].strip()

            print(f"⚠️ Ollama devolvió status HTTP {res.status_code}: {res.text}")

        except Exception as e:
            print(f"⚠️ Excepción al conectar con Ollama GPU Space: {e}")

    return ""


# ---------------------------------------------------------
# 3. FUNCIÓN PRINCIPAL DE GENERACIÓN
# ---------------------------------------------------------
def generar_respuesta_llm(orden, contexto_base=""):
    # 1. Búsqueda web condicional según la orden
    info_web = evaluar_y_buscar_web(orden)

    # 2. Definición del system prompt
    prompt_sistema = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "Respondé siempre en español rioplatense natural, directo y técnicamente riguroso."
    )

    if contexto_base:
        prompt_sistema += f"\n\nCONTEXTO DE ENTRADA:\n{contexto_base}"

    if info_web:
        prompt_sistema += f"\n\n{info_web}"

    messages = [
        {"role": "system", "content": prompt_sistema},
        {"role": "user", "content": orden},
    ]

    print("🧠 Generando respuesta con la IA (GPU)...")
    respuesta = llamar_ollama_gpu_space(messages)

    if not respuesta:
        print("❌ Ollama en el Space GPU no devolvió una respuesta válida.")

    return respuesta
