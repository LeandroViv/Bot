"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo para GitHub Actions: procesar.py
- Personaje e iniciativa espontánea 100% prompteables desde SYSTEM_PROMPT.
- Síntesis de voz siempre procesada con DSP Rubberband y tu historial_metricas_voz.json.
- Transcripción con Faster-Whisper y actualización acumulativa de tu dataset métrico.
"""

import asyncio
json_lib = __import__('json')
import os
import re
import sys
import math
import random
import subprocess
import requests
import time
from datetime import datetime

# --- INYECCIÓN AUTOMÁTICA DE HF_TOKEN ---
hf_token = os.environ.get("HF_TOKEN")
if hf_token:
    os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
    print("🔑 [HUGGING FACE]: Token detectado e inyectado correctamente.")
# ----------------------------------------

print("🚀 [INIT]: Inicializando LeandroBot en GitHub Actions...", flush=True)

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
from gtts import gTTS
import soundfile as sf

TXT_FILE = "conversaciones.txt"
MEMORIA_TAREAS = "memoria_tareas.json"
CARPETA_MUESTRAS = "muestras_voz"
FILE_METRICAS_VOZ = "historial_metricas_voz.json"
FILE_DATASET = "dataset_entrenamiento.jsonl"
FILE_METRICAS_GENERALES = "metricas_entrenamiento.json"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

if not os.path.exists(MEMORIA_TAREAS):
    with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

if not os.path.exists(FILE_METRICAS_GENERALES):
    with open(FILE_METRICAS_GENERALES, "w", encoding="utf-8") as f:
        json_lib.dump({"total_interacciones": 0, "gemini_exitos": 0, "llama_exitos": 0, "audios_procesados": 0}, f, indent=4)

if not os.path.exists(FILE_METRICAS_VOZ):
    with open(FILE_METRICAS_VOZ, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

ENV_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHAT_ID_ACTIVO = int(ENV_CHAT_ID) if ENV_CHAT_ID and ENV_CHAT_ID.strip().isdigit() else None

if CHAT_ID_ACTIVO:
    print(f"🎯 [SECRETS]: CHAT_ID cargado exitosamente: {CHAT_ID_ACTIVO}")
else:
    print("⚠️ [SECRETS]: TELEGRAM_CHAT_ID no encontrado en secretos. Se capturará con el primer mensaje.")

lock_voz = asyncio.Lock()
GEMINI_BLOQUEADO_POR_CUOTA = False
MODELO_GEMINI = "gemini-2.0-flash"

client = None
try:
    from google import genai
    if GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ [GEMINI]: Cliente GenAI inicializado correctamente.")
except Exception as e:
    print(f"⚠️ [GEMINI ERROR]: {e}")

# =====================================================================
# SYSTEM PROMPT TOTALMENTE PROMPTEABLE
# (Cambiá la personalidad o las reglas de espontaneidad cuando quieras)
# =====================================================================
SYSTEM_PROMPT = os.environ.get(
    "CUSTOM_SYSTEM_PROMPT",
    "Sos Leandro, un colega y compañero de charlas por Telegram. Sos directo, cálido y hablas en perfecto español rioplatense (porteño), "
    "usando voseo natural ('che', 'vós sabés', 'fijate', 'posta', 'de una') y lunfardo sutil.\n"
    "REGLA DE PERSONAJE: Podés adoptar el rol que se te pida (un campesino, un programador, un locutor, etc.) según el contexto.\n"
    "REGLA ESPONTÁNEA: Si tenés activada la iniciativa en tus instrucciones, podés mandar un mensaje o reflexión por tu cuenta si descubrís algo interesante.\n"
    "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown):\n"
    "{\n"
    '  "texto_completo": "Tu respuesta redactada según el personaje y con acentuación porteña",\n'
    '  "canal_salida": "ambos"\n'
    "}"
)

def registrar_metricas_voz_usuario(path_audio_ogg, texto_transcripto):
    try:
        wav_tmp = f"tmp_analisis_{int(time.time())}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", path_audio_ogg, "-ar", "16000", "-ac", "1", wav_tmp
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        intensidad_db_estimada = -2.0
        duracion_total_ms = 1000

        if os.path.exists(wav_tmp):
            data, samplerate = sf.read(wav_tmp)
            duracion_total_ms = int((len(data) / samplerate) * 1000)
            
            rms = math.sqrt(sum(data**2) / len(data)) if len(data) > 0 else 0.0001
            intensidad_db_estimada = round(20 * math.log10(max(rms, 0.0001)), 2)
            os.remove(wav_tmp)

        palabras = texto_transcripto.split()
        cant_palabras = len(palabras) if palabras else 1
        duracion_promedio_palabra = max(150, int(duracion_total_ms / cant_palabras))

        partitura = []
        for p in palabras:
            partitura.append({
                "palabra": p,
                "duracion_ms": duracion_promedio_palabra,
                "intensidad_db": intensidad_db_estimada
            })

        nueva_entrada = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "tipo": "voz_usuario",
            "archivo": path_audio_ogg,
            "texto": texto_transcripto,
            "partitura_metrica": partitura
        }

        historial = []
        if os.path.exists(FILE_METRICAS_VOZ):
            try:
                with open(FILE_METRICAS_VOZ, "r", encoding="utf-8") as f:
                    historial = json_lib.load(f)
            except Exception:
                historial = []

        historial.append(nueva_entrada)
        with open(FILE_METRICAS_VOZ, "w", encoding="utf-8") as f:
            json_lib.dump(historial, f, indent=4, ensure_ascii=False)

        print(f"📈 [HISTORIAL METRICAS]: Agregadas {cant_palabras} palabras nuevas a {FILE_METRICAS_VOZ}.")
    except Exception as e:
        print(f"⚠️ Error actualizando {FILE_METRICAS_VOZ}: {e}")

def obtener_calibracion_personalizada():
    calibracion_por_defecto = {"tempo_factor": 1.0, "gain_db": 0.0}
    if not os.path.exists(FILE_METRICAS_VOZ):
        return calibracion_por_defecto
    try:
        with open(FILE_METRICAS_VOZ, "r", encoding="utf-8") as f:
            datos = json_lib.load(f)
        
        duraciones = []
        intensidades = []
        
        for entrada in datos:
            for metrica in entrada.get("partitura_metrica", []):
                if "duracion_ms" in metrica:
                    duraciones.append(metrica["duracion_ms"])
                if "intensidad_db" in metrica:
                    intensidades.append(metrica["intensidad_db"])
        
        if duraciones and intensidades:
            promedio_duracion = sum(duraciones) / len(duraciones)
            promedio_intensidad = sum(intensidades) / len(intensidades)
            
            tempo_calibrado = 350.0 / max(promedio_duracion, 150.0)
            tempo_calibrado = max(0.8, min(tempo_calibrado, 1.25))
            
            return {"tempo_factor": round(tempo_calibrado, 2), "gain_db": round(promedio_intensidad, 2)}
    except Exception as e:
        print(f"⚠️ Error leyendo calibración: {e}")
    
    return calibracion_por_defecto

def registrar_ejemplo_entrenamiento(prompt_usuario, respuesta_bot, origen_modelo="gemini"):
    try:
        ejemplo = {
            "timestamp": datetime.now().isoformat(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_usuario},
                {"role": "assistant", "content": respuesta_bot}
            ],
            "metadata": {"modelo_usado": origen_modelo}
        }
        with open(FILE_DATASET, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps(ejemplo, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️ Error guardando dataset: {e}")

def actualizar_metricas_generales(modelo_usado):
    try:
        with open(FILE_METRICAS_GENERALES, "r", encoding="utf-8") as f:
            m = json_lib.load(f)
        m["total_interacciones"] = m.get("total_interacciones", 0) + 1
        if modelo_usado == "gemini":
            m["gemini_exitos"] = m.get("gemini_exitos", 0) + 1
        elif modelo_usado == "llama":
            m["llama_exitos"] = m.get("llama_exitos", 0) + 1
        with open(FILE_METRICAS_GENERALES, "w", encoding="utf-8") as f:
            json_lib.dump(m, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error actualizando métricas generales: {e}")

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}\n")
    except Exception as e:
        print(f"⚠️ Error conversacion: {e}")

def generar_texto_ia(prompt_usuario, es_proactivo=False):
    global GEMINI_BLOQUEADO_POR_CUOTA
    p = prompt_usuario
    if es_proactivo:
        p = f"Iniciás vos la charla espontáneamente según tu personaje asignado sobre este motivo: {prompt_usuario}."

    respuesta = ""
    modelo_usado = "local"

    # 1. Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            res = client.models.generate_content(
                model=MODELO_GEMINI,
                contents=p,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json"
                }
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
                    modelo_usado = "gemini"
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "QuotaExceeded" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
            else:
                print(f"⚠️ Gemini falló, conmutando a Llama: {e}")

    # 2. Fallback a Llama (Ollama local)
    if not respuesta:
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": p}
            ],
            "format": "json",
            "options": {"num_ctx": 4096, "temperature": 0.7},
            "stream": False,
        }
        try:
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            res_local = requests.post(url_llama, json=payload, timeout=20)
            if res_local.status_code == 200:
                content_str = res_local.json().get("message", {}).get("content", "{}")
                content_str = re.sub(r'^```json\s*', '', content_str, flags=re.IGNORECASE)
                content_str = re.sub(r'^```\s*', '', content_str)
                content_str = re.sub(r'\s*```$', '', content_str).strip()
                data = json_lib.loads(content_str)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    respuesta = str(texto).strip()
                    modelo_usado = "llama"
        except Exception as ex_local:
            print(f"⚠️ Error en Llama local: {ex_local}")

    if not respuesta or not str(respuesta).strip():
        respuesta = "De una che, te capté perfecto. Sintonizados."

    actualizar_metricas_generales(modelo_usado)
    registrar_ejemplo_entrenamiento(prompt_usuario, respuesta, modelo_usado)

    return respuesta

# ==========================================
# SÍNTESIS DSP CON RUBBERBAND Y MÉTRICAS PROPIAS
# ==========================================
VOZ_ESTILO_PERSONALIZADO = os.environ.get(
    "VOZ_ESTILO",
    "Voz masculina natural, cálida y pausada de Buenos Aires"
)
VOZ_BASE_NOMBRE = os.environ.get("VOZ_BASE", "Charon")

def sintetizar_voz_gemini(texto, ogg_salida="resp.ogg"):
    if not client or GEMINI_BLOQUEADO_POR_CUOTA:
        return False
    try:
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=[{"role": "user", "parts": [{"text": texto, "speechMetadata": {"style": VOZ_ESTILO_PERSONALIZADO}}] }],
            config={
                "response_modalities": ["AUDIO"],
                "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": VOZ_BASE_NOMBRE}}}
            }
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

def sintetizar_voz_con_calibracion_propia(texto, ogg_salida="resp.ogg"):
    try:
        calibracion = obtener_calibracion_personalizada()
        tempo_f = calibracion["tempo_factor"]
        gain_db = calibracion["gain_db"]

        mp3_tmp = "tmp_base.mp3"
        gTTS(text=texto, lang="es", tld="com.ar").save(mp3_tmp)
        
        filtro_dsp = f"rubberband=pitch=0.88:tempo={tempo_f}:formant=preserved:transients=smooth,volume={gain_db}dB,highpass=f=100,lowpass=f=4500"
        
        cmd_ffmpeg = [
            "ffmpeg", "-y", "-i", mp3_tmp,
            "-af", filtro_dsp,
            "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ]
        
        subprocess.run(cmd_ffmpeg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        if os.path.exists(mp3_tmp):
            os.remove(mp3_tmp)
        return os.path.exists(ogg_salida)
    except Exception as e:
        print(f"⚠️ Error en síntesis propia: {e}")
        if os.path.exists(mp3_tmp):
            os.remove(mp3_tmp)
        return False

async def sintetizar_voz(texto, ogg_salida="resp.ogg"):
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            if sintetizar_voz_gemini(texto, ogg_salida):
                return True
        except Exception:
            pass
    
    return sintetizar_voz_con_calibracion_propia(texto, ogg_salida)

# --- BUCLE ESPONTÁNEO PROMPTEABLE ---
async def bucle_espontaneo_prompteable(bot_app: Application):
    """Evalúa si en el SYSTEM_PROMPT le indicaste que tenga iniciativa propia."""
    print("⚡ [PROACTIVO]: Verificando reglas del System Prompt...", flush=True)
    await asyncio.sleep(25)

    while True:
        try:
            await asyncio.sleep(1800) # Chequeo cada 30 minutos

            global CHAT_ID_ACTIVO
            if not CHAT_ID_ACTIVO:
                continue

            # Solo dispara si el prompt del sistema le autoriza la iniciativa propia
            if "espontáne" in SYSTEM_PROMPT.lower() or "iniciativa" in SYSTEM_PROMPT.lower() or "proactivo" in SYSTEM_PROMPT.lower():
                print(f"🎙️ [ESPONTÁNEO]: Disparando mensaje según prompt...", flush=True)
                motivo = "Pensamiento o novedad según tu personaje asignado"
                texto_spont = generar_texto_ia(motivo, es_proactivo=True)
                registrar_conversacion("Leandro (Espontáneo)", texto_spont)

                await bot_app.bot.send_message(chat_id=CHAT_ID_ACTIVO, text=texto_spont)

                ogg_f = "espontaneo.ogg"
                if await sintetizar_voz(texto_spont, ogg_f):
                    with open(ogg_f, "rb") as vf:
                        await bot_app.bot.send_voice(chat_id=CHAT_ID_ACTIVO, voice=vf)
                    if os.path.exists(ogg_f):
                        os.remove(ogg_f)

        except Exception as e:
            print(f"⚠️ Error en bucle espontáneo: {e}", flush=True)
            await asyncio.sleep(60)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text(f"¡Buenas che! Quedamos sintonizados en el Chat ID `{CHAT_ID_ACTIVO}`.", parse_mode="Markdown")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
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
    global CHAT_ID_ACTIVO
    async with lock_voz:
        if not update.message:
            return
        CHAT_ID_ACTIVO = update.message.chat_id

        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()

        nombre_archivo = f"audio_usuario_{update.message.message_id}.ogg"
        path_in = os.path.join(CARPETA_MUESTRAS, nombre_archivo)
        await file.download_to_drive(path_in)

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip() or "Che, te mandé un audio."

        registrar_metricas_voz_usuario(path_in, texto_crudo)

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

def asegurar_e_iniciar_ollama():
    try:
        res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3)
        if res.status_code == 200:
            return
    except Exception:
        pass

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

    print("🚀 [INIT]: Configurando LeandroBot con Telegram (Polling continuo)...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    async def post_init(application: Application):
        asyncio.create_task(bucle_espontaneo_prompteable(application))

    app = Application.builder().token(TOKEN).request(request_config).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    while True:
        try:
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            print(f"⚠️ Conexión interrumpida ({e}). Reconectando en 5 segundos...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
