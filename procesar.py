"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo para GitHub Actions: procesar.py
- Análisis e integración de dB (intensidad/volumen) y Cadencia (ritmo).
- Lectura/escritura blindada de conversaciones.txt con file_lock.
- Búsqueda web real (DuckDuckGo) e historial en dataset_entrenamiento_chat.json.
- Mapeo dinámico de DSP Rubberband + Ecualización basada en tus métricas.
"""

import asyncio
json_lib = __import__('json')
import os
import re
import sys
import math
import threading
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
FILE_DATASET = "dataset_entrenamiento_chat.json"
FILE_METRICAS_GENERALES = "metricas_entrenamiento.json"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

if not os.path.exists(TXT_FILE):
    try:
        with open(TXT_FILE, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sistema: Bitácora iniciada.\n")
    except Exception as e:
        print(f"⚠️ Error creando conversaciones.txt: {e}")

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

lock_voz = asyncio.Lock()
file_lock = threading.Lock()
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
# SYSTEM PROMPT
# =====================================================================
SYSTEM_PROMPT = (
    "Sos Leandro, un compañero y colega de Telegram. Hablás en perfecto español rioplatense (porteño) con voseo natural ('che', 'vós', 'fijate', 'posta').\n"
    "REGLA DE TONO Y TIMBRE: Evaluá la petición del usuario para definir el tono de voz:\n"
    "- Si pide 'voz más grave', 'tachero', 'profundo', 'nocturno' -> pitch_factor: 0.72\n"
    "- Si pide 'voz normal', 'colega', 'estándar' -> pitch_factor: 0.88\n"
    "- Si pide 'voz aguda' o 'rápida' -> pitch_factor: 1.05\n"
    "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown):\n"
    "{\n"
    '  "texto_completo": "Tu respuesta redactada con la personalidad solicitada y acento porteño",\n'
    '  "pitch_factor": 0.88,\n'
    '  "ganancia_db": 0.0\n'
    "}"
)

# --- MANEJO BLINDADO DE conversaciones.txt ---
def obtener_historial_adaptativo(cant_lineas=60):
    with file_lock:
        if not os.path.exists(TXT_FILE):
            return ""
        try:
            try:
                with open(TXT_FILE, "r", encoding="utf-8") as f:
                    lineas = f.readlines()
            except UnicodeDecodeError:
                with open(TXT_FILE, "r", encoding="latin-1", errors="ignore") as f:
                    lineas = f.readlines()
            
            recientes = [l.strip() for l in lineas[-cant_lineas:] if l.strip()]
            return "\n".join(recientes)
        except Exception as e:
            print(f"⚠️ Error leyendo {TXT_FILE}: {e}")
            return ""

def registrar_conversacion(remitente, texto):
    with file_lock:
        try:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            linea = f"[{ts}] {remitente}: {texto}\n"
            with open(TXT_FILE, "a", encoding="utf-8") as f:
                f.write(linea)
                f.flush()
                os.fsync(f.fileno())
            print(f"📝 [TXT REGISTRADO]: {remitente}: {texto[:50]}...")
        except Exception as e:
            print(f"⚠️ Error escribiendo en {TXT_FILE}: {e}")

def registrar_ejemplo_entrenamiento(prompt_usuario, respuesta_bot, resultados_web="", origen_modelo="gemini"):
    try:
        ejemplo = {
            "timestamp": datetime.now().isoformat(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_usuario},
                {"role": "assistant", "content": respuesta_bot}
            ],
            "metadata": {
                "modelo_usado": origen_modelo,
                "contexto_web_incluido": bool(resultados_web)
            }
        }
        with open(FILE_DATASET, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps(ejemplo, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"⚠️ Error guardando en {FILE_DATASET}: {e}")

# --- MÓDULO DE BÚSQUEDA WEB REAL ---
def buscar_en_la_web(query):
    try:
        print(f"🌐 [WEB SEARCH]: Buscando en la web: '{query}'...", flush=True)
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
            limpios = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:3]]
            if limpios:
                return "\n".join(limpios)
    except Exception as e:
        print(f"⚠️ Error en búsqueda web: {e}")
    return ""

def registrar_metricas_voz_usuario(path_audio_ogg, texto_transcripto):
    try:
        wav_tmp = f"tmp_analisis_{int(time.time())}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", path_audio_ogg, "-ar", "16000", "-ac", "1", wav_tmp
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        intensidad_db_estimada = -18.0
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

        partitura = [{
            "palabra": p,
            "duracion_ms": duracion_promedio_palabra,
            "intensidad_db": intensidad_db_estimada
        } for p in palabras]

        nueva_entrada = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
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
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"⚠️ Error actualizando métricas de voz: {e}")

def obtener_metricas_calibracion():
    """Calcula el tempo (cadencia) e intensidad promedio (dB) acumulada de tus audios."""
    calibracion = {"tempo_factor": 1.0, "gain_db": 0.0, "intensidad_promedio": -18.0}
    if not os.path.exists(FILE_METRICAS_VOZ):
        return calibracion
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
            prom_duracion = sum(duraciones) / len(duraciones)
            prom_intensidad = sum(intensidades) / len(intensidades)
            
            tempo_calibrado = 350.0 / max(prom_duracion, 150.0)
            tempo_calibrado = max(0.8, min(tempo_calibrado, 1.25))
            
            calibracion["tempo_factor"] = round(tempo_calibrado, 2)
            calibracion["intensidad_promedio"] = round(prom_intensidad, 2)
            calibracion["gain_db"] = round(max(-6.0, min(6.0, (-18.0 - prom_intensidad))), 2)
    except Exception as e:
        print(f"⚠️ Error leyendo calibración: {e}")
    return calibracion

def generar_respuesta_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    
    historial_previo = obtener_historial_adaptativo(60)

    contexto_web = ""
    if any(kw in prompt_usuario.lower() for kw in ["buscá", "busca", "encontrá", "noticias", "web", "qué pasó", "quien es", "como se", "info"]):
        snippets = buscar_en_la_web(prompt_usuario)
        if snippets:
            contexto_web = f"[RESULTADOS WEB]:\n{snippets}\n"

    pitch_estimado = 0.88
    if any(kw in prompt_usuario.lower() for kw in ["grave", "tachero", "profundo", "baja el tono"]):
        pitch_estimado = 0.72
    elif any(kw in prompt_usuario.lower() for kw in ["agudo", "rápido", "fino"]):
        pitch_estimado = 1.05

    resultado = {
        "texto_completo": "De una che, te capté.",
        "pitch_factor": pitch_estimado,
        "ganancia_db": 0.0
    }
    modelo_usado = "local"

    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            partes_adjuntas = []
            if historial_previo:
                partes_adjuntas.append({"text": f"--- ADJUNTO: HISTORIAL DE CHARLA ---\n{historial_previo}\n--- FIN ADJUNTO ---"})
            if contexto_web:
                partes_adjuntas.append({"text": contexto_web})
            
            partes_adjuntas.append({"text": f"Mensaje actual: {prompt_usuario}"})

            res = client.models.generate_content(
                model=MODELO_GEMINI,
                contents=partes_adjuntas,
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
                if data.get("texto_completo"):
                    resultado["texto_completo"] = str(data.get("texto_completo")).strip()
                    if "pitch_factor" in data: resultado["pitch_factor"] = float(data["pitch_factor"])
                    if "ganancia_db" in data: resultado["ganancia_db"] = float(data["ganancia_db"])
                    modelo_usado = "gemini"
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "QuotaExceeded" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True

    if modelo_usado == "local":
        prompt_fallback = f"Historial adjunto:\n{historial_previo}\n{contexto_web}\nMensaje: {prompt_usuario}"
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_fallback}
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
                if data.get("texto_completo"):
                    resultado["texto_completo"] = str(data.get("texto_completo")).strip()
                    if "pitch_factor" in data: resultado["pitch_factor"] = float(data["pitch_factor"])
                    if "ganancia_db" in data: resultado["ganancia_db"] = float(data["ganancia_db"])
                    modelo_usado = "llama"
        except Exception as ex_local:
            print(f"⚠️ Error en Llama local: {ex_local}")

    registrar_ejemplo_entrenamiento(prompt_usuario, resultado["texto_completo"], contexto_web, modelo_usado)

    return resultado

# ==========================================
# SÍNTESIS DSP CON CADENCIA Y INTENSIDAD (dB)
# ==========================================
def sintetizar_voz_dinamica(texto, pitch_prompt=0.85, ganancia_prompt=0.0, ogg_salida="resp.ogg"):
    try:
        calibracion = obtener_metricas_calibracion()
        tempo_f = calibracion["tempo_factor"]
        gain_final = ganancia_prompt if ganancia_prompt != 0.0 else calibracion["gain_db"]

        mp3_tmp = "tmp_base.mp3"
        gTTS(text=texto, lang="es", tld="com.ar").save(mp3_tmp)
        
        # Filtro de ecualización ajustado por intensidad de dB
        eq_gain = 5.0 if calibracion["intensidad_promedio"] < -20.0 else 3.0
        filtro_eq = f",equalizer=f=140:width_type=h:width=100:g={eq_gain}" if pitch_prompt < 0.80 else ""
        
        filtro_dsp = f"rubberband=pitch={pitch_prompt}:tempo={tempo_f}:formant=preserved:transients=smooth{filtro_eq},volume={gain_final}dB,highpass=f=80,lowpass=f=4500"
        
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
        print(f"⚠️ Error en síntesis DSP: {e}")
        if os.path.exists(mp3_tmp):
            os.remove(mp3_tmp)
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text(f"¡Buenas che! Chat ID `{CHAT_ID_ACTIVO}` fijado correctamente.", parse_mode="Markdown")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text or update.message.caption or "[Texto recibido]"
    
    registrar_conversacion("Usuario", u_text)

    res_ia = generar_respuesta_ia(u_text)
    resp = res_ia["texto_completo"]
    pitch_val = res_ia["pitch_factor"]
    gain_val = res_ia["ganancia_db"]

    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = "resp.ogg"
    if sintetizar_voz_dinamica(resp, pitch_prompt=pitch_val, ganancia_prompt=gain_val, ogg_salida=ogg_f):
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

        res_ia = generar_respuesta_ia(texto_crudo)
        resp = res_ia["texto_completo"]
        pitch_val = res_ia["pitch_factor"]
        gain_val = res_ia["ganancia_db"]

        registrar_conversacion("LeandroBot", resp)
        await update.message.reply_text(resp)

        ogg_f = "resp.ogg"
        if sintetizar_voz_dinamica(resp, pitch_prompt=pitch_val, ganancia_prompt=gain_val, ogg_salida=ogg_f):
            with open(ogg_f, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption=f"*(Interpretado: {texto_crudo})*")
            if os.path.exists(ogg_f):
                os.remove(ogg_f)

def asegurar_e_iniciar_ollama():
    try:
        res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3)
        if res.status_code == 200: return
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

    print("🚀 [INIT]: Configurando LeandroBot (Métricas dB + Cadencia + FileLock)...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    app = Application.builder().token(TOKEN).request(request_config).build()
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
