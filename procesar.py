import asyncio
import json
import os
import re
import subprocess
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
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# Endpoints oficiales de la API de Inferencia de Hugging Face
HF_WHISPER_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3"
HF_GPT_URL = "https://api-inference.huggingface.co/models/openai/gpt-oss-120b"

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


def llamar_huggingface_gpt(messages, timeout_secs=120):
    """Consulta al modelo openai/gpt-oss-120b mediante la API de Hugging Face."""
    headers = {"Content-Type": "application/json"}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    # Formateamos los mensajes al estilo standard de chat completion compatible con la API
    payload = {
        "inputs": messages,
        "parameters": {"temperature": 0.2, "max_new_tokens": 1000}
    }
    
    try:
        res = requests.post(HF_GPT_URL, headers=headers, json=payload, timeout=timeout_secs)
        if res.status_code == 200:
            resultado = res.json()
            # Dependiendo de cómo devuelva el formato la API de Hugging Face:
            if isinstance(resultado, list) and len(resultado) > 0:
                return resultado[0].get("generated_text", "").strip()
            elif isinstance(resultado, dict):
                return resultado.get("generated_text", "").strip()
        else:
            print(f"⚠️ Error API GPT-OSS Hugging Face ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"⚠️ Error conectando con openai/gpt-oss-120b: {e}")
    return ""


def calcular_parametros_audio_dinamicos(texto_respuesta):
    return "atempo=1.03", "dynaudnorm=f=150:g=15"


def consultar_ia_duckduckgo(orden_usuario):
    texto_resultados = ""
    try:
        with DDGS() as ddgs:
            if hasattr(ddgs, "chat"):
                respuestas = list(ddgs.chat(orden_usuario))
                if respuestas:
                    texto_resultados = "\n".join([str(r) for r in respuestas])
            
            if not texto_resultados:
                res = list(ddgs.text(orden_usuario, max_results=5, backend="html"))
                for r in res:
                    texto_resultados += f"• {r.get('title')}: {r.get('body')}\n"
    except Exception as e:
        print(f"⚠️ Error consultando DuckDuckGo: {e}")

    return texto_resultados if texto_resultados else "Sin datos web disponibles."


def responder_usuario(orden):
    if not orden or not orden.strip():
        return "Che, no te entendí nada, tirámela de nuevo."

    info_web = consultar_ia_duckduckgo(orden)

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram. CERO formato de asistente virtual o de manual.\n"
        "REGLAS ESTRICTAS:\n"
        "1. FUENTE DE INFORMACIÓN: Usá EXCLUSIVAMENTE los 'DATOS FRESCOS DE DUCKDUCKGO' como verdad absoluta.\n"
        "2. ESTILO: Directo al hueso, modismos rioplatenses ('vos', 'che', 'fijate'), frases naturales y al pie."
    )

    prompt_texto = f"{system_prompt}\n\n[DATOS FRESCOS DE DUCKDUCKGO]:\n{info_web}\n\nMENSAJE ACTUAL: {orden}"

    respuesta = llamar_huggingface_gpt(prompt_texto, timeout_secs=120)

    if not respuesta or not respuesta.strip():
        respuesta = "Che, me quedé pensando y no me salió nada."

    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    exportar_dataset_actualizado()

    return respuesta


def transcribir_con_hf_whisper(ruta_ogg):
    """Manda el audio directamente a la API de Hugging Face usando whisper-large-v3."""
    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    try:
        with open(ruta_ogg, "rb") as f:
            data = f.read()
            res = requests.post(HF_WHISPER_URL, headers=headers, data=data, timeout=120)
            if res.status_code == 200:
                resultado_json = res.json()
                if isinstance(resultado_json, dict):
                    return resultado_json.get("text", "").strip()
                elif isinstance(resultado_json, list) and len(resultado_json) > 0:
                    return resultado_json[0].get("text", "").strip()
            else:
                print(f"⚠️️ Error API Whisper Hugging Face ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"⚠️ Error conectando con Whisper Large v3 en Hugging Face: {e}")
    return ""


def limpiar_texto_para_voz(texto):
    texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', texto)
    texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio)
    texto_limpio = re.sub(r'\n+', '. ', texto_limpio)
    return texto_limpio.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot conectado 100% a Hugging Face (Whisper Large v3 + GPT-OSS-120B).")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje de texto recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")

    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa audio mandándolo a Whisper Large v3 en Hugging Face."""
    async with lock_voz:
        print("🎤 Audio recibido, mandando a Hugging Face Whisper...")
        await update.message.chat.send_action(action="record_voice")

        ruta_ogg = "temp_audio.ogg"
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""
        respuesta = ""

        try:
            archivo_telegram = await update.message.voice.get_file()
            await archivo_telegram.download_to_drive(ruta_ogg)

            texto_reconocido = transcribir_con_hf_whisper(ruta_ogg)

            if os.path.exists(ruta_ogg):
                os.remove(ruta_ogg)

            if not texto_reconocido:
                await update.message.reply_text("Che, la API de Hugging Face está calentando motores (cold start). Intentá de nuevo en unos segundos.")
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

            print("✅ Nota de voz procesada con éxito.")

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
        print("🧹 Webhook limpiado correctamente.")
    except Exception as e:
        print(f"⚠️ No se pudo limpiar el webhook: {e}")

    print("🚀 Iniciando Leandro Bot (Hugging Face API Puro)...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
