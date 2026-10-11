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

print("🚀 [INIT]: Inicializando sistema híbrido definitivo (Timbre Bark + JSON Adjunto a Gemini 3.8 + Git Sync)...")

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


def registrar_entrenamiento_json(path_audio, texto_transcrito, partitura_aplicada, tipo="voz_usuario"):
    """
    Guarda de forma persistente y continua el flujo de audios, textos 
    y métricas detalladas reales palabra por palabra.
    """
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
        "partitura_metrica": partitura_aplicada,
        "total_entrenamientos": len(historial) + 1
    }
    historial.append(nuevo_registro)
    
    with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)
        
    print(f"📒 [REGISTRO JSON CONTINUO]: Entrenamiento #{nuevo_registro['total_entrenamientos']} guardado con éxito.")


def generar_respuesta_y_partitura_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    respuesta_raw = ""
    
    system_prompt = (
        "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo.\n"
        "Tenés adjunto el historial JSON completo con todas las métricas acumuladas de las notas de voz previas. "
        "Analizá las duraciones e intensidades reales guardadas, abstrae las reglas de variación prosódica "
        "según la semántica del español, y aplicá ese ritmo para componer la partitura de la respuesta palabra por palabra.\n\n"
        "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown tipo ```json, solo el JSON crudo):\n"
        "{\n"
        "  \"texto_completo\": \"Tu respuesta hablada aquí\",\n"
        "  \"partitura\": [\n"
        "    {\"palabra\": \"Che,\", \"duracion_ms\": 120, \"intensidad_db\": -1.0},\n"
        "    {\"palabra\": \"escuchá\", \"duracion_ms\": 250, \"intensidad_db\": 0.0}\n"
        "  ]\n"
        "}"
    )
    
    # 1. Gemini con archivo adjunto (reintentando si da 503 por alta demanda)
    if client and not GEMINI_BLOQUEADO_POR_CUOTA and os.path.exists(REGISTRO_METRICAS):
        for intento in range(2):
            try:
                archivo_adjunto = client.files.upload(file=REGISTRO_METRICAS)
                res = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=[archivo_adjunto, f"Mensaje del oyente: \"{prompt_usuario}\""],
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json"
                    )
                )
                if res and res.text:
                    respuesta_raw = res.text.strip()
                    break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    GEMINI_BLOQUEADO_POR_CUOTA = True
                    print("⚠️ [CUOTA EXCEDIDA]: Gemini bloqueado, derivando a Llama local...")
                    break
                elif "503" in str(e) and intento == 0:
                    print("⚠️ [503 UNAVAILABLE]: Reintentando llamada a Gemini en 2 segundos...")
                    time.sleep(2)
                else:
                    print(f"⚠️ Error con Gemini adjuntando archivo: {e}")
                    break

    # 2. Fallback a Llama local (Ollama) con URL limpia sin corchetes
    if not respuesta_raw or GEMINI_BLOQUEADO_POR_CUOTA:
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
            url_llama = "[http://127.0.0.1:11434/api/chat](http://127.0.0.1:11434/api/chat)"
            res_local = requests.post(url_llama, json=payload, timeout=60)
            if res_local.status_code == 200:
                respuesta_raw = res_local.json().get("message", {}).get("content", "").strip()
        except Exception as ex_local:
            print(f"⚠️ Error conectando con Llama local: {ex_local}")

    # Limpieza total de markdown
    respuesta_raw = re.sub(r'^```json\s*', '', respuesta_raw, flags=re.IGNORECASE)
    respuesta_raw = re.sub(r'^```\s*', '', respuesta_raw)
    respuesta_raw = re.sub(r'\s*```$', '', respuesta_raw).strip()

    try:
        datos = json_lib.loads(respuesta_raw)
        texto = datos.get("texto_completo", "Che, todo bien por acá.")
        partitura = datos.get("partitura", [])
        if not partitura:
            raise ValueError("Partitura vacía")
        return texto, partitura
    except Exception as parse_err:
        print(f"⚠️ Error parseando JSON de la IA ({parse_err}). Respuesta cruda fue: {respuesta_raw}")
        texto_fallback = "Che, te escuché perfecto, acá sintonizamos de nuevo."
        partitura_fallback = [{"palabra": w, "duracion_ms": 180, "intensidad_db": -0.5} for w in texto_fallback.split()]
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

            inputs = processor(f"[es] {texto[:200]}", voice_preset="v2/es_speaker_2").to(device)
            with torch.no_grad():
                audio_bark = model.generate(**inputs)
            
            audio_bark = audio_bark.cpu().numpy().squeeze()
            if len(audio_bark) > 5000:
                sf.write(wav_temp_timbre, audio_bark, sample_rate)
                timbre_ok = os.path.exists(wav_temp_timbre)
        except Exception as e:
            print(f"⚠️ Error en timbre Bark: {e}")

    if not timbre_ok:
        print("⚠️ [FALLBACK TIMBRE]: Usando tono base seguro.")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=180:duration=3", wav_temp_timbre], check=True)

    try:
        data_timbre, sr = sf.read(wav_temp_timbre)
        if len(data_timbre.shape) > 1:
            data_timbre = np.mean(data_timbre, axis=1)

        max_val = np.max(np.abs(data_timbre))
        if max_val > 0:
            data_timbre = data_timbre / max_val

        if len(data_timbre) < sr * 1.0:
            data_timbre = np.tile(data_timbre, 2)

        audio_dinamico = np.array([], dtype=np.float32)
        chunk_base_size = int(sr * 0.15)

        if not partitura:
            partitura = [{"palabra": w, "duracion_ms": 180, "intensidad_db": 0.0} for w in texto.split()]

        for item in partitura:
            duracion_ms = item.get("duracion_ms", 180)
            intensidad_db = item.get("intensidad_db", 0.0)

            muestras_bloque = int(sr * (duracion_ms / 1000.0))
            if muestras_bloque <= 0:
                muestras_bloque = chunk_base_size

            start_idx = np.random.randint(0, max(1, len(data_timbre) - muestras_bloque))
            fragmento = data_timbre[start_idx : start_idx + muestras_bloque]

            intensidad_db_segura = max(min(intensidad_db, 1.5), -2.5)
            mult_vol = 10 ** (intensidad_db_segura / 20.0)
            
            audio_dinamico = np.concatenate((audio_dinamico, fragmento * mult_vol))

        if len(audio_dinamico) < sr * 1.0:
            audio_dinamico = data_timbre

        sf.write(wav_temp_final, audio_dinamico, sr)
    except Exception as e:
        print(f"⚠️ Error aplicando partitura segura: {e}")
        subprocess.run(["cp", wav_temp_timbre, wav_temp_final], check=True)

    filtros = [
        "highpass=f=80",
        "lowpass=f=7500",
        "dynaudnorm=f=150:g=15:p=0.9",
        "volume=1.2"
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
    await update.message.reply_text("¡Buenas che! Bot híbrido activo con historial JSON adjunto y partituras continuas reales.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    await update.message.chat.send_action(action="record_voice")
    
    texto_limpio, partitura = generar_respuesta_y_partitura_ia(texto_usuario)
    ogg_f = "resp.ogg"
    
    sintetizar_con_partitura_de_ia(texto_limpio, partitura, ogg_f)

    with open(ogg_f, "rb") as vf:
        await update.message.reply_voice(voice=vf, caption="🎙️ *(Historial JSON Adjunto + Partitura IA)*")

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

        # Extracción real con Whisper (Timestamps y texto)
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_ogg, beam_size=5, language="es", word_timestamps=True)
        
        texto_crudo = ""
        partitura_real = []

        # Cargamos el WAV para medir intensidad real RMS por tramo
        data_wav, sr_wav = sf.read(path_wav) if os.path.exists(path_wav) else (None, 22050)
        if data_wav is not None and len(data_wav.shape) > 1:
            data_wav = np.mean(data_wav, axis=1)

        for segment in segments:
            texto_crudo += segment.text + " "
            if hasattr(segment, 'words') and segment.words:
                for w_info in segment.words:
                    palabra = w_info.word.strip()
                    inicio_ms = int(w_info.start * 1000)
                    fin_ms = int(w_info.end * 1000)
                    duracion_ms = max(50, fin_ms - inicio_ms)
                    
                    intensidad_db = 0.0
                    if data_wav is not None and len(data_wav) > 0:
                        idx_ini = int(w_info.start * sr_wav)
                        idx_fin = int(w_info.end * sr_wav)
                        fragmento = data_wav[max(0, idx_ini):min(len(data_wav), idx_fin)]
                        if len(fragmento) > 0:
                            rms = np.sqrt(np.mean(fragmento**2))
                            if rms > 0:
                                intensidad_db = round(float(20 * np.log10(rms)), 2)
                                intensidad_db = max(min(intensidad_db, 2.0), -4.0)

                    partitura_real.append({
                        "palabra": palabra,
                        "duracion_ms": duracion_ms,
                        "intensidad_db": intensidad_db
                    })

        texto_crudo = texto_crudo.strip()

        if not texto_crudo:
            await update.message.reply_text("Che, no te capté bien el audio.")
            return

        if not partitura_real:
            partitura_real = [{"palabra": w, "duracion_ms": 200, "intensidad_db": 0.0} for w in texto_crudo.split()]

        # Guardamos en el JSON las métricas reales exactas
        registrar_entrenamiento_json(path_wav if os.path.exists(path_wav) else path_ogg, texto_crudo, partitura_real)

        try:
            subprocess.run(["git", "config", "--global", "user.name", "Bot de Telegram"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "bot@github.action"], check=True)
            subprocess.run(["git", "add", CARPETA_MUESTRAS, REGISTRO_METRICAS], check=True)
            subprocess.run(["git", "commit", "-m", f"🧠 Auto-entrenamiento métricas reales: {update.message.message_id}"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("🚀 [GIT SYNC]: Muestras y métricas detalladas reales subidas a GitHub.")
        except Exception as git_err:
            print(f"⚠️ [GIT SYNC]: Push omitido o sin permisos: {git_err}")

        texto_limpio, partitura_respuesta = generar_respuesta_y_partitura_ia(texto_crudo)
        ogg_f = "resp.ogg"
        
        sintetizar_con_partitura_de_ia(texto_limpio, partitura_respuesta, ogg_f)

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"🗣️ ¡Métricas reales guardadas y respuesta lista!")

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

    print("🚀 Iniciando Bot Híbrido Definitivo...")
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
