import os
import json
import time
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

HISTORIAL_FILE = "historial.json"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


def cargar_historial():
    if os.path.exists(HISTORIAL_FILE):
        try:
            with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def guardar_historial(historial):
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(historial[-20:], f, ensure_ascii=False, indent=2)


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
    contexto = ""
    for msg in historial[-4:]:
        rol = "Usuario" if msg["role"] == "user" else "Asistente"
        texto = msg['content'][:250].replace('\n', ' ')
        contexto += f"{rol}: {texto}\n"

    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un extractor de búsquedas semánticas. Tu único trabajo es responder con 2 a 5 palabras clave "
                "para buscar en Google/DuckDuckGo.\n"
                "REGLAS STRICTAS:\n"
                "1. Mirá el historial para entender a qué se refiere el usuario con palabras como 'eso', 'aquello', 'de nuevo', 'gratis', etc.\n"
                "2. NO incluyas comandos como 'buscame', 'dame', 'links'.\n"
                "3. Devolvé SOLAMENTE los términos de búsqueda en texto plano."
            ),
        },
        {"role": "user", "content": f"HISTORIAL:\n{contexto}\nCONSULTA ACTUAL: {orden_usuario}"},
    ]
    query = llamar_ollama(prompt)
    query_limpia = query.replace('"', "").replace("'", "").strip() if query else orden_usuario
    print(f"🧠 Búsqueda semántica generada -> '{query_limpia}'")
    return query_limpia


def buscar_web(orden_usuario, historial):
    query = generar_query_semantica(orden_usuario, historial)
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
    historial = cargar_historial()
    info_web = buscar_web(orden, historial)

    system_prompt = {
        "role": "system",
        "content": (
            "Sos Leandro Bot, el asistente personal de Leandro.\n"
            "REGLAS FUNDAMENTALES:\n"
            "- Hablá SIEMPRE en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate').\n"
            "- CONTINUIDAD: Tenés pleno acceso a los mensajes anteriores en la conversación. Si el usuario pregunta por 'eso', 'aquello' o 'gratis', respondé basándote en lo que hablaron recién.\n"
            "- NUNCA digas '¿sobre qué tema buscas?' o 'dame contexto' si el tema ya fue mencionado previamente en el historial.\n"
            "- Sé directo, conciso y técnico."
        )
    }

    mensajes_chat = [system_prompt]
    for msg in historial:
        mensajes_chat.append(msg)

    contenido_actual = orden
    if info_web:
        contenido_actual += f"\n\n[DATOS RECUPERADOS EN TIEMPO REAL PARA ESTA CONSULTA]:\n{info_web}"
    
    mensajes_chat.append({"role": "user", "content": contenido_actual})

    respuesta = llamar_ollama(mensajes_chat)

    if respuesta:
        historial.append({"role": "user", "content": orden})
        historial.append({"role": "assistant", "content": respuesta})
        guardar_historial(historial)

    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Acá Leandro Bot activo y listo. Decime en qué andamos.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje recibido: {texto_usuario}")
    
    # Indicar que está procesando
    await update.message.chat.send_action(action="typing")
    
    respuesta = responder_usuario(texto_usuario)
    if not respuesta:
        respuesta = "Che, se me complicó la respuesta con Ollama, pero acá sigo activo."

    await update.message.reply_text(respuesta)


def main():
    if not TOKEN:
        print("❌ ERROR: No se encontró TELEGRAM_BOT_TOKEN en las variables de entorno.")
        return

    print("🚀 Iniciando Leandro Bot en Telegram...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    app.run_polling()


if __name__ == "__main__":
    main()
