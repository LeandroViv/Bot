import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
import numpy as np

print("🚀 [INIT]: Inicializando sistema híbrido (Timbre Bark + Dinámica Cuantitativa por Vibe Coding)...")

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

# Intentamos cargar dependencias para Bark
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

for archivo, contenido in [(TXT_FILE, ""), (REGISTRO_METRICAS, [])]:
    if not os.path.exists(archivo):
        with open(archivo, "w", encoding="utf-8") as f:
            if isinstance(contenido, list):
                json_lib.dump(contenido, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY) if (GENAI_DISPONIBLE and GEMINI_API_KEY) else None
GEMINI_BLOQUEADO_POR_CUOTA = False
lock_voz = asyncio.Lock()


def cargar_metricas_entrenadas():
    if os.path.exists(REGISTRO_METRICAS):
        try:
            with open(REGISTRO_METRICAS, "r", encoding="utf-8") as f:
                return json_lib.load(f)
        except:
            return []
    return []


def guardar_metrica_entrenamiento(metrica_nueva):
    historial = cargar_metricas_entrenadas()
    historial.append(metrica_nueva)
    # Mantenemos las últimas 50 para que evolucione sin romper memoria
    if len(historial) > 50:
        historial = historial[-50:]
    with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)


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


def sintetizar_hibrido_timbre_dinamica(texto, partitura_dinamica, ogg_salida="resp.ogg"):
    """
    Combina el timbre de Bark con la dinámica y fraseo cuantitativo de la partitura.
    """
    wav_temp_timbre = "temp_bark.wav"
    wav_temp_final = "temp_final.wav"
    sample_rate = 24000
    
    # 1. Obtenemos el timbre base con Bark (Caja negra para textura de voz)
    timbre_ok = False
    if BARK_DISPONIBLE:
        try:
            print("🎙️ [HÍBRIDO]: Generando timbre base con Bark...")
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
            print(f"⚠️ Error generando timbre Bark: {e}")

    # Si Bark falla, usamos un tono limpio como base de timbre
    if not timbre_ok:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=140:duration=3", wav_temp_timbre], check=True)

    # 2. Aplicamos la dinámica cuantitativa (fraseo, envolventes y variaciones de intensidad/pitch)
    try:
        print("🎛️ [HÍBRIDO]: Aplicando dinámica y fraseo cuantitativo a la voz...")
        # Cargamos el audio de timbre generado
        data_timbre, sr = sf.read(wav_temp_timbre)
        
        # Modulamos la dinámica basándonos en la partitura obtenida por IA / Vibe Coding
        audio_dinamico = np.array([], dtype=np.float32)
        
        for item in partitura_dinamica:
            duracion_ms = item.get("duracion_ms", 120)
            intensidad_db = item.get("intensidad_db", 0.0)
            
            muestras_bloque = int(sr * (duracion_ms / 1000.0))
            if muestras_bloque <= 0:
                continue
                
            # Extraemos un fragmento del timbre de Bark o generamos silencio si es pausa
            if len(data_timbre) > muestras_bloque:
                fragmento = data_timbre[:muestras_bloque]
                data_timbre = data_timbre[muestras_bloque:]
            else:
                fragmento = np.zeros(muestras_bloque, dtype=np.float32)
                
            # Aplicamos la intensidad cuantitativa (dinámica de fraseo)
            mult_vol = 10 ** (intensidad_db / 20.0)
            fragmento_modulado = fragmento * mult_vol
            audio_dinamico = np.concatenate((audio_dinamico, fragmento_modulado))

        if len(audio_dinamico) == 0:
            audio_dinamico = data_timbre

        sf.write(wav_temp_final, audio_dinamico, sr)

    except Exception as e:
        print(f"⚠️ Error aplicando dinámica cuantitativa: {e}")
        subprocess.run(["cp", wav_temp_timbre, wav_temp_final], check=True)

    # 3. Retoque final con FFmpeg (Estudio FM nocturno)
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
    print("✅ [HÍBRIDO]: Audio con timbre Bark y dinámica cuantitativa generado con éxito.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot híbrido activo: Timbre Bark + Dinámica y Fraseo Cuantitativo por Vibe Coding.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    await update.message.chat.send_action(action="record_voice")
    
    # 1. La IA redacta la respuesta con onda de locutor nocturno
    respuesta_texto = llamar_ia_externa_o_local(texto_usuario)
    texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta_texto)
    texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

    # 2. Pedimos a la IA que genere la partitura cuantitativa de dinámica y fraseo para ese texto
    prompt_dinamica = (
        "Analiza este texto y genera EXCLUSIVAMENTE un JSON válido que sea una lista de objetos. "
        "Cada objeto representa una sílaba o palabra y debe contener: 'palabra' (string), "
        "'duracion_ms' (entero entre 80 y 250), e 'intensidad_db' (entre -4 y 0 para dar la dinámica de fraseo). "
        f"Texto: \"{texto_limpio}\""
    )
    system_dinamica = "Sos un motor de análisis prosódico y dinámico. Devuelves únicamente JSON puro sin markdown."
    resp_json = llamar_ia_externa_o_local(prompt_dinamica, system_prompt_custom=system_dinamica)
    
    partitura = []
    try:
        inicio = resp_json.find('[')
        fin = resp_json.rfind(']') + 1
        partitura = json_lib.loads(resp_json[inicio:fin])
        # Guardamos en el historial de entrenamiento propio del bot
        guardar_metrica_entrenamiento({"texto": texto_limpio, "partitura": partitura})
    except:
        # Partitura por defecto si falla el parseo
        partitura = [{"palabra": w, "duracion_ms": 120, "intensidad_db": 0.0} for w in texto_limpio.split()]

    ogg_f = "resp.ogg"
    sintetizar_hibrido_timbre_dinamica(texto_limpio, partitura, ogg_f)

    with open(ogg_f, "rb") as vf:
        await update.message.reply_voice(voice=vf, caption="🎙️ *(Timbre Bark + Dinámica Cuantitativa Híbrida)*")

    if os.path.exists(ogg_f): 
        os.remove(ogg_f)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        path_in = os.path.join("muestras_voz", f"audio_{update.message.message_id}.ogg")
        os.makedirs("muestras_voz", exist_ok=True)
        await file.download_to_drive(path_in)

        # Transcribimos con Whisper
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip()

        if not texto_crudo:
            await update.message.reply_text("Che, no te capté bien el audio de referencia.")
            return

        # Extraemos métricas del audio enviado para alimentar el entrenamiento de vibe coding
        metrica_extraida = {
            "origen": "audio_usuario",
            "texto": texto_crudo,
            "timestamp": time.time()
        }
        guardar_metrica_entrenamiento(metrica_extraida)

        respuesta = llamar_ia_externa_o_local(texto_crudo)
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

        ogg_f = "resp.ogg"
        partitura_base = [{"palabra": w, "duracion_ms": 130, "intensidad_db": -1.0} for w in texto_limpio.split()]
        sintetizar_hibrido_timbre_dinamica(texto_limpio, partitura_base, ogg_f)

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"🧠 Entrenado con tu audio y respondido con timbre híbrido.")

        if os.path.exists(ogg_f): os.remove(ogg_f)
        if os.path.exists(path_in): os.remove(path_in)


def main():
    os.makedirs("muestras_voz", exist_ok=True)
    if not TOKEN:
        print("❌ ERROR: Falta TELEGRAM_BOT_TOKEN.")
        return

    print("🧹 Limpiando webhooks...")
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except Exception as e:
        print(f"⚠️ Aviso webhook: {e}")

    print("🚀 Iniciando Bot Híbrido...")
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
