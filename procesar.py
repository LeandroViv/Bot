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

print("🚀 [INIT]: Inicializando sistema híbrido definitivo (Timbre Bark + Registro JSON + Métricas Nativas)...")

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

# Intentamos cargar dependencias para Bark y análisis de audio
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
    import librosa
    LIBROSA_DISPONIBLE = True
    print("✅ [INIT]: Librosa disponible para análisis DSP de .wav.")
except ImportError:
    LIBROSA_DISPONIBLE = False
    print("⚠️ [INIT]: Librosa no disponible, usando análisis nativo RMS con soundfile/numpy.")

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

# Inicializar JSON de registro si no existe
if not os.path.exists(REGISTRO_METRICAS):
    with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY) if (GENAI_DISPONIBLE and GEMINI_API_KEY) else None
GEMINI_BLOQUEADO_POR_CUOTA = False
lock_voz = asyncio.Lock()


def registrar_entrenamiento_json(path_audio, texto_transcrito, tipo="voz_usuario"):
    """Registra de forma persistente cada entrenamiento en el historial JSON."""
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
        
    print(f"📒 [REGISTRO JSON]: Entrenamiento #{nuevo_registro['total_entrenamientos']} guardado correctamente.")


def llamar_ia_externa_o_local(prompt_usuario, system_prompt_custom=None):
    global GEMINI_BLOQUEADO_POR_CUOTA
    
    system_prompt = system_prompt_custom or (
        "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. "
        "Porteño, cálido, directo, usando 'vos' y 'che'. "
        "Dinamizá tus textos con pausas y énfasis para que la cadencia sea perfecta."
    )
    
    respuesta = ""
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=f"Solicitud: \"{prompt_usuario}\"",
                config=genai.types.GenerateContentConfig(system_instruction=system_prompt)
            )
            if res and res.text:
                respuesta = res.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True

    if not respuesta:
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.6},
            "stream": False,
        }
        try:
            res_local = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=15)
            if res_local.status_code == 200:
                respuesta = res_local.json().get("message", {}).get("content", "").strip()
        except Exception:
            pass

    return respuesta or "Che... me quedé sin conexión un toque."


def extraer_metricas_de_wav(path_wav, cantidad_palabras=10):
    """Extrae métricas cuantitativas usando librosa o análisis nativo RMS con soundfile/numpy."""
    if LIBROSA_DISPONIBLE:
        try:
            y, sr = librosa.load(path_wav, sr=22050)
            hop_length = 512
            rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
            db_values = librosa.amplitude_to_db(rms, ref=np.max)
            
            chunk_duration_ms = int((hop_length / sr) * 1000)
            partitura_extraida = []
            
            for i in range(0, len(db_values), 2):
                intensidad = float(db_values[i])
                intensidad_normalizada = max(min(intensidad / 6.0, 0.0), -4.0)
                partitura_extraida.append({
                    "duracion_ms": chunk_duration_ms * 2,
                    "intensidad_db": intensidad_normalizada
                })
            print(f"📊 [ANÁLISIS LIBROSA]: Métricas extraídas de {path_wav} ({len(partitura_extraida)} frames).")
            if partitura_extraida:
                return partitura_extraida
        except Exception as e:
            print(f"⚠️ Error en librosa: {e}")

    # Análisis nativo RMS por bloques usando soundfile y numpy (sin necesidad de librosa)
    try:
        data, sr = sf.read(path_wav)
        if len(data.shape) > 1:
            data = np.mean(data, axis=1) # Convertir a mono si es estéreo
            
        frame_length = int(sr * 0.05) # Bloques de 50ms
        if frame_length <= 0:
            frame_length = 1000
            
        partitura_extraida = []
        for i in range(0, len(data), frame_length):
            chunk = data[i:i + frame_length]
            if len(chunk) == 0:
                continue
            rms_val = np.sqrt(np.mean(chunk**2))
            db_val = 20 * np.log10(max(rms_val, 1e-5))
            # Normalizar dB relativos
            db_norm = max(min(db_val / 6.0, 0.0), -4.0)
            
            partitura_extraida.append({
                "duracion_ms": 50,
                "intensidad_db": float(db_norm)
            })
            
        print(f"📊 [ANÁLISIS NATIVO RMS]: Métricas extraídas de {path_wav} ({len(partitura_extraida)} frames).")
        if partitura_extraida:
            return partitura_extraida
    except Exception as e:
        print(f"⚠️ Error en análisis nativo RMS: {e}")

    # Fallback final proporcional
    return [{"duracion_ms": 150, "intensidad_db": 0.0} for _ in range(max(cantidad_palabras, 5))]


