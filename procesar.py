import os
import json
import requests
from bs4 import BeautifulSoup
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
    historial = historial[-20:]
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)


def llamar_ollama(messages):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {"model": "llama3.2", "messages": messages, "stream": False}
    try:
        res = requests.post(url, json=payload, timeout=90)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Error conectando con Ollama: {e}")
    return ""


def generar_query_semantica(orden_usuario):
    """Pide a Llama 3.2 que interprete el sentido humano de la orden y abstraiga los conceptos clave de búsqueda."""
    prompt = [
        {
            "role": "system",
            "content": (
                "Tu única función es extraer los conceptos semánticos principales para una búsqueda web."
                " Analizá lo que quiere saber el usuario y devolvé ÚNICAMENTE entre 2 y 4 palabras clave ideales para buscar.\n"
                "REGLAS:\n"
                "- NO incluyas palabras como 'buscame', 'que es', 'noticias', 'en la web'.\n"
                "- Respondé EXCLUSIVAMENTE con los términos clave sin comillas ni explicaciones.\n"
                "Ejemplo: 'Che buscame en la web qué onda con los llm'\n"
                "Respuesta: novedades modelos lenguaje llm"
            ),
        },
        {"role": "user", "content": orden_usuario},
    ]
    query = llamar_ollama(prompt)
    query_limpia = query.replace('"', "").replace("'", "").strip() if query else orden_usuario
    print(f"🧠 Semántica interpretada -> Query para web: '{query_limpia}'")
    return query_limpia


def buscar_web(orden_usuario):
    query = generar_query_semantica(orden_usuario)
    texto_resultados = ""

    # Intento 1: API DuckDuckGo
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=4))
            for r in res:
                texto_resultados += f"• Título: {r.get('title')}\n  Detalle: {r.get('body')}\n  URL: {r.get('href')}\n\n"
            if texto_resultados:
                return texto_resultados
    except Exception as e:
        print(f"⚠️ DDGS falló: {e}. Probando respaldo Lite...")

    # Intento 2: Fallback BeautifulSoup (DDG Lite)
    try:
        url = "https://lite.duckduckgo.com/lite/"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        res = requests.post(url, data={"q": query}, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            filas = soup.find_all("td", class_="result-snippet")
            for f in filas[:4]:
                texto_resultados += f"• {f.get_text(strip=True)}\n\n"
    except Exception as e:
        print(f"⚠️ Fallback Lite falló: {e}")

    return texto_resultados


def responder_usuario(orden):
    guardar_mensaje("user", orden)
    historial = cargar_historial()

    info_web = buscar_web(orden)

    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "Hablá en español rioplatense (usá vos, che, mirá), de forma directa, natural y técnicamente rigurosa.\n"
        "Tenés acceso directo a los datos web suministrados.\n"
        "PROHIBIDO: NUNCA digas 'sin necesidad de ir a la web' ni 'como modelo de IA no tengo acceso a internet'."
    )

    datos_reporte = (
        info_web
        if info_web
        else "No se encontraron resultados externos adicionales. Respondé usando tu conocimiento técnico."
    )

    mensaje_con_contexto = (
        f"Consulta de Leandro: {orden}\n\n"
        f"[DATOS WEB RECUPERADOS PARA ESTA CONSULTA]:\n"
        f"{datos_reporte}\n\n"
        f"Instrucción: Respondé a Leandro usando los datos web recuperados."
    )

    mensajes_chat = [{"role": "system", "content": system_prompt}]
    for m in historial[:-1]:
        mensajes_chat.append(m)

    mensajes_chat.append({"role": "user", "content": mensaje_con_contexto})

    respuesta = llamar_ollama(mensajes_chat)

    if respuesta:
        guardar_mensaje("assistant", respuesta)
    return respuesta


def evaluar_iniciativa_propia():
    historial = cargar_historial()
    if not historial:
        return None

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

    prompt_evaluacion = [
        {"role": "system", "content": (
            "Sos el filtro de relevancia de Leandro Bot.\n"
            "Analizá la información encontrada. Si hay alguna novedad técnica de ALTO VALOR para Leandro, "
            "redactale un mensaje breve y directo en español rioplatense.\n"
            "Si la información es común o vacía, tu única respuesta debe ser la palabra: NO"
        )},
        {"role": "user", "content": f"Temas de Leandro: {temas}\nResultados web:\n{novedades}"}
    ]

    criterio = llamar_ollama(prompt_evaluacion)
    if criterio and not criterio.strip().startswith("NO") and len(criterio) > 10:
        guardar_mensaje("assistant", criterio)
        return criterio
    return None
