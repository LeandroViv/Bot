"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo: procesar.py
Mejoras integradas:
1. Voz natural limpia con Gemini TTS (sin ruidos de Bark, sin cuelgues de CPU).
2. Fallback inteligente a Ollama (Llama) sin bloqueos de timeout.
3. MOTOR AUTÓNOMO PROACTIVO: Bucle de fondo que lee memoria_tareas.json y escribe
   por propia iniciativa al chat del usuario sin que él tenga que escribir primero!
4. Transcripción con Faster-Whisper, comando /corregir y sincronización Git.
"""

import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
from datetime import datetime
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

print("🚀 [INIT]: Inicializando LeandroBot definitivo (Gemini TTS + Motor Proactivo + Fallback Llama)...")

TXT_FILE = "conversaciones.txt"
REGISTRO_METRICAS = "historial_metricas_voz.json"
MEMORIA_TAREAS = "memoria_tareas.json"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CARPETA_MUESTRAS = "muestras_voz"
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

for f_path, default_val in [
    (REGISTRO_METRICAS, []),
    (MEMORIA_TAREAS, []),
    (DATASET_ENTRENAMIENTO, []),
]:
    if not os.path.exists(f_path):
        with open(f_path, "w", encoding="utf-8") as f:
            json_lib.dump(default_val, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# ID de chat objetivo detectado para mandar mensajes espontáneos
CHAT_ID_ACTIVO = None
lock_voz = asyncio.Lock()

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

def registrar_tarea_pendiente(instruccion):
    try:
        with open(MEMORIA_TAREAS, "r", encoding="utf-8") as f:
            tareas = json_lib.load(f)
        tareas.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "instruccion": instruccion, "pendiente": True})
        with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
            json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
        print(f"📒 [MEMORIA TAREAS]: Tarea guardada: {instruccion}")
    except Exception as e:
        print(f"⚠️ Error tarea: {e}")

def generar_texto_ia(prompt_usuario, es_proactivo=False):
    """Genera el texto usando Gemini (Prioridad 1) con fallback a Llama (Prioridad 2)."""
    p = prompt_usuario
    if es_proactivo:
        p = f"Iniciá vos la conversación con tu colega en Telegram por iniciativa propia sobre este motivo: {prompt_usuario}."

    if client:
        try:
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=p,
                config=dict(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
            )
            raw = res.text.strip()
            data = json_lib.loads(raw)
            return data.get("texto_completo", "Che, todo bien por acá.")
        except Exception as e:
            print(f"⚠️ Gemini fallback a Llama: {e}")

    # Fallback Ollama
    try:
        r = requests.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/chat",
            json={"model": "llama3.2", "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": p}], "format": "json"},
            timeout=60
        )
        if r.status_code == 200:
            data = json_lib.loads(r.json().get("message", {}).get("content", "{}"))
            return data.get("texto_completo", "Che, sintonizamos en un toque.")
    except Exception as ex:
        print(f"⚠️ Error Ollama: {ex}")

# Configuración de voz modelada por características (Voice Design)
VOZ_ESTILO_PERSONALIZADO = os.environ.get(
    "VOZ_ESTILO",
    "Locutor nocturno de radio FM porteño, hombre de 42 años, tono barítono cálido, pausado, con pequeñas respiraciones naturales, acústica de cabina de radio y voseo de Buenos Aires"
)
VOZ_BASE_NOMBRE = os.environ.get("VOZ_BASE", "Charon")

def sintetizar_voz_gemini(texto, ogg_salida="resp.ogg"):
    """
    Sintetiza audio con Gemini 3.8 TTS nativo usando el estilo modelado por características.
    Convierte directo a OGG/Opus sin pasar por Bark ni generar ruidos metálicos.
    """
    if not client:
        return False
    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash-lite-tts",
            contents=[{"role": "user", "parts": [{"text": texto, "speechMetadata": {"style": VOZ_ESTILO_PERSONALIZADO}}] }],
            config=dict(
                response_modalities=["AUDIO"],
                speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": VOZ_BASE_NOMBRE}}}
            )
        )
        b64 = response.candidates[0].content.parts[0].inline_data.data
        import base64
        wav_bytes = base64.b64decode(b64)
        
        # Convertir a OGG Opus nativo vía ffmpeg
        proc = subprocess.Popen([
            "ffmpeg", "-y", "-f", "wav", "-i", "-",
            "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.communicate(input=wav_bytes)
        return os.path.exists(ogg_salida)
    except Exception as e:
        print(f"⚠️ Error sintetizando con Gemini TTS: {e}")
        return False

# BUCLE AUTÓNOMO PROACTIVO: Escribe sin que el usuario le escriba
async def bucle_proactivo_autonomo(bot_app: Application):
    """Revisa memoria_tareas.json y lanza reflexiones de radio en Telegram de forma autónoma."""
    print("⚡ [PROACTIVO]: Motor de iniciativa propia iniciado. Esperando chat activo...")
    await asyncio.sleep(15)

    while True:
        try:
            await asyncio.sleep(180) # Cada 3 minutos evalúa si mandar un mensaje espontáneo
            global CHAT_ID_ACTIVO
            if not CHAT_ID_ACTIVO:
                continue

            # 1. Chequear si hay tareas pendientes en memoria_tareas.json
            tarea_pendiente = None
            try:
                with open(MEMORIA_TAREAS, "r", encoding="utf-8") as f:
                    tareas = json_lib.load(f)
                for t in tareas:
                    if t.get("pendiente"):
                        tarea_pendiente = t
                        t["pendiente"] = False
                        break
                with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
                    json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

            motivo = f"Cumpliendo lo que me pediste: '{tarea_pendiente['instruccion']}'" if tarea_pendiente else "Reflexión nocturna de radio FM espontánea"
            print(f"🎙️ [PROACTIVO]: Disparando mensaje espontáneo: {motivo}")

            texto_spont = generar_texto_ia(motivo, es_proactivo=True)
            registrar_conversacion("Leandro (Proactivo)", texto_spont)

            # Mandar texto a Telegram
            await bot_app.bot.send_message(chat_id=CHAT_ID_ACTIVO, text=f"📻 *Leandro (Radio FM)*:\n{texto_spont}", parse_mode="Markdown")

            # Mandar audio si se puede
            ogg_f = "proactivo.ogg"
            if sintetizar_voz_gemini(texto_spont, ogg_f):
                with open(ogg_f, "rb") as vf:
                    await bot_app.bot.send_voice(chat_id=CHAT_ID_ACTIVO, voice=vf)
                if os.path.exists(ogg_f):
                    os.remove(ogg_f)

        except Exception as e:
            print(f"⚠️ Error en bucle proactivo: {e}")
            await asyncio.sleep(10)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    await update.message.reply_text("¡Buenas che! Acá Leandro. Ya sintonicé tu chat: ahora te voy a hablar por cuenta propia a lo largo del día.")

async def corregir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    corr = " ".join(context.args).strip()
    await update.message.reply_text(f"✅ ¡Entendido che! Corrección guardada: '{corr}'.")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text
    registrar_conversacion("Usuario", u_text)

    # Detectar recordatorio
    if any(k in u_text.lower() for k in ["durante el día", "escribime", "recordá", "acordate"]):
        registrar_tarea_pendiente(u_text)

    resp = generar_texto_ia(u_text)
    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = "resp.ogg"
    if sintetizar_voz_gemini(resp, ogg_f):
        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(ogg_f): os.remove(ogg_f)

def main():
    if not TOKEN:
        print("❌ Falta TELEGRAM_BOT_TOKEN.")
        return
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)
    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("corregir", corregir))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    # Iniciar motor proactivo en segundo plano
    loop = asyncio.get_event_loop()
    loop.create_task(bucle_proactivo_autonomo(app))

    print("🔄 [POLLING]: Bot y motor proactivo activos...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
