import asyncio
import json
import os
import re
import difflib
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
from faster_whisper import WhisperModel
import google.generativeai as genai
from gtts import gTTS

TXT_FILE = "conversaciones.txt"
REGISTRO_INDUCCION = "historial_induccion.json"
CARPETA_MUESTRAS = "muestras_voz"

# Aseguramos que existan las carpetas y archivos base localmente antes de tocar git
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)
if not os.path.exists(REGISTRO_INDUCCION):
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json.dump({}, f)
if not os.path.exists(TXT_FILE):
    open(TXT_FILE, "w", encoding="utf-8").close()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

lock_voz = asyncio.Lock()


def sincronizar_txt_con_github():
    """Sincroniza de forma segura la memoria y la inducción sin romper si falta algún archivo."""
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        
        # Agregamos solo si existen para evitar el error de pathspec
        archivos_a_subir = [TXT_FILE]
        if os.path.exists(REGISTRO_INDUCCION):
            archivos_a_subir.append(REGISTRO_INDUCCION)
            
        subprocess.run(["git", "add"] + archivos_a_subir, check=True)
        resultado = subprocess.run(["git", "commit", "-m", "🤖 Sincronización automática de inducción"], capture_output=True, text=True)
        
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Sincronizado con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ Aviso de git (no crítico): {e}")


def guardar_en_txt(rol, texto):
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")
    sincronizar_txt_con_github()


# ==========================================
# SISTEMA DE INDUCCIÓN Y REGISTRO
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
    """Guarda la corrección en el JSON y asegura que el archivo de audio quede referenciado."""
    historial = cargar_historial_induccion()
    historial[error_whisper.lower()] = {
        "correcto": correccion_real,
        "audio_muestra": audio_path
    }
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json.dump(historial, f, indent=4, ensure_ascii=False)
    print(f"🧠 [Inducción Aprendida]: '{error_whisper}' -> '{correccion_real}'")
    sincronizar_txt_con_github()


def cotejar_y_corregir_induccion(texto_crudo):
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


def llamar_ia_externa_o_local(prompt_usuario):
    info_web = ""
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(f"implementaciones LLM industria transporte {prompt_usuario}", max_results=2))
            for r in res:
                info_web += f"• {r.get('title')}: {r.get('body')}\n"
    except Exception as e:
        print(f"⚠️ Error en web: {e}")

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram. CERO formato de asistente virtual.\n"
        "REGLAS ESTRICTAS:\n"
        "1. AL HUESO: Respondé directo sobre lo que te pidió.\n"
        "2. TONO PORTEÑO NATURAL: Hablá directo, al pie, usando 'vos', 'che', 'fijate'.\n"
        "3. BREVEDAD: No te flashees con textos larguísimos."
    )

    prompt_final = f"MENSAJE: {prompt_usuario}"
    if info_web:
        prompt_final += f"\n\n[DATOS WEB]:\n{info_web}"

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=system_prompt)
            response = model.generate_content(prompt_final)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"⚠️ Gemini falló: {e}")

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
    await update.message.reply_text("¡Buenas che! Bot activo con corrección inductiva directa.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")
    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        print("🎤 Procesando audio...")
        await update.message.chat.send_action(action="record_voice")

        message_id = update.message.message_id
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""

        try:
            archivo_telegram = await update.message.voice.get_file()
            
            # Guardado físico permanente en muestras_voz/
            audio_filename = f"audio_{message_id}.ogg"
            audio_path = os.path.join(CARPETA_MUESTRAS, audio_filename)
            await archivo_telegram.download_to_drive(audio_path)
            print(f"🎙️ Audio guardado en: {audio_path}")

            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path, beam_size=5, language="es")
            texto_crudo = " ".join([segment.text for segment in segments]).strip()
            
            print(f"🗣️ Whisper crudo: {texto_crudo}")

            # Cotejo inductivo
            texto_reconocido = cotejar_y_corregir_induccion(texto_crudo)

            # Si detectamos que pifió feo y el usuario nos pasó la posta o queremos registrarlo:
            mensaje_feedback = ""
            if texto_crudo != texto_reconocido:
                registrar_correccion_inductiva(audio_path, texto_crudo, texto_reconocido)
                mensaje_feedback = f"Listo, ahí lo corrigí, che. Entendí: \"{texto_reconocido}\".\n\n"

            if not texto_reconocido:
                await update.message.reply_text("Che, no te capté bien el audio, ¿me lo repetís?")
                return

            respuesta = responder_usuario(texto_reconocido)
            respuesta_final_voz = mensaje_feedback + respuesta

            texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
            texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

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

            print("✅ Nota de voz procesada con éxito.")

        except Exception as e:
            print(f"⚠️ Error en audio: {e}")
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
        print("❌ ERROR: Falta token.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
        print("🧹 Webhook limpio.")
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")

    print("🚀 Iniciando bot blindado contra errores de Git y con feedback inductivo...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
