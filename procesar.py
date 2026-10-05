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
from gtts import gTTS

TXT_FILE = "conversaciones.txt"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
# Token de Hugging Face (si tu Space o modelo requiere autenticación)
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# URL oficial de la API de inferencia de Hugging Face para Whisper Large v3
HF_WHISPER_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3"

# Candado global para procesar notas de voz en orden estricto
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
            print("☁️️ conversaciones.txt sincronizado con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️️ No se pudo sincronizar el .txt con GitHub: {e}")


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
        "options": {"num_ctx": 16384, "temperature": 0.2},
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


def calcular_parametros_audio_dinamicos(texto_respuesta):
    return "atempo=1.03", "dynaudnorm=f=150:g=15"


def extraer_conceptos_semanticos(consulta):
    prompt = [
        {
            "role": "system",
            "content": "Extractor de conceptos. Generá una lista de palabras clave separadas por comas, sin explicaciones.",
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


def recuperar_contexto_de_txt(consulta, max_bloques=3):
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


def consultar_ia_duckduckgo(orden_usuario):
    query = generar_query_semantica(orden_usuario)
    texto_resultados = ""
    try:
        with DDGS() as ddgs:
            if hasattr(ddgs, "chat"):
                respuestas = list(ddgs.chat(query))
                if respuestas:
                    texto_resultados = "\n".join([str(r) for r in respuestas])
            
            if not texto_resultados:
                res = list(ddgs.text(query, max_results=5, backend="html"))
                for r in res:
                    texto_resultados += f"• {r.get('title')}: {r.get('body')}\n"
    except Exception as e:
        print(f"⚠️ Error consultando DuckDuckGo: {e}")

    return texto_resultados if texto_resultados else "Sin datos web disponibles."


def responder_usuario(orden):
    if not orden or not orden.strip():
        return "Che, no te entendí nada, tirámela de nuevo."

    contexto_txt = recuperar_contexto_de_txt(orden, max_bloques=3)
    info_web = consultar_ia_duckduckgo(orden)

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram. CERO formato de asistente virtual o de manual.\n"
        "REGLAS ESTRICTAS:\n"
        "1. FUENTE DE INFORMACIÓN: Usá EXCLUSIVAMENTE los 'DATOS FRESCOS DE DUCKDUCKGO' como verdad absoluta.\n"
        "2. USO DEL HISTORIAL: El historial es SÓLO para mantener tus modismos rioplatenses ('vos', 'che', 'fijate').\n"
        "3. ESTILO: Directo al hueso, frases naturales y al pie."
    )

    mensaje_usuario = f"MENSAJE ACTUAL: {orden}\n\n[DATOS FRESCOS DE DUCKDUCKGO - VERDAD ABSOLUTA]:\n{info_web}"
    
    if contexto_txt:
        mensaje_usuario += f"\n\n[HISTORIAL DE ESTILO - NO REPETIR NI RESUMIR]:\n{contexto_txt}"

    mensajes_chat = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": mensaje_usuario},
    ]

    respuesta = llamar_ollama(mensajes_chat, timeout_secs=300)

    if not respuesta or not respuesta.strip():
        respuesta = "Che, me quedé pensando y no me salió nada."

    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    exportar_dataset_actualizado()

    return respuesta


def transcribir_con_hf_whisper_large_v3(ruta_ogg):
    """Manda el audio directamente a la API de Hugging Face usando whisper-large-v3."""
    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    try:
        with open(ruta_ogg, "rb") as f:
            data = f.read()
            res = requests.post(HF_WHISPER_URL, headers=headers, data=data, timeout=60)
            if res.status_code == 200:
                resultado_json = res.json()
                # Hugging Face suele devolver un diccionario con la clave 'text'
                if isinstance(resultado_json, dict):
                    return resultado_json.get("text", "").strip()
                elif isinstance(resultado_json, list) and len(resultado_json) > 0:
                    return resultado_json[0].get("text", "").strip()
            else:
                print(f"⚠️ Error API Hugging Face ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"⚠️ Error conectando con Hugging Face Whisper Large v3: {e}")
    return ""


def limpiar_texto_para_voz(texto):
    texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', texto)
    texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio)
    texto_limpio = re.sub(r'\n+', '. ', texto_limpio)
    return texto_limpio.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot activo con Whisper Large v3 (Hugging Face API) y DuckDuckGo.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje de texto recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")

    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa audio mandándolo a la API de Whisper Large v3 en Hugging Face."""
    async with lock_voz:
        print("🎤 Audio recibido, mandando a Hugging Face Whisper Large v3...")
        await update.message.chat.send_action(action="record_voice")

        ruta_ogg = "temp_audio.ogg"
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""
        respuesta = ""

        try:
            archivo_telegram = await update.message.voice.get_file()
            await archivo_telegram.download_to_drive(ruta_ogg)

            # Llamada directa a Whisper Large v3 en Hugging Face
            texto_reconocido = transcribir_con_hf_whisper_large_v3(ruta_ogg)

            if os.path.exists(ruta_ogg):
                os.remove(ruta_ogg)

            if not texto_reconocido:
                await update.message.reply_text("Che, no te capté bien el audio o la API de Hugging Face está cargando.")
                return

            respuesta = responder_usuario(texto_reconocido)
            print(f"🔊 Respuesta generada: '{respuesta}'")

            respuesta_para_voz = limpiar_texto_para_voz(respuesta)
            if not respuesta_para_voz:
                respuesta_para_voz = "Che, me quedé pensando y no supe qué decirte."

            tts = gTTS(text=respuesta_para_voz, lang="es", tld="com.ar")
            tts.save(ruta_respuesta_mp3)

            filtro_atempo, filtro_dinamico = calcular_parametros_audio_dinamicos(respuesta_para_voz)

            subprocess.run([
                "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                "-filter:a", f"{filtro_atempo},{filtro_dinamico}",
                "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
                ruta_respuesta_ogg
            ], check=True)

            with open(ruta_respuesta_ogg, "rb") as voice_file:
                await update.message.reply_voice(
                    voice=voice_file, 
                    caption=f"*(Entendido: \"{texto_reconocido}\")*"
                )

            print("✅ Nota de voz procesada con Whisper Large v3 y enviada con éxito.")

        except Exception as e:
            print(f"⚠ Error procesando el audio: {e}")
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
        print("🧹 Webhook limpiado correctamente.")
    except Exception as e:
        print(f"⚠️ No se pudo limpiar el webhook: {e}")

    print("🚀 Iniciando Leandro Bot (Whisper Large v3 API + DuckDuckGo)...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
