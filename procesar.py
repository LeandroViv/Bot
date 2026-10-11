import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
import urllib.request
import numpy as np
from datetime import datetime

print("🚀 [INIT]: Inicializando sistema híbrido definitivo (Timbre Bark + Partitura IA + Memoria Histórica + Git Sync)...")

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

try:
    from transformers import AutoProcessor, BarkModel
    import torch
    import soundfile as sf
    BARK_DISPONIBLE = True
    print("✅ [INIT]: Motor de timbre Bark disponible.")
except ImportError:
    BARK_DISPONIBLE = False
    print("⚠️ [INIT]: Bark no disponible.")

try:
    from google import genai
    GENAI_DISPONIBLE = True
    print("✅ [INIT]: Google GenAI disponible.")
except ImportError:
    GENAI_DISPONIBLE = False
    print("⚠️ [INIT]: Google GenAI NO disponible.")

TXT_FILE = "conversaciones.txt"
REGISTRO_METRICAS = "historial_metricas_voz.json"
CARPETA_MUESTRAS = "muestras_voz"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

if not os.path.exists(REGISTRO_METRICAS):
    with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY) if (GENAI_DISPONIBLE and GEMINI_API_KEY) else None
GEMINI_BLOQUEADO_POR_CUOTA = False
lock_voz = asyncio.Lock()


def registrar_entrenamiento_json(path_audio, texto_transcrito, tipo="voz_usuario"):
    try:
        with open(REGISTRO_METRICAS, "r", encoding="utf-8") as f:
            historial = json_lib.load(f)
    except Exception:
        historial = []

    nuevo_registro = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tipo": tipo,
        "archivo": path_audio,
        "texto": texto_transcrito,
        "total_entrenamientos": len(historial) + 1
    }
    historial.append(nuevo_registro)
    
    with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)
        
    print(f"📒 [REGISTRO JSON]: Entrenamiento #{nuevo_registro['total_entrenamientos']} guardado.")


def extraer_partitura_historica():
    if os.path.exists(REGISTRO_METRICAS):
        try:
            with open(REGISTRO_METRICAS, "r", encoding="utf-8") as f:
                historial = json_lib.load(f)
                ultimos = historial[-5:]
                return json_lib.dumps(ultimos, ensure_ascii=False)
        except Exception:
            pass
    return "[]"


def generar_respuesta_y_partitura_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    historial_contexto = extraer_partitura_historica()
    
    system_prompt = (
        "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo. "
        "Tenés a tu disposición el historial de notas de voz del usuario para aprender sus métricas rítmicas:\n"
        f"{historial_contexto}\n\n"
        "REGLA DE SÍNTESIS DE VOZ:\n"
        "Generá una respuesta en texto y construí una partitura métrica detallada palabra por palabra. "
        "Deduce la duración (duracion_ms entre 100 y 350) y la intensidad (intensidad_db entre -4.0 y 2.0) "
        "de cada palabra (incluso palabras nuevas o esdrújulas que no aparecían antes) analizando su sílaba tónica y el tono de la charla.\n\n"
        "Devolvé OBLIGATORIAMENTE un JSON estricto con esta estructura exacta, sin texto extra fuera:\n"
        "{\n"
        "  \"texto_completo\": \"Tu respuesta hablada aquí\",\n"
        "  \"partitura\": [\n"
        "    {\"palabra\": \"Che,\", \"duracion_ms\": 120, \"intensidad_db\": -1.5},\n"
        "    {\"palabra\": \"escuchá\", \"duracion_ms\": 250, \"intensidad_db\": 0.0}\n"
        "  ]\n"
        "}"
    )
    
    respuesta_raw = ""
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=f"Mensaje del oyente: \"{prompt_usuario}\"",
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json"
                )
            )
            if res and res.text:
                respuesta_raw = res.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
            print(f"⚠️ Error en Gemini partitura: {e}")

    if not respuesta_raw:
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.7},
            "stream": False,
        }
        try:
            res_local = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=15)
            if res_local.status_code == 200:
                respuesta_raw = res_local.json().get("message", {}).get("content", "").strip()
        except Exception:
            pass

    try:
        datos = json_lib.loads(respuesta_raw)
        texto = datos.get("texto_completo", "Che, todo bien por acá.")
        partitura = datos.get("partitura", [])
        if not partitura:
            raise ValueError("Partitura vacía")
        return texto, partitura
    except Exception:
        texto_fallback = "Che, se me cruzaron los cables un segundo, decime de nuevo."
        partitura_fallback = [
            {"palabra": "Che,", "duracion_ms": 120, "intensidad_db": -1.5},
            {"palabra": "todo", "duracion_ms": 150, "intensidad_db": 0.0},
            {"palabra": "bien.", "duracion_ms": 250, "intensidad_db": -2.0}
        ]
        return texto_fallback, partitura_fallback


