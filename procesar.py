import json
import os
import re
import subprocess
from bs4 import BeautifulSoup
from ddgs import DDGS
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import whisper

TXT_FILE = "conversaciones.txt"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Cargamos el modelo de Whisper ('base' corre rápido en el runner y reconoce muy bien)
print("🎙️ Cargando modelo Whisper...")
modelo_whisper = whisper.load_model("base")


def sincronizar_txt_con_github():
    """Hace commit y push automático del conversaciones.txt al repositorio."""
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        
        subprocess.run(["git", "add", TXT_FILE], check=True)
        resultado = subprocess.run(["git", "commit", "-m", "🤖 Actualización automática de conversaciones.txt"], capture_output=True, text=True)
        
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ conversaciones.txt sincronizado con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ No se pudo sincronizar el .txt con GitHub: {e}")


def guardar_en_txt(rol, texto):
    """Guarda el historial en un archivo .txt plano y lo sube a GitHub."""
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")
    
    sincronizar_txt_con_github()


def exportar_dataset_actualizado():
    """Genera/actualiza dataset.jsonl cada vez que hay nuevos datos."""
    try:
        from exportar_dataset import generar_y_subir_dataset
        generar_y_subir_dataset()
    except Exception as e:
        print(f"⚠️ No se pudo exportar el dataset: {e}")


def llamar_ollama(messages, timeout_secs=300):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": "llama3.2",
        "messages": messages,
        "options": {"num_ctx": 16384, "temperature": 0.7},
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

    try:
        print("🔄 Reintentando llamada a Ollama...")
        res = requests.post(url, json=payload, timeout=timeout_secs)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Falló el reintento con Ollama: {e}")

    return ""


def requiere_busqueda_web(consulta):
    prompt = [
        {
            "role": "system",
            "content": (
                "Analizá la consulta del usuario. Si requiere datos en vivo, "
                "fechas recientes, enlaces, noticias, especificaciones "
                "técnicas de terceros o búsquedas externas, respondé 'SI'. Si "
                "es charla casual, opinión, instrucciones de control, gracias o "
                "conversación fluida, respondé 'NO'. Devolvé SOLAMENTE 'SI' o 'NO'."
            ),
        },
        {"role": "user", "content": consulta},
    ]
    res = llamar_ollama(prompt, timeout_secs=60)
    return "SI" in res.upper() if res else False


def extraer_conceptos_semanticos(consulta):
    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un extractor de conceptos semánticos. Dado el mensaje de un "
                "usuario, generá una lista de 5 a 10 palabras clave "
                "(incluyendo sinónimos) para buscar por sentido en el historial.\n"
                "Devolvé SOLAMENTE los términos separados por comas, sin explicaciones."
            ),
        },
        {"role": "user", "content": f"Mensaje del usuario: {consulta}"},
    ]
    respuesta = llamar_ollama(prompt, timeout_secs=120)
    if respuesta:
        return [
            c.strip().lower()
            for c in respuesta.replace("\n", "").split(",")
            if len(c.strip()) > 2
        ]
    return [p.lower() for p in re.findall(r"\w+", consulta) if len(p) > 3]


def recuperar_contexto_de_txt(consulta, max_bloques=6):
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

    bloques_puntuados.sort(key=lambda x: x[0], reverse=True)

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
    historial_completo = ""
    if os.path.exists(TXT_FILE):
        with open(TXT_FILE, "r", encoding="utf-8") as f:
            historial_completo = f.read()

    prompt = [
        {
            "role": "system",
            "content": (
                "Analizá el historial y la consulta para devolver de 2 a 5 "
                "palabras clave de búsqueda web. Devolvé SOLAMENTE los términos en texto plano."
            ),
        },
        {
            "role": "user",
            "content": f"HISTORIAL:\n{historial_completo}\n\nCONSULTA: {orden_usuario}",
        },
    ]
    query = llamar_ollama(prompt, timeout_secs=120)
    return query.replace('"', "").replace("'", "").strip() if query else orden_usuario


def buscar_web(orden_usuario):
    if not requiere_busqueda_web(orden_usuario):
        print("⏭️ Búsqueda web omitida (conversación general / control).")
        return ""

    query = generar_query_semantica(orden_usuario)
    texto_resultados = ""

    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(query, max_results=4, backend="html"))
            for r in res:
                texto_resultados += (
                    f"• Título: {r.get('title')}\n  Detalle: {r.get('body')}\n  URL: {r.get('href')}\n\n"
                )
            if texto_resultados:
                return texto_resultados
    except Exception as e:
        print(f"⚠ DDGS falló: {e}")

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
        "- Nutrite de los fragmentos recuperados del archivo .txt para mantener coherencia.\n"
        "- Sé directo, conciso y técnico. Si el usuario te pide una tarea "
        "programada o de fondo que no podés ejecutar por ti solo, aclaraselo con precisión."
    )

    mensaje_usuario = f"CONSULTA: {orden}"
    if contexto_txt:
        mensaje_usuario += f"\n\n[CONTEXTO PREVIO DEL HISTORIAL]:\n{contexto_txt}"
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
        exportar_dataset_actualizado()

    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot activo, con voz y memoria en GitHub.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje de texto recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")

    respuesta = responder_usuario(texto_usuario)
    if not respuesta:
        respuesta = "Che, la consulta demoró en responder, pero ya quedé listo para la siguiente."

    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Descarga nota de voz de Telegram, la pasa a texto con Whisper y la responde."""
    print("🎤 Audio recibido, procesando voz con Whisper...")
    await update.message.chat.send_action(action="typing")

    ruta_ogg = "temp_audio.ogg"
    try:
        archivo_telegram = await update.message.voice.get_file()
        await archivo_telegram.download_to_drive(ruta_ogg)

        resultado_transcripcion = modelo_whisper.transcribe(ruta_ogg, language="es")
        texto_reconocido = resultado_transcripcion.get("text", "").strip()
        
        print(f"🗣️ Texto reconocido de la voz: '{texto_reconocido}'")

        if os.path.exists(ruta_ogg):
            os.remove(ruta_ogg)

        if not texto_reconocido:
            await update.message.reply_text("Che, no te pude captar bien el audio, ¿me lo repetís?")
            return

        respuesta = responder_usuario(texto_reconocido)
        if not respuesta:
            respuesta = "Che, la consulta de voz demoró en responder, pero ya quedé listo."

        await update.message.reply_text(f"*(Audio entendido: \"{texto_reconocido}\")*\n\n{respuesta}")

    except Exception as e:
        print(f"⚠️ Error procesando el audio: {e}")
        if os.path.exists(ruta_ogg):
            os.remove(ruta_ogg)
        await update.message.reply_text("Che, se me armó un lío procesando el audio.")


def main():
    if not TOKEN:
        print("❌ ERROR: No se encontró TELEGRAM_BOT_TOKEN.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
        print("🧹 Webhook previo eliminado correctamente.")
    except Exception as e:
        print(f"⚠️ No se pudo eliminar el webhook: {e}")

    print("🚀 Iniciando Leandro Bot en Telegram con soporte de voz...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz)) # Manejador de notas de voz
    
    app.run_polling()


if __name__ == "__main__":
    main()
