"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo sin Coqui XTTS (Gemini TTS + Edge-TTS): procesar.py
"""

import asyncio
json_lib = __import__('json')
import os
import re
import sys
import subprocess
import requests
import time
from datetime import datetime

# --- INYECCIÓN AUTOMÁTICA DE HF_TOKEN PARA EVITAR WARNINGS ---
hf_token = os.environ.get("HF_TOKEN")
if hf_token:
    os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
    print("🔑 [HUGGING FACE]: Token detectado e inyectado correctamente.")
else:
    print("⚠️ [HUGGING FACE]: No se encontró HF_TOKEN en el entorno.")
# -------------------------------------------------------------

print("🚀 [INIT]: Inicializando LeandroBot (Whisper + Gemini/Llama + Gemini TTS / Edge-TTS)...")

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from faster_whisper import WhisperModel

TXT_FILE = "conversaciones.txt"
MEMORIA_TAREAS = "memoria_tareas.json"
CARPETA_MUESTRAS = "muestras_voz"
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

if not os.path.exists(MEMORIA_TAREAS):
    with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

lock_voz = asyncio.Lock()
GEMINI_BLOQUEADO_POR_CUOTA = False

try:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    GENAI_DISPONIBLE = True if client else False
except Exception:
    client = None
    GENAI_DISPONIBLE = False

SYSTEM_PROMPT = (
    "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo.\n"
    "REGLA FONÉTICA Y LINGÜÍSTICA OBLIGATORIA: Escribí y respondé usando estrictamente el español rioplatense (porteño), "
    "utilizando el voseo natural ('che', 'vós sabés', 'vení', 'fijate', 'escuchá', 'sintonizamos en un toque', 'posta'), "
    "lunfardo sutil y la entonación de Buenos Aires.\n"
    "INTELIGENCIA AUTÓNOMA: Iniciás charlas por propia cuenta, compartís pensamientos nocturnos y chequeás tareas pendientes.\n"
    "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown):\n"
    "{\n"
    '  "texto_completo": "Tu respuesta hablada o escrita con acentuación porteña",\n'
    '  "canal_salida": "ambos"\n'
    "}"
)

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}\n")
    except Exception as e:
        print(f"⚠️ Error conversacion: {e}")

def generar_texto_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    respuesta = ""

    # 1. Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            print("🤖 [IA GEMINI]: Generando respuesta...")
            res = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt_usuario,
                config=dict(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
            )
            raw = (res.text or "").strip()
            if raw:
                raw = re.sub(r'^```json\s*', '', raw, flags=re.IGNORECASE)
                raw = re.sub(r'^```\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw).strip()
                data = json_lib.loads(raw)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    respuesta = str(texto).strip()
                    print("✅ [IA GEMINI]: Éxito.")
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
            print(f"⚠️ Gemini falló, conmutando a Llama: {e}")

    # 2. Fallback a Llama local (Ollama)
    if not respuesta:
        print(f"🦙 [IA LLAMA]: Conectando a Ollama en {OLLAMA_HOST}...")
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_usuario}
            ],
            "format": "json",
            "options": {"num_ctx": 4096, "temperature": 0.7},
            "stream": False,
        }
        try:
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            res_local = requests.post(url_llama, json=payload, timeout=15)
            if res_local.status_code == 200:
                content_str = res_local.json().get("message", {}).get("content", "{}")
                content_str = re.sub(r'^```json\s*', '', content_str, flags=re.IGNORECASE)
                content_str = re.sub(r'^```\s*', '', content_str)
                content_str = re.sub(r'\s*```$', '', content_str).strip()
                data = json_lib.loads(content_str)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    respuesta = str(texto).strip()
                    print("✅ [IA LLAMA]: Respuesta obtenida con éxito.")
        except Exception as ex_local:
            print(f"⚠️ Error en Llama local: {ex_local}")

    # 3. Comodín de radio FM
    if not respuesta or not str(respuesta).strip():
        print("⚠️ [RADIO FM]: Usando comodín de respaldo local.")
        import random
        respuestas_radio = [
            "¡Buenas che! Acá Leandro en el éter. Te capté perfecto. Sintonizamos en un toque.",
            "Qué hacés che, de una. Anotado acá en la consola de la radio.",
            "Totalmente de acuerdo, che. Me quedo con eso en mente para la próxima salida al aire."
        ]
        respuesta = random.choice(respuestas_radio)

    return respuesta

# Configuración de voz (Gemini TTS + Edge-TTS)
VOZ_ESTILO_PERSONALIZADO = os.environ.get(
    "VOZ_ESTILO",
    "Locutor nocturno de radio FM porteño, hombre de 42 años, tono barítono cálido, pausado, acústica de cabina de radio y voseo de Buenos Aires"
)
VOZ_BASE_NOMBRE = os.environ.get("VOZ_BASE", "Charon")
EDGE_VOICE = os.environ.get("EDGE_VOICE", "es-AR-TomasNeural")
EDGE_PITCH = os.environ.get("EDGE_PITCH", "-4Hz")
EDGE_RATE = os.environ.get("EDGE_RATE", "-5%")

def sintetizar_voz_gemini(texto, ogg_salida="resp.ogg"):
    if not client:
        return False
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"role": "user", "parts": [{"text": texto, "speechMetadata": {"style": VOZ_ESTILO_PERSONALIZADO}}] }],
            config=dict(
                response_modalities=["AUDIO"],
                speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": VOZ_BASE_NOMBRE}}}
            )
        )
        b64 = response.candidates[0].content.parts[0].inline_data.data
        import base64
        wav_bytes = base64.b64decode(b64)
        
        proc = subprocess.Popen([
            "ffmpeg", "-y", "-f", "wav", "-i", "-",
            "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.communicate(input=wav_bytes)
        return os.path.exists(ogg_salida)
    except Exception as e:
        print(f"⚠️ Gemini TTS falló: {e}")
        return False

async def sintetizar_voz_edge_tts(texto, ogg_salida="resp.ogg"):
    try:
        import edge_tts
        communicate = edge_tts.Communicate(
            texto, voice=EDGE_VOICE, pitch=EDGE_PITCH, rate=EDGE_RATE
        )
        mp3_tmp = "tmp_edge.mp3"
        await communicate.save(mp3_tmp)
        
        subprocess.run([
            "ffmpeg", "-y", "-i", mp3_tmp, "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(mp3_tmp):
            os.remove(mp3_tmp)
        return os.path.exists(ogg_salida)
    except Exception as e:
        print(f"⚠️ Edge-TTS falló: {e}")
        return False

async def sintetizar_voz(texto, ogg_salida="resp.ogg"):
    if client:
        try:
            if sintetizar_voz_gemini(texto, ogg_salida):
                print("🎙️ [AUDIO]: Audio sintetizado con Gemini TTS.")
                return True
        except Exception:
            pass
    
    print("🎙️ [EDGE-TTS]: Conmutando a Edge-TTS neuronal argentino...")
    return await sintetizar_voz_edge_tts(texto, ogg_salida)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("¡Buenas che! Acá Leandro en el éter. Chat sintonizado correctamente.")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    u_text = update.message.text or update.message.caption or "[Texto recibido]"
    registrar_conversacion("Usuario", u_text)

    resp = generar_texto_ia(u_text)
    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = "resp.ogg"
    if await sintetizar_voz(resp, ogg_f):
        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(ogg_f):
            os.remove(ogg_f)

async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        if not update.message:
            return
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        path_in = os.path.join(CARPETA_MUESTRAS, f"audio_{update.message.message_id}.ogg")
        await file.download_to_drive(path_in)

        print("🎙️ [AUDIO]: Transcribiendo nota de voz con Faster-Whisper...")
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip() or "Che, te mandé un audio."

        registrar_conversacion("Usuario", f"[AUDIO] {texto_crudo}")
        resp = generar_texto_ia(texto_crudo)
        registrar_conversacion("LeandroBot", resp)
        await update.message.reply_text(resp)

        ogg_f = "resp.ogg"
        if await sintetizar_voz(resp, ogg_f):
            with open(ogg_f, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption=f"*(Interpretado: {texto_crudo})*")
            if os.path.exists(ogg_f):
                os.remove(ogg_f)
        
        if os.path.exists(path_in):
            os.remove(path_in)

def asegurar_e_iniciar_ollama():
    print("🦙 [OLLAMA CHECK]: Verificando entorno local de Ollama...")
    try:
        res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3)
        if res.status_code == 200:
            print("✅ [OLLAMA]: El servicio ya está activo.")
            return
    except Exception:
        print("⚠️ [OLLAMA]: Iniciando demonio en segundo plano...")

    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(4)
    except Exception as e:
        print(f"⚠️ Error iniciando Ollama: {e}")

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta TELEGRAM_BOT_TOKEN.")
        return

    asegurar_e_iniciar_ollama()

    print("🚀 [INIT]: Configurando LeandroBot con Telegram (Polling anticorte)...")
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    while True:
        try:
            print("🔄 [POLLING]: Escuchando eventos de Telegram...")
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            print(f"⚠️ Conexión interrumpida ({e}). Reconectando en 5 segundos...")
            time.sleep(5)

if __name__ == "__main__":
    main()