def sintetizar_con_partitura_de_ia(texto, partitura, ogg_salida="resp.ogg"):
    wav_temp_timbre = "temp_timbre_bark.wav"
    wav_temp_final = "temp_dinamica_final.wav"
    sample_rate = 24000

    timbre_ok = False
    if BARK_DISPONIBLE:
        try:
            processor = AutoProcessor.from_pretrained("suno/bark-small")
            model = BarkModel.from_pretrained("suno/bark-small")
            device = "cpu"
            model = model.to(device)

            inputs = processor(f"[es] {texto[:250]}", voice_preset="v2/es_speaker_2").to(device)
            with torch.no_grad():
                audio_bark = model.generate(**inputs, max_new_tokens=250)
            
            audio_bark = audio_bark.cpu().numpy().squeeze()
            if len(audio_bark) > 1000:
                sf.write(wav_temp_timbre, audio_bark, sample_rate)
                timbre_ok = os.path.exists(wav_temp_timbre)
        except Exception as e:
            print(f"⚠️ Error en timbre Bark: {e}")

    if not timbre_ok:
        print("⚠️ [FALLBACK TIMBRE]: Usando tono base seguro.")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=150:duration=4", wav_temp_timbre], check=True)

    try:
        data_timbre, sr = sf.read(wav_temp_timbre)
        if len(data_timbre.shape) > 1:
            data_timbre = np.mean(data_timbre, axis=1)

        audio_dinamico = np.array([], dtype=np.float32)
        chunk_base_size = int(sr * 0.12)

        for item in partitura:
            duracion_ms = item.get("duracion_ms", 160)
            intensidad_db = item.get("intensidad_db", 0.0)

            muestras_bloque = int(sr * (duracion_ms / 1000.0))
            if muestras_bloque <= 0:
                muestras_bloque = chunk_base_size

            start_idx = np.random.randint(0, max(1, len(data_timbre) - muestras_bloque))
            fragmento = data_timbre[start_idx : start_idx + muestras_bloque]

            mult_vol = 10 ** (intensidad_db / 20.0)
            audio_dinamico = np.concatenate((audio_dinamico, fragmento * mult_vol))

        if len(audio_dinamico) < sr * 0.5:
            audio_dinamico = data_timbre

        sf.write(wav_temp_final, audio_dinamico, sr)
    except Exception as e:
        print(f"⚠️ Error aplicando partitura de IA, usando respaldo: {e}")
        subprocess.run(["cp", wav_temp_timbre, wav_temp_final], check=True)

    filtros = [
        "highpass=f=80",
        "lowpass=f=7500",
        "dynaudnorm=f=150:g=15:p=0.9",
        "volume=0.95"
    ]

    subprocess.run([
        "ffmpeg", "-y", "-i", wav_temp_final,
        "-filter:a", ",".join(filtros),
        "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
        ogg_salida
    ], check=True)

    for temp_f in [wav_temp_timbre, wav_temp_final]:
        if os.path.exists(temp_f):
            os.remove(temp_f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot híbrido activo con partitura IA guiada por historial y timbre Bark.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    await update.message.chat.send_action(action="record_voice")
    
    texto_limpio, partitura = generar_respuesta_y_partitura_ia(texto_usuario)
    ogg_f = "resp.ogg"
    
    sintetizar_con_partitura_de_ia(texto_limpio, partitura, ogg_f)

    with open(ogg_f, "rb") as vf:
        await update.message.reply_voice(voice=vf, caption="🎙️ *(Timbre Bark + Partitura IA)*")

    if os.path.exists(ogg_f): 
        os.remove(ogg_f)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        
        path_ogg = os.path.join(CARPETA_MUESTRAS, f"audio_usuario_{update.message.message_id}.ogg")
        path_wav = os.path.join(CARPETA_MUESTRAS, f"audio_usuario_{update.message.message_id}.wav")
        
        await file.download_to_drive(path_ogg)

        try:
            subprocess.run(["ffmpeg", "-y", "-i", path_ogg, "-ar", "22050", "-ac", "1", path_wav], check=True)
        except Exception as e:
            print(f"⚠️ Error convirtiendo .ogg a .wav: {e}")

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_ogg, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip()

        if not texto_crudo:
            await update.message.reply_text("Che, no te capté bien el audio.")
            return

        registrar_entrenamiento_json(path_wav if os.path.exists(path_wav) else path_ogg, texto_crudo)

        try:
            subprocess.run(["git", "config", "--global", "user.name", "Bot de Telegram"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "bot@github.action"], check=True)
            subprocess.run(["git", "add", CARPETA_MUESTRAS, REGISTRO_METRICAS], check=True)
            subprocess.run(["git", "commit", "-m", f"🧠 Auto-entrenamiento voz: {update.message.message_id}"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("🚀 [GIT SYNC]: Muestras y JSON subidos a GitHub.")
        except Exception as git_err:
            print(f"⚠️ [GIT SYNC]: Push omitido o sin permisos: {git_err}")

        texto_limpio, partitura = generar_respuesta_y_partitura_ia(texto_crudo)
        ogg_f = "resp.ogg"
        
        sintetizar_con_partitura_de_ia(texto_limpio, partitura, ogg_f)

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"🗣️ ¡Entrenamiento registrado y partitura IA aplicada!")

        if os.path.exists(ogg_f): os.remove(ogg_f)


def main():
    if not TOKEN:
        print("❌ ERROR: Falta TELEGRAM_BOT_TOKEN.")
        return

    print("🧹 Limpiando webhooks...")
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except Exception as e:
        print(f"⚠️ Aviso webhook: {e}")

    print("🚀 Iniciando Bot Híbrido Definitivo (Partitura IA + Bark)...")
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)
    app = Application.builder().token(TOKEN).request(request_config).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))

    while True:
        try:
            print("🔄 [POLLING]: Escuchando eventos...")
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            print(f"⚠️ Red interrumpida ({e}). Reconectando en 5 segundos...")
            time.sleep(5)


if __name__ == "__main__":
    main()
