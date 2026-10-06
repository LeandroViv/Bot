import asyncio
json_lib = __import__('json')
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

# Aseguramos directorios y archivos base
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)
if not os.path.exists(REGISTRO_INDUCCION):
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json_lib.dump({}, f)
if not os.path.exists(TXT_FILE):
    open(TXT_FILE, "w", encoding="utf-8").close()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

lock_voz = asyncio.Lock()

# Variable temporal para rastrear el último audio y su transcripción cruda por usuario/sesion
ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}


def sincronizar_con_github():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        
        archivos = [TXT_FILE, REGISTRO_INDUCCION]
        subprocess.run(["git", "add"] + archivos, check=True)
        
        # Agregamos también los archivos .ogg de muestras si hay nuevos
        subprocess.run(["git", "add", f"{CARPETA_MUESTRAS}/"], check=True)
        
        resultado = subprocess.run(["git", "commit", "-m", "🤖 Sincronización automática de muestras y觉inducción"], capture_output=True, text=True)
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Sincronizado con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ Aviso de git (no crítico): {e}")


def guardar_en_txt(rol, texto):
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")
    sincronizar_con_github()


# ==========================================
# SISTEMA DE INDUCCIÓN Y REGISTRO
# ==========================================
def cargar_historial_induccion():
    if os.path.exists(REGISTRO_INDUCCION):
        with open(REGISTRO_INDUCCION, "r", encoding="utf-8") as f:
            try:
                return json_lib.load(f)
            except:
                return {}
    return {}


def registrar_correccion_inductiva(audio_path, error_whisper, correccion_real):
    historial = cargar_historial_induccion()
    # Guardamos la frase o error completo para asociarlo de forma directa
    historial[error_whisper.lower().strip()] = {
        "correcto": correccion_real.strip(),
        "audio_muestra": audio_path
    }
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)
    print(f"🧠 [Inducción Aprendida]: '{error_whisper}' -> '{correccion_real}' (Audio: {audio_path})")
    sincronizar_con_github()


def cotejar_y_corregir_induccion(texto_crudo):
    historial = cargar_historial_induccion()
    if not historial:
        return texto_crudo
    
    texto_lower = texto_crudo.lower().strip()
    # 1. Si hay coincidencia exacta de frase guardada
    if texto_lower in historial:
        correccion = historial[texto_lower]["correcto"]
        print(f"🔍 [Inducción Exacta Aplicada]: '{texto_crudo}' -> '{correccion}'")
        return correccion

    # 2. Si no, revisamos por aproximación de palabras con difflib
    palabras = texto_crudo.split()
    texto_corregido = texto_crudo
    errores_conocidos = list(historial.keys())
    
    for palabra in palabras:
        coincidencias = difflib.get_close_matches(palabra.lower(), errores_conocidos, n=1, cutoff=0.80)
        if coincidencias:
            error_encontrado = coincidencias[0]
            correccion = historial[error_encontrado]["correcto"]
            texto_corregido = texto_corregido.replace(palabra, correccion)
            print(f"🔍 [Inducción Parcial Aplicada]: '{error_encontrado}' -> '{correccion}'")
            
    return texto_corregido


def llamar_ia_externa_o_local(prompt_usuario):
    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram. CERO formato de asistente virtual.\n"
        "REGLAS ESTRICTAS:\n"
        "1. AL HUESO: Respondé directo sobre lo que te pidió, sin dar vueltas.\n"
        "2. TONO PORTEÑO NATURAL: Hablá directo, al pie, usando 'vos', 'che', 'fijate'.\n"
        "3. BREVEDAD: Contestá corto y conciso."
    )

    prompt_final = f"MENSAJE: {prompt_usuario}"

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
    await update.message.reply_text("¡Buenas che! Bot activo con inducción por feedback directo.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    texto_usuario = update.message.text
    print(f"📩 Mensaje de texto recibido (posible corrección): {texto_usuario}")
    
    # Si el usuario responde justo después de un audio con texto, asumimos que es la corrección de ese audio
    if ULTIMO_AUDIO_PENDIENTE["path"] and ULTIMO_AUDIO_PENDIENTE["crudo"]:
        audio_p = ULTIMO_AUDIO_PENDIENTE["path"]
        crudo_p = ULTIMO_AUDIO_PENDIENTE["crudo"]
        
        registrar_correccion_inductiva(audio_p, crudo_p, texto_usuario)
        ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}
        
        await update.message.reply_text(f"Listo, che. Ya me anoté la corrección vinculada al audio físico y lo guardé en el historial inductivo.")
        return

    await update.message.chat.send_action(action="typing")
    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    async with lock_voz:
        print("🎤 Procesando audio...")
        await update.message.chat.send_action(action="record_voice")

        message_id = update.message.message_id
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""

        try:
            archivo_telegram = await update.message.voice.get_file()
            
            # Guardado físico permanente y forzado en muestras_voz/
            audio_filename = f"audio_{message_id}.ogg"
            audio_path = os.path.join(CARPETA_MUESTRAS, audio_filename)
            await archivo_telegram.download_to_drive(audio_path)
            print(f"🎙️ Audio guardado de forma permanente en: {audio_path}")

            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path, beam_size=5, language="es")
            texto_crudo = " ".join([segment.text for segment in segments]).strip()
            
            print(f"🗣️ Whisper crudo: {texto_crudo}")

            # Guardamos esto en la memoria temporal por si el usuario lo corrige al toque
            ULTIMO_AUDIO_PENDIENTE["path"] = audio_path
            ULTIMO_AUDIO_PENDIENTE["crudo"] = texto_crudo

            # Cotejo inductivo
            texto_reconocido = cotejar_y_corregir_induccion(texto_crudo)

            if not texto_reconocido:
                await update.message.reply_text("Che, no te capté bien el audio, ¿me lo repetís?")
                return

            respuesta = responder_usuario(texto_reconocido)

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

            print("✅ Nota de voz procesada con éxito y archivo .ogg asegurado.")

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

    print("🚀 Iniciando bot con captura de feedback y muestras persistentes...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
