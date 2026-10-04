import asyncio
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
from gtts import gTTS

TXT_FILE = "conversaciones.txt"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Candado global para procesar notas de voz en orden y que no se pisen
lock_voz = asyncio.Lock()


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
    return ""


def requiere_busqueda_web(consulta):
    prompt = [
        {
            "role": "system",
            "content": (
                "Analizá la consulta del usuario. Si requiere datos en vivo, "
                "fechas recientes, enlaces, noticias o especificaciones "
                "técnicas de terceros, respondé 'SI'. Si es charla casual, "
                "opinión o conversación fluida, respondé 'NO'. Devolvé SOLAMENTE 'SI' o 'NO'."
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
                "usuario, generá una lista de palabras clave separadas por comas.\n"
                "Devolvé SOLAMENTE los términos, sin explicaciones."
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
            "content": "Analizá el historial y la consulta para devolver de 2 a 5 palabras clave de búsqueda web en texto plano.",
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

    return texto_resultados


def responder_usuario(orden):
    if not orden or not orden.strip():
        return "Che, no entendí bien lo que dijiste, ¿me lo repetís?"

    contexto_txt = recuperar_contexto_de_txt(orden)
    info_web = buscar_web(orden)

    system_prompt = (
        "Sos Leandro Bot, el asistente personal de Leandro.\n"
        "REGLAS:\n"
        "- Hablá SIEMPRE en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate').\n"
        "- Nutrite de los fragmentos recuperados del archivo .txt para mantener coherencia.\n"
        "- Sé directo, conciso y técnico. No des explicaciones de más."
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

    if not respuesta or not respuesta.strip():
        respuesta = "Che, me quedé pensando y no supe qué responderte a eso."

    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    exportar_dataset_actualizado()

    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot activo y al firme con voz bidireccional.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje de texto recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")

    respuesta = responder_usuario(texto_usuario)
    if not respuesta:
        respuesta = "Che, la consulta demoró en responder, pero ya quedé listo."

    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa notas de voz en orden secuencial (lock), las transcribe, genera IA y devuelve audio."""
    async with lock_voz:
        print("🎤 Audio recibido, procesando voz con Whisper...")
        await update.message.chat.send_action(action="record_voice")

        ruta_ogg = "temp_audio.ogg"
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""
        respuesta = ""

        try:
            modelo_whisper = whisper.load_model("base")

            archivo_telegram = await update.message.voice.get_file()
            await archivo_telegram.download_to_drive(ruta_ogg)

            resultado_transcripcion = modelo_whisper.transcribe(ruta_ogg, language="es")
            texto_reconocido = resultado_transcripcion.get("text", "").strip()
            
            print(f"🗣 Texto reconocido: '{texto_reconocido}'")

            if os.path.exists(ruta_ogg):
                os.remove(ruta_ogg)

            if not texto_reconocido:
                await update.message.reply_text("Che, no te pude captar bien el audio, ¿me lo repetís?")
                return

            respuesta = responder_usuario(texto_reconocido)
            print(f"🔊 Respuesta generada: '{respuesta}'")

            tts = gTTS(text=respuesta, lang="es", tld="com.ar")
            tts.save(ruta_respuesta_mp3)

            subprocess.run([
                "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
                ruta_respuesta_ogg
            ], check=True)

            with open(ruta_respuesta_ogg, "rb") as voice_file:
                await update.message.reply_voice(
                    voice=voice_file, 
                    caption=f"*(Entendido: \"{texto_reconocido}\")*"
                )

            print("✅ Nota de voz de respuesta enviada con éxito.")

        except Exception as e:
            print(f"⚠️ Error procesando el audio: {e}")
            try:
                await update.message.reply_text(f"*(Entendido: \"{texto_reconocido}\")*\n\n{respuesta}")
            except:
                await update.message.reply_text("Che, se me armó un lío procesando el audio.")

        finally:
            for archivo in [ruta_ogg, ruta_respuesta_mp3, ruta_respuesta_ogg]:
                if os.path.exists(archivo):
                    try:
                        os.remove(archivo)
                    except:
                        pass


def main():
    if not TOKEN:
        print("❌ ERROR: No se encontró TELEGRAM_BOT_TOKEN.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
        print("🧹 Webhook y actualizaciones pendientes limpiadas correctamente.")
    except Exception as e:
        print(f"⚠️ No se pudo limpiar el webhook: {e}")

    print("🚀 Iniciando Leandro Bot en Telegram con soporte de voz completo...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
