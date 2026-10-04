import os
import json
import re
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TXT_FILE = "conversaciones.txt"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


def guardar_en_txt(rol, texto):
    """Guarda todo el historial en un archivo .txt plano de forma indefinida."""
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")


def llamar_ollama(messages):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": "llama3.2",
        "messages": messages,
        "options": {
            "num_ctx": 32768
        },
        "stream": False,
    }
    try:
        res = requests.post(url, json=payload, timeout=90)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Error conectando con Ollama: {e}")
    return ""


def extraer_conceptos_semanticos(consulta):
    """
    Expande la consulta del usuario a términos conceptuales, sinónimos y temas relacionados
    para poder hacer match por sentido dentro del .txt.
    """
    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un extractor de conceptos semánticos. Dado el mensaje de un usuario, generá una lista "
                "de 5 a 10 palabras o conceptos clave relacionados (incluyendo sinónimos, nombres propios, "
                "categorías o términos afines) para buscar por sentido en un historial de chat.\n"
                "Devolvé SOLAMENTE los términos separados por comas, sin explicaciones."
            ),
        },
        {"role": "user", "content": f"Mensaje del usuario: {consulta}"},
    ]
    respuesta = llamar_ollama(prompt)
    if respuesta:
        conceptos = [c.strip().lower() for c in respuesta.replace("\n", "").split(",") if len(c.strip()) > 2]
        print(f"🔍 Conceptos semánticos expandidos -> {conceptos}")
        return conceptos
    
    # Fallback básico si Ollama no responde la expansión
    return [p.lower() for p in re.findall(r'\w+', consulta) if len(p) > 3]


def recuperar_contexto_de_txt(consulta, max_bloques=8):
    """
    Busca dentro de TODO conversaciones.txt los fragmentos con mayor relevancia por sentido/concepto,
    sin importar si usan exactamente las mismas palabras o cuán viejos sean.
    """
    if not os.path.exists(TXT_FILE):
        return ""

    with open(TXT_FILE, "r", encoding="utf-8") as f:
        contenido = f.read()

    bloques = contenido.split("---\n")
    bloques_validos = [b.strip() for b in bloques if b.strip()]
    if not bloques_validos:
        return ""

    # 1. Obtener conceptos y sinónimos vía Ollama
    conceptos = extraer_conceptos_semanticos(consulta)

    if not conceptos:
        return ""

    # 2. Puntuar cada bloque de TODO el archivo según la presencia de esos conceptos
    bloques_puntuados = []
    for b in bloques_validos:
        b_lower = b.lower()
        coincidencias = sum(1 for c in conceptos if c in b_lower)
        if coincidencias > 0:
            bloques_puntuados.append((coincidencias, b))

    # Ordenar por relevancia conceptual
    bloques_puntuados.sort(key=lambda x: x[0], reverse=True)

    # Extraer los bloques más afines al sentido de la consulta
    top_bloques = [b[1] for b in bloques_puntuados[:max_bloques]]

    return "\n\n".join(top_bloques)


def generar_query_semantica(orden_usuario):
    """Lee el archivo .txt COMPLETO para resolver pronombres e indirectas en búsquedas web."""
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
    query = llamar_ollama(prompt)
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
    # Recuperación semántica por sentido
    contexto_txt = recuperar_contexto_de_txt(orden)
    info_web = buscar_web(orden)

    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "REGLAS:\n"
        "- Hablá SIEMPRE en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate').\n"
        "- Nutrite de los fragmentos de conversaciones pasadas recuperados semánticamente por sentido del archivo .txt para responder.\n"
        "- Sé directo, conciso y técnico."
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

    respuesta = llamar_ollama(mensajes_chat)

    if respuesta:
        guardar_en_txt("usuario", orden)
        guardar_en_txt("leandro_bot", respuesta)

    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot activo con búsqueda conceptual y de sentido en el .txt.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")
    
    respuesta = responder_usuario(texto_usuario)
    if not respuesta:
        respuesta = "Che, se me complicó la respuesta con Ollama, pero acá sigo activo."

    await update.message.reply_text(respuesta)


def main():
    if not TOKEN:
        print("❌ ERROR: No se encontró TELEGRAM_BOT_TOKEN.")
        return

    print("🚀 Iniciando Leandro Bot en Telegram...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.run_polling()


if __name__ == "__main__":
    main()
