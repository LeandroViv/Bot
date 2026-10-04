import os
import json
import re
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TXT_FILE = "conversaciones.txt"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


def guardar_en_txt(rol, texto):
    """Guarda el historial en un archivo .txt plano sin límites de retención."""
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")


def llamar_ollama(messages, timeout_secs=300):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": "llama3.2",
        "messages": messages,
        "options": {
            "num_ctx": 16384,
            "temperature": 0.7
        },
        "stream": False,
    }
    try:
        res = requests.post(url, json=payload, timeout=timeout_secs)
        if res.status_code == 200:
            contenido = res.json().get("message", {}).get("content", "").strip()
            if contenido:
                return contenido
    except Exception as e:
        print(f"⚠️ Error conectando con Ollama: {e}")

    # Reintento directo en caso de fallo momentáneo
    try:
        print("🔄 Reintentando llamada a Ollama...")
        res = requests.post(url, json=payload, timeout=timeout_secs)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Falló el reintento con Ollama: {e}")

    return ""


def extraer_conceptos_semanticos(consulta):
    """
    Expande la consulta del usuario a términos conceptuales y sinónimos 
    para buscar por sentido en todo el .txt.
    """
    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un extractor de conceptos semánticos. Dado el mensaje de un usuario, generá una lista "
                "de 5 a 10 palabras o conceptos clave relacionados (incluyendo sinónimos, categorías o términos afines) "
                "para buscar por sentido en un historial de chat.\n"
                "Devolvé SOLAMENTE los términos separados por comas, sin explicaciones."
            ),
        },
        {"role": "user", "content": f"Mensaje del usuario: {consulta}"},
    ]
    respuesta = llamar_ollama(prompt, timeout_secs=120)
    if respuesta:
        conceptos = [c.strip().lower() for c in respuesta.replace("\n", "").split(",") if len(c.strip()) > 2]
        print(f"🔍 Conceptos semánticos expandidos -> {conceptos}")
        return conceptos
    
    return [p.lower() for p in re.findall(r'\w+', consulta) if len(p) > 3]


def recuperar_contexto_de_txt(consulta, max_bloques=6):
    """
    Escanea TODO el archivo conversaciones.txt sin importar su antigüedad,
    evitando duplicados y recuperando bloques con alta relevancia semántica.
    """
    if not os.path.exists(TXT_FILE):
        return ""

    with open(TXT_FILE, "r", encoding="utf-8") as f:
        contenido = f.read()

    bloques = contenido.split("---\n")
    bloques_validos = [b.strip() for b in bloques if b.strip()]
    if not bloques_validos:
        return ""

    conceptos = extraer_conceptos_semanticos(consulta)
    if not conceptos:
        return ""

    bloques_puntuados = []
    for b in bloques_validos:
        b_lower = b.lower()
        coincidencias = sum(1 for c in conceptos if c in b_lower)
        if coincidencias > 0:
            bloques_puntuados.append((coincidencias, b))

    # Ordenar por máxima coincidencia conceptual
    bloques_puntuados.sort(key=lambda x: x[0], reverse=True)

    # Filtrar duplicados
    top_bloques = []
    vistos = set()
    for _, b in bloques_puntuados:
        if b not in vistos:
            top_bloques.append(b)
            vistos.add(b)
        if len(top_bloques) >= max_bloques:
            break

    return "\n\n".join(top_bloques)


def generar_query_semantica(orden_usuario):
    """
    Lee el historial COMPLETO para resolver 'eso', 'aquello' o referencias pasadas.
    """
    historial_completo = ""
    if os.path.exists(TXT_FILE):
        with open(TXT_FILE, "r", encoding="utf-8") as f:
            historial_completo = f.read()

    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un extractor de búsquedas semánticas. Tu trabajo es analizar TODO el historial de la conversación "
                "en texto plano y la consulta actual para devolver de 2 a 5 palabras clave de búsqueda para Google/DuckDuckGo.\n"
                "REGLAS STRICTAS:\n"
                "1. Escaneá todo el historial pasado para entender a qué se refiere el usuario por el sentido de sus palabras ('eso', 'aquello', 'de nuevo', 'gratis', etc.).\n"
                "2. NO incluyas comandos como 'buscame', 'dame', 'links'.\n"
                "3. Devolvé SOLAMENTE los términos de búsqueda en texto plano."
            ),
        },
        {
            "role": "user",
            "content": f"HISTORIAL COMPLETO DEL .TXT:\n{historial_completo}\n\nCONSULTA ACTUAL: {orden_usuario}",
        },
    ]
    query = llamar_ollama(prompt, timeout_secs=120)
    query_limpia = query.replace('"', "").replace("'", "").strip() if query else orden_usuario
    print(f"🧠 Búsqueda web semántica sobre TODO el .txt -> '{query_limpia}'")
    return query_limpia


def buscar_web(orden_usuario):
    query = generar_query_semantica(orden_usuario)
    texto_resultados = ""

    # Intento 1: DDGS HTML
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=4, backend="html"))
            for r in res:
                texto_resultados += f"• Título: {r.get('title')}\n  Detalle: {r.get('body')}\n  URL: {r.get('href')}\n\n"
            if texto_resultados:
                return texto_resultados
    except Exception as e:
        print(f"⚠️ DDGS falló: {e}")

    # Intento 2: Fallback DDG Lite
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
    contexto_txt = recuperar_contexto_de_txt(orden)
    info_web = buscar_web(orden)

    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "REGLAS:\n"
        "- Hablá SIEMPRE en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate').\n"
        "- Nutrite de los fragmentos de conversaciones pasadas recuperados semánticamente por sentido del archivo .txt para responder.\n"
        "- Sé directo, conciso y técnico. Evitá repetir introducciones o volver a decir exactamente lo mismo que en mensajes anteriores."
    )

    mensaje_usuario = f"CONSULTA: {orden}"
    if contexto_txt:
        mensaje_usuario += f"\n\n[FRAGMENTOS EXTRAÍDOS POR SENTIDO/CONCEPTO DEL HISTORIAL .TXT]:\n{contexto_txt}"
    if info_web:
        mensaje_usuario += f"\n\n[DATOS RECUPERADOS DE LA WEB]:\n{info_web}"

    mensajes_chat = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": mensaje_usuario},
    ]

    respuesta = llamar_ollama(mensajes_chat, timeout_secs=300)

    if respuesta:
        guardar_en_txt("usuario", orden)
        guardar_en_txt("leandro_bot", respuesta)

    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot activo y listo.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")
    
    respuesta = responder_usuario(texto_usuario)
    if not respuesta:
        respuesta = "Che, la consulta demoró en responder, pero ya quedé listo para la siguiente."

    await update.message.reply_text(respuesta)


def main():
    if not TOKEN:
        print("❌ ERROR: No se encontró TELEGRAM_BOT_TOKEN.")
        return

    # Limpieza previa del webhook de Telegram
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
        print("🧹 Webhook previo eliminado correctamente.")
    except Exception as e:
        print(f"⚠️ No se pudo eliminar el webhook: {e}")

    print("🚀 Iniciando Leandro Bot en Telegram...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.run_polling()


if __name__ == "__main__":
    main()