def obtener_wav_de_la_web_o_sintetico(query_o_url, cantidad_palabras=10):
    os.makedirs(CARPETA_MUESTRAS, exist_ok=True)
    wav_referencia = None
    
    if query_o_url.startswith("http"):
        try:
            print(f"🌐 [WEB]: Descargando .wav de referencia...")
            path_temp_web = os.path.join(CARPETA_MUESTRAS, f"referencia_web_{int(time.time())}.wav")
            urllib.request.urlretrieve(query_o_url, path_temp_web)
            if os.path.exists(path_temp_web) and os.path.getsize(path_temp_web) > 1000:
                wav_referencia = path_temp_web
                print(f"✅ [WEB]: Guardado en {wav_referencia}")
        except Exception as e:
            print(f"⚠️ [WEB]: Falló descarga: {e}")

    if not wav_referencia:
        print("🛠️ [FALLBACK SINTÉTICO]: Generando .wav local con FFmpeg...")
        path_sintetico = os.path.join(CARPETA_MUESTRAS, f"referencia_sintetica_{int(time.time())}.wav")
        try:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "sine=frequency=180:duration=3",
                "-af", "volume=0.8",
                path_sintetico
            ], check=True)
            if os.path.exists(path_sintetico):
                wav_referencia = path_sintetico
                print(f"✅ [FALLBACK SINTÉTICO]: Guardado en {wav_referencia}")
        except Exception as ex:
            print(f"⚠️ Error generando .wav sintético: {ex}")

    if wav_referencia:
        return extraer_metricas_de_wav(wav_referencia, cantidad_palabras)
    else:
        return [{"duracion_ms": 180, "intensidad_db": 0.0} for _ in range(cantidad_palabras)]


