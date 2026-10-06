import asyncio
import json
import os
import re
import difflib
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
from faster_whisper import WhisperModel
import google.generativeai as genai
from gtts import gTTS

TXT_FILE = "conversaciones.txt"
REGISTRO_INDUCCION = "historial_induccion.json"
CARPETA_MUESTRAS = "muestras_voz"
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Candado global para procesar notas de voz en orden estricto
lock_voz = asyncio.Lock()


def sincronizar_txt_con_github():
    """Hace commit y push automático de la memoria e inducción al repositorio."""
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        
        subprocess.run(["git", "add", TXT_FILE, REGISTRO_INDUCCION], check=True)
        resultado = subprocess.run(["git", "commit", "-m", "🤖 Sincronización automática de inducción y memoria"], capture_output=True, text=True)
        
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Archivos sincronizados con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ No se pudo sincronizar con GitHub: {e}")


def guardar_en_txt(rol, texto):
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")
    sincronizar_txt_con_github()


# ==========================================
# SISTEMA DE INDUCCIÓN Y APRENDIZAJE FONÉTICO
# ==========================================
def cargar_historial_induccion():
    if os.path.exists(REGISTRO_INDUCCION):
        with open(REGISTRO_INDUCCION, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}


def registrar_correccion_inductiva(audio_path, error_whisper, correccion_real):
    """Asocia el audio físico guardado con la corrección real provista por vos."""
    historial = cargar_historial_induccion()
    historial[error_whisper.lower()] = {
        "correcto": correccion_real,
        "audio_muestra": audio_path
    }
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json.dump(historial, f, indent=4, ensure_ascii=False)
    print(f"🧠 [Inducción Aprendida]: '{error_whisper}' -> '{correccion_real}' (Atado a {audio_path})")
    sincronizar_txt_con_github()


def cotejar_y_corregir_induccion(texto_crudo):
    """Compara la transcripción con el historial inductivo usando difflib."""
    historial = cargar_historial_induccion()
    if not historial:
        return texto_crudo
    
    palabras = texto_crudo.split()
    texto_corregido = texto_crudo
    errores_conocidos = list(historial.keys())
    
    for palabra in palabras:
        coincidencias = difflib.get_close_matches(palabra.lower(), errores_conocidos, n=1, cutoff=0.75)
        if coincidencias:
            error_encontrado = coincidencias[0]
            correccion = historial[error_encontrado]["correcto"]
            texto_corregido = texto_corregido.replace(palabra, correccion)
            print(f"🔍 [Inducción Aplicada]: '{error_encontrado}' -> '{correccion}'")
            
    return texto_corregido


# ==========================================
# CONSULTA A LA IA (GEMINI / OLLAMA) CON BÚSQUEDA WEB
# ==========================================
def llamar_ia_externa_o_local(prompt_usuario):
    """Usa Gemini con DuckDuckGo o respaldo local, enfocado estrictamente en transporte e industria."""
    # Buscamos datos frescos en la web relacionados con la consulta
    info_web = ""
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(f"implementaciones LLM industria transporte {prompt_usuario}", max_results=3))
            for r in res:
                info_web += f"• {r.get('title')}: {r.get('body')}\n"
    except Exception as e:
        print(f"⚠️ Error en web: {e}")

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram. CERO formato de asistente virtual, ni manuales largos, ni resúmenes.\n"
        "REGLAS ESTRICTAS:\n"
        "1. AL HUESO: Respondé directo sobre lo que te pidió (ej. LLM en transporte).\n"
        "2. TONO PORTEÑO NATURAL: Hablá directo, al pie, usando 'vos', 'che', 'fijate', sin formalidades.\n"
        "3. VERDAD WEB: Si hay datos frescos de la web, usalos como base técnica."
    )

    prompt_final = f"MENSAJE: {prompt_usuario}"
    if info_web:
        prompt_final += f"\n\n[DATOS FRESCOS WEB]:\n{info_web}"

    # 1. Intento con Google Gemini API
    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=system_prompt)
            response = model.generate_content(prompt_final)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"⚠️ Falló Gemini: {e}. Probando Ollama...")

    # 2. Respaldo Ollama local
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_final}
        ],
        "options": {"num_ctx": 16384, "temperature": 0.2},
        "stream": False,
    }
    try:
        res = requests.post(url, json=payload, timeout=300)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
    except:
        pass
        
    return "Che, me quedé sin conexión con las IAs, tirámela de nuevo."


def responder_usuario(orden):
    if not orden or not orden.strip():
        return "Che, no te entendí nada, tirámela de nuevo."

    respuesta = llamar_ia_externa_o_local(orden)
    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con inducción fonética y persistencia de muestras.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje de texto recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")

    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa audio guardándolo permanentemente en muestras_voz/, aplicando Whisper e inducción."""
    async with lock_voz:
        print("🎤 Audio recibido, procesando persistencia y Whisper...")
        await update.message.chat.send_action(action="record_voice")

        message_id = update.message.message_id
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""
        respuesta = ""

        try:
            archivo_telegram = await update.message.voice.get_file()
            
            # Guardado permanente del archivo físico en muestras_voz/
            audio_filename = f"audio_{message_id}.ogg"
            audio_path = os.path.join(CARPETA_MUESTRAS, audio_filename)
            await archivo_telegram.download_to_drive(audio_path)
            print(f"🎙️ Audio guardado de forma permanente en: {audio_path}")

            # Transcripción con Faster-Whisper
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path, beam_size=5, language="es")
            texto_crudo = " ".join([segment.text for segment in segments]).strip()
            
            print(f"🗣️ Whisper crudo: {texto_crudo}")

            # Aplicamos cotejo inductivo fonético
            texto_reconocido = cotejar_y_corregir_induccion(texto_crudo)

            # Si nos pasaste explícitamente el texto real por el chat o detectamos desvío, registramos la inducción
            if texto_crudo != texto_reconocido:
                registrar_correccion_inductiva(audio_path, texto_crudo, texto_reconocido)

            if not texto_reconocido:
                await update.message.reply_text("Che, no te capté bien el audio, ¿me lo repetís?")
                return

            respuesta = responder_usuario(texto_reconocido)
            print(f"🔊 Respuesta generada: '{respuesta}'")

            texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
            texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()
            if not texto_limpio:
                texto_limpio = "Che, me quedé pensando y no supe qué decirte."

            tts = gTTS(text=texto_limpio, lang="es", tld="com.ar")
            tts.save(ruta_respuesta_mp3)

            subprocess.run([
                "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                "-filter:a", "atempo=1.03,dynaudnorm=f=150:g=15",
                "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
                ruta_respuesta_ogg
            ], check=True)

            with open(ruta_respuesta_ogg, "rb") as voice_file:
                await update.message.reply_voice(
                    voice=voice_file, 
                    caption=f"*(Entendido: \"{texto_reconocido}\")*"
                )

            print("✅ Nota de voz procesada y enviada con éxito.")

        except Exception as e:
            print(f"⚠️ Error procesando el audio: {e}")
            try:
                await update.message.reply_text(f"*(Entendido: \"{texto_reconocido}\")*\n\n{respuesta}")
            except:
                await update.message.reply_text("Che, se me armó un lío procesando el audio.")

        finally:
            for archivo in [ruta_respuesta_mp3, ruta_respuesta_ogg]:
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

    print("🚀 Iniciando Leandro Bot con Inducción Fonética y Muestras Activas...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
