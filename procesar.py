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
    """Guarda absolutamente todo el historial en un archivo .txt plano sin borrar nada nunca."""
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")


def recuperar_contexto_de_txt(consulta, max_bloques=5):
    """
    Busca dentro de conversaciones.txt los fragmentos más relevantes 
    para la consulta actual (RAG simplificado por coincidencia semántica/palabras).
    """
    if not os.path.exists(TXT_FILE):
        return ""

    with open(TXT_FILE, "r", encoding="utf-8") as f:
        contenido = f.read()

    bloques = contenido.split("---\n")
    if not bloques:
        return ""

    # Palabras clave de la consulta actual para filtrar
    palabras_clave = [p.lower() for p in re.findall(r'\w+', consulta) if len(p) > 3]
    
    bloques_relevantes = []
    
    # 1. Priorizar siempre los últimos 3 bloques para mantener el hilo inmediato
    ultimos_bloques = [b.strip() for b in bloques if b.strip()][-3:]
    
    # 2. Buscar bloques pasados que contengan las palabras clave de la consulta
    for b in bloques:
        b_lower = b.lower()
        if any(pc in b_lower for pc in palabras_clave):
            if b.strip() not in ultimos_bloques and b.strip() not in bloques_relevantes:
                bloques_relevantes.append(b.strip())

    # Combinar coincidencias pasadas + contexto reciente
    contexto_final = bloques_relevantes[-max_bloques:] + ultimos_bloques
    return "\n\n".join(contexto_final)


def llamar_ollama(messages):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": "llama3.2",
        "messages": messages,
        "options": {
            "num_ctx": 32768  # Contexto amplio y estable
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


def generar_query_semantica(orden_usuario, contexto_txt):
    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un extractor de búsquedas semánticas. Mirá el contexto del .txt y la consulta actual "
                "para devolver de 2 a 5 palabras clave para buscar en la web.\n"
                "Devolvé SOLAMENTE las palabras clave en texto plano."
            ),
        },
        {"role": "user", "content": f"CONTEXTO RECUPERADO:\n{contexto_txt}\n\nCONSULTA: {orden_usuario}"},
    ]
    query = llamar_ollama(prompt)
    return query.replace('"', "").replace("'", "").strip() if query else orden_usuario


def buscar_web(orden_usuario, contexto_txt):
    query = generar_query_semantica(orden_usuario, contexto_txt)
    texto_resultados = ""

    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=4, backend="html"))
            for r in res:
                texto_resultados += f"• Título: {r.get('title')}\n  Detalle: {r.get('body')}\n  URL: {r.get('href')}\n\n"
            if texto_resultados:
                return texto_resultados
    except Exception as e:
        print(f"⚠️ DDGS falló: {e}")

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
    # 1. Recuperar los fragmentos del .txt relevantes + los últimos chats
    contexto_txt = recuperar_contexto_de_txt(orden)

    # 2. Buscar datos en la web si hace falta
    info_web = buscar_web(orden, contexto_txt)

    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "REGLAS:\n"
        "- Hablá SIEMPRE en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate').\n"
        "- Nutrite de los fragmentos de conversaciones pasadas recuperados del archivo .txt para responder.\n"
        "- Sé directo, conciso y técnico."
    )

    mensaje_usuario = f"CONSULTA: {orden}"
    if contexto_txt:
        mensaje_usuario += f"\n\n[FRAGMENTOS EXTRAÍDOS DEL HISTORIAL .TXT]:\n{contexto_txt}"
    if info_web:
        mensaje_usuario += f"\n\n[DATOS RECUPERADOS DE LA WEB]:\n{info_web}"

    mensajes_chat = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": mensaje_usuario}
    ]

    respuesta = llamar_ollama(mensajes_chat)

    if respuesta:
        # Guardar la interacción actual en el .txt permanente
        guardar_en_txt("usuario", orden)
        guardar_en_txt("leandro_bot", respuesta)

    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot activo y recuperando memoria desde .txt.")


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

    print("🚀 Iniciando Leandro Bot en Telegram con lectura de .txt...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.run_polling()


if __name__ == "__main__":
    main()
