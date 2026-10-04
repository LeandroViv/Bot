import os
import json
import requests
from duckduckgo_search import DDGS

HISTORIAL_FILE = "historial.json"

def cargar_historial():
    if os.path.exists(HISTORIAL_FILE):
        try:
            with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_mensaje(rol, contenido):
    historial = cargar_historial()
    historial.append({"role": rol, "content": contenido})
    # Mantener últimos 20 mensajes para no saturar el contexto
    historial = historial[-20:]
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

def buscar_web(query):
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=3))
            return "\n".join([f"- {r.get('title')}: {r.get('body')}" for r in res])
    except Exception:
        return ""

def llamar_ollama(messages):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {"model": "llama3.2", "messages": messages, "stream": False}
    try:
        res = requests.post(url, json=payload, timeout=90)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Error Ollama: {e}")
    return ""

def responder_usuario(orden):
    guardar_mensaje("user", orden)
    historial = cargar_historial()
    
    # Búsqueda condicional
    info_web = ""
    keywords = ["busc", "web", "internet", "link", "noticia", "repo"]
    if any(k in orden.lower() for k in keywords):
        info_web = buscar_web(orden)

    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "Respondé siempre en español rioplatense natural, directo y técnicamente riguroso.\n"
        "Aprendé de sus preferencias e intereses a lo largo de la conversación."
    )
    if info_web:
        system_prompt += f"\n\nDATOS DE LA WEB:\n{info_web}"

    messages = [{"role": "system", "content": system_prompt}] + historial
    respuesta = llamar_ollama(messages)
    
    if respuesta:
        guardar_mensaje("assistant", respuesta)
    return respuesta

def evaluar_iniciativa_propia():
    historial = cargar_historial()
    if not historial:
        return None

    # Extraer temas de interés aprendidos de la conversación
    prompt_analisis = [
        {"role": "system", "content": "Extraé en 3 palabras clave los temas técnicos de interés de Leandro según el historial."},
        {"role": "user", "content": f"Historial reciente:\n{json.dumps(historial)}"}
    ]
    temas = llamar_ollama(prompt_analisis)
    if not temas:
        return None

    # Buscar novedades sobre esos temas
    novedades = buscar_web(temas)
    if not novedades:
        return None

    # Evaluar si realmente vale la pena molestar
    prompt_evaluacion = [
        {"role": "system", "content": (
            "Sos el filtro de criterio de Leandro Bot.\n"
            "Analizá la información encontrada. Si es de verdadero interés técnico o práctico para Leandro "
            "según lo que viene hablando con vos, redactale un mensaje breve en español rioplatense.\n"
            "Si la información es genérica, aburrida o no suma nada relevante, respondé estrictamente la palabra 'NO'."
        )},
        {"role": "user", "content": f"Intereses: {temas}\nNovedades encontradas:\n{novedades}"}
    ]
    
    criterio = llamar_ollama(prompt_evaluacion)
    if criterio and criterio.strip().upper() != "NO" and not criterio.startswith("NO"):
        guardar_mensaje("assistant", criterio)
        return criterio
    return None