def sintetizar_hibrido_con_referencia_dinamica(texto, partitura_dinamica, ogg_salida="resp.ogg"):
    wav_temp_timbre = "temp_timbre_bark.wav"
    wav_temp_final = "temp_dinamica_final.wav"
    sample_rate = 24000

    # 1. Timbre base con Bark
    timbre_ok = False
    if BARK_DISPONIBLE:
        try:
            print("🎙️ [TIMBRE BARK]: Sintetizando textura vocal base...")
            processor = AutoProcessor.from_pretrained("suno/bark-small")
            model = BarkModel.from_pretrained("suno/bark-small")
            device = "cpu"
            model = model.to(device)

            inputs = processor(f"[es] {texto[:180]}", voice_preset="v2/es_speaker_2").to(device)
            with torch.no_grad():
                audio_bark = model.generate(**inputs)
            
            audio_bark = audio_bark.cpu().numpy().squeeze()
            sf.write(wav_temp_timbre, audio_bark, sample_rate)
            timbre_ok = os.path.exists(wav_temp_timbre)
        except Exception as e:
            print(f"⚠️ Error en timbre Bark: {e}")

    if not timbre_ok:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=140:duration=4", wav_temp_timbre], check=True)

    # 2. Aplicar Dinámica Cuantitativa con bucle circular seguro
    try:
        print("🎛️ [DINÁMICA]: Aplicando métricas cuantitativas al fraseo...")
        data_timbre, sr = sf.read(wav_temp_timbre)
        audio_dinamico = np.array([], dtype=np.float32)
        
        if not partitura_dinamica:
            partitura_dinamica = [{"duracion_ms": 150, "intensidad_db": 0.0} for _ in texto.split()]

        indice_audio = 0
        for item in partitura_dinamica:
            duracion_ms = item.get("duracion_ms", 150)
            intensidad_db = item.get("intensidad_db", 0.0)
            
            muestras_bloque = int(sr * (duracion_ms / 1000.0))
            if muestras_bloque <= 0:
                continue
                
            if indice_audio + muestras_bloque <= len(data_timbre):
                fragmento = data_timbre[indice_audio:indice_audio + muestras_bloque]
                indice_audio += muestras_bloque
            else:
                indice_audio = 0
                fragmento = data_timbre[indice_audio:indice_audio + muestras_bloque]
                indice_audio += muestras_bloque
                
            mult_vol = 10 ** (intensidad_db / 20.0)
            fragmento_modulado = fragmento * mult_vol
            audio_dinamico = np.concatenate((audio_dinamico, fragmento_modulado))

        if len(audio_dinamico) == 0:
            audio_dinamico = data_timbre

        sf.write(wav_temp_final, audio_dinamico, sr)
    except Exception as e:
        print(f"⚠️ Error aplicando dinámica: {e}")
        subprocess.run(["cp", wav_temp_timbre, wav_temp_final], check=True)

    # 3. Masterización FM con FFmpeg
    filtros = [
        "dynaudnorm=f=125:g=15:p=0.9",
        "equalizer=f=90:t=h:w=100:g=3.0",
        "equalizer=f=3500:t=h:w=300:g=4.0",
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
            
    print("✅ [PROCESO HÍBRIDO]: Audio completo generado con éxito.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot híbrido activo con timbre de Bark y registro de entrenamiento JSON.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    await update.message.chat.send_action(action="record_voice")
    
    respuesta_texto = llamar_ia_externa_o_local(texto_usuario)
    texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta_texto)
    texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

    url_potencial = next((w for w in texto_usuario.split() if w.startswith("http")), "sin_url")
    cantidad_palabras = len(texto_limpio.split())
    partitura_dinamica = obtener_wav_de_la_web_o_sintetico(url_potencial, cantidad_palabras)

    ogg_f = "resp.ogg"
    sintetizar_hibrido_con_referencia_dinamica(texto_limpio, partitura_dinamica, ogg_f)

    with open(ogg_f, "rb") as vf:
        await update.message.reply_voice(voice=vf, caption="🎙️ *(Timbre Bark + Métricas Dinámicas)*")

    if os.path.exists(ogg_f): 
        os.remove(ogg_f)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        
        path_ogg = os.path.join(CARPETA_MUESTRAS, f"audio_usuario_{update.message.message_id}.ogg")
        path_wav = os.path.join(CARPETA_MUESTRAS, f"audio_usuario_{update.message.message_id}.wav")
        
        await file.download_to_drive(path_ogg)

        # Convertir a .wav usando FFmpeg
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", path_ogg,
                "-ar", "22050", "-ac", "1", path_wav
            ], check=True)
        except Exception as e:
            print(f"⚠️ Error convirtiendo .ogg a .wav: {e}")

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_ogg, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip()

        if not texto_crudo:
            await update.message.reply_text("Che, no te capté bien el audio.")
            return

        # Registrar entrenamiento en el JSON
        registrar_entrenamiento_json(path_wav if os.path.exists(path_wav) else path_ogg, texto_crudo)

        respuesta = llamar_ia_externa_o_local(texto_crudo)
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

        cantidad_palabras = len(texto_limpio.split())
        if os.path.exists(path_wav):
            partitura_dinamica = extraer_metricas_de_wav(path_wav, cantidad_palabras)
        else:
            partitura_dinamica = [{"duracion_ms": 150, "intensidad_db": 0.0} for _ in range(cantidad_palabras)]

        ogg_f = "resp.ogg"
        sintetizar_hibrido_con_referencia_dinamica(texto_limpio, partitura_dinamica, ogg_f)

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"🗣️ ¡EntRENAMIENTO REGISTRADO! Clavando tu ritmo.")

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
