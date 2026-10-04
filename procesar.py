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
    historial = historial[-20:] # Mantiene los últimos 20 mensajes
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

def buscar_web(query):
    print(f"🔍 Buscando en la web: '{query}'...")
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=4))
            if res:
                texto_resultados = ""
                for r in res:
                    texto_resultados += f"• Título: {r.get('title')}\n  Detalle: {r.get('body')}\n  URL: {r.get('href')}\n\n"
                return texto_resultados
    except Exception as e:
        print(f"⚠️ Error al buscar en DuckDuckGo: {e}")
    return ""

def llamar_ollama(messages):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {"model": "llama3.2", "messages": messages, "stream": False}
    try:
        res = requests.post(url, json=payload, timeout=90)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Error conectando con Ollama local: {e}")
    return ""

def responder_usuario(orden):
    guardar_mensaje("user", orden)
    historial = cargar_historial()
    
    # 1. Búsqueda web automática
    info_web = buscar_web(orden)

    # 2. Prompt del sistema estricto
    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "Hablá siempre en español rioplatense, de forma directa, natural y técnicamente rigurosa.\n"
        "NUNCA digas que no tenés acceso a internet ni hables de cortes de entrenamiento.\n"
    )

    if info_web:
        system_prompt += (
            "\n\n[INFORMACIÓN DE BÚSQUEDA EN TIEMPO REAL]\n"
            f"{info_web}\n"
            "INSTRUCCIÓN: Usá OBLIGATORIAMENTE los datos de búsqueda de arriba para responder la consulta de Leandro con precisión y enlaces si corresponden."
        )
    else:
        system_prompt += "\nSi no hay resultados web, respondé directamente con tus conocimientos sin dar excusas sobre internet."

    messages = [{"role": "system", "content": system_prompt}] + historial
    respuesta = llamar_ollama(messages)
    
    if respuesta:
        guardar_mensaje("assistant", respuesta)
    return respuesta

def evaluar_iniciativa_propia():
    historial = cargar_historial()
    if not historial:
        return None

    # Extraer temas clave hablados recientemente
    prompt_analisis = [
        {"role": "system", "content": "Extraé de forma concisa los temas técnicos o proyectos de interés de Leandro según el historial."},
        {"role": "user", "content": f"Historial:\n{json.dumps(historial)}"}
    ]
    temas = llamar_ollama(prompt_analisis)
    if not temas:
        return None

    novedades = buscar_web(f"novedades {temas}")
    if not novedades:
        return None

    # Evaluar relevancia real
    prompt_evaluacion = [
        {"role": "system", "content": (
            "Sos el filtro de relevancia de Leandro Bot.\n"
            "Analizá la información encontrada en la web. Si hay alguna novedad técnica, actualización o dato de ALTO VALOR para Leandro "
            "según sus proyectos e intereses, redactale un mensaje breve y directo en español rioplatense.\n"
            "Si la información es común, irrelevante o vacía, tu única respuesta debe ser la palabra: NO"
        )},
        {"role": "user", "content": f"Temas de Leandro: {temas}\nResultados web:\n{novedades}"}
    ]
    
    criterio = llamar_ollama(prompt_evaluacion)
    if criterio and not criterio.strip().startswith("NO") and len(criterio) > 10:
        guardar_mensaje("assistant", criterio)
        return criterio
    return None
