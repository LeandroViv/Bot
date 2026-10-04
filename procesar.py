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
    historial = historial[-20:]  # Mantener los últimos 20 mensajes
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


def generar_query_semantica(orden_usuario, historial):
    """Analiza la consulta actual JUNTO al historial para resolver referencias implícitas (ej: 'de eso', 'lo último')."""
    
    # Extraer contexto reciente (últimos 3 mensajes)
    contexto_reciente = ""
    for msg in historial[-3:]:
        rol = "Usuario" if msg["role"] == "user" else "Asistente"
        contexto_reciente += f"{rol}: {msg['content']}\n"

    prompt = [
        {
            "role": "system",
            "content": (
                "Tu función es generar entre 2 y 4 palabras clave para buscar en la web.\n"
                "IMPORTANTE: Tené en cuenta el hilo de la conversación previa para resolver pronombres como 'eso', 'aquello', 'de nuevo', etc.\n"
                "REGLAS:\n"
                "- NO incluyas palabras como 'buscame', 'dame', 'links', 'noticias'.\n"
                "- Devolvé ÚNICAMENTE las palabras clave para buscar, sin comillas ni aclaraciones."
            ),
        },
        {"role": "user", "content": f"Historial reciente:\n{contexto_reciente}\nConsulta actual: {orden_usuario}"},
    ]
    query = llamar_ollama(prompt)
    query_limpia = query.replace('"', "").replace("'", "").strip() if query else orden_usuario
    print(f"🧠 Semántica interpretada -> Query para web: '{query_limpia}'")
    return query_limpia


def buscar_web(orden_usuario, historial):
    query = generar_query_semantica(orden_usuario, historial)
    texto_resultados = ""

    # Intento 1: API DuckDuckGo HTML
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=4, backend="html"))
            for r in res:
                texto_resultados += f"• Título: {r.get('title')}\n  Detalle: {r.get('body')}\n  URL: {r.get('href')}\n\n"
            if texto_resultados:
                return texto_resultados
    except Exception as e:
        print(f"⚠️ DDGS falló: {e}. Probando respaldo Lite...")

    # Intento 2: Fallback BeautifulSoup (DDG Lite)
    try:
        url = "https://lite.duckduckgo.com/lite/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.post(url, data={"q": query}, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            filas = soup.find_all("td", class_="result-snippet")
            for f in filas[:4]:
                texto_resultados += f"• {f.get_text(strip=True)}\n\n"
            if texto_resultados:
                return texto_resultados
    except Exception as e:
        print(f"⚠️ Fallback Lite falló: {e}")

    return texto_resultados


def responder_usuario(orden):
    historial = cargar_historial()
    
    # 1. Buscar web usando la orden actual + el contexto previo
    info_web = buscar_web(orden, historial)

    # 2. Guardar el mensaje actual del usuario en la memoria
    guardar_mensaje("user", orden)

    if info_web:
        reporte_contexto = f"[DATOS COMPLEMENTARIOS RECUPERADOS DE LA WEB EN TIEMPO REAL]:\n{info_web}"
    else:
        reporte_contexto = "[SISTEMA]: No se requirieron o no se obtuvieron resultados externos adicionales. Usá la información del historial y tu base técnica."

    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "REGLAS OBLIGATORIAS:\n"
        "- Hablá SIEMPRE en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate').\n"
        "- MANTENÉ LA CONTINUIDAD: Tenés pleno acceso al historial de la charla. Cuando el usuario hable de 'eso' o de un tema anterior, referite al contexto previo.\n"
        "- PROHIBIDO DECIR: 'no tengo acceso a internet', 'como modelo de IA' o 'dame más contexto' si la referencia está en el historial.\n"
        "- Sé directo, directo al grano y técnicamente preciso."
    )

    # 3. Armar la estructura del chat respetando la alternancia natural del historial
    mensajes_chat = [{"role": "system", "content": system_prompt}]
    
    # Cargar todo el historial acumulado
    for m in historial:
        mensajes_chat.append(m)

    # Inyectar el bloque de datos de la web directamente en la última instrucción
    mensaje_final = (
        f"{orden}\n\n"
        f"{reporte_contexto}\n\n"
        f"Instrucción: Respondé considerando todo nuestro historial previo y los datos web si aplican."
    )
    
    # Reemplazar el contenido del último mensaje del usuario para incluir los datos web sin romper el rol
    mensajes_chat[-1]["content"] = mensaje_final

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

    novedades = buscar_web(f"novedades {temas}", historial)
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
