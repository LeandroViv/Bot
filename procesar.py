"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo para GitHub Actions: procesar.py
- Memoria contextual integrada leyendo y escribiendo conversaciones.txt con Lock.
- Parser de texto directo y fluido (sin JSON estricto para evitar bloqueos).
- Búsqueda web real en tiempo real (DuckDuckGo).
- Síntesis DSP con Rubberband controlando cadencia y dB según métricas.
- Sincronización automática con Git / GitHub Actions.
"""

import asyncio
json_lib = __import__('json')
import os
import re
import sys
import math
import difflib
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

print("🚀 [INIT]: Inicializando LeandroBot con Autonomía y DSP...", flush=True)

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
from google import genai
from gtts import gTTS
import soundfile as sf

TXT_FILE = "conversaciones.txt"
REGISTRO_INDUCCION = "historial_induccion.json"
REGISTRO_REFINAMIENTO = "historial_refinamiento.json"
FILE_METRICAS_VOZ = "historial_metricas_voz.json"
FILE_DATASET = "dataset_entrenamiento_chat.json"
CARPETA_MUESTRAS = "muestras_voz"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

# Lock físico de hilos para evitar colisiones en archivos de texto
file_lock = threading.Lock()

for archivo_base, contenido_inicial in [
    (REGISTRO_INDUCCION, {}),
    (REGISTRO_REFINAMIENTO, []),
    (FILE_METRICAS_VOZ, []),
    (TXT_FILE, "")
]:
    if not os.path.exists(archivo_base):
        with open(archivo_base, "w", encoding="utf-8") as f:
            if isinstance(contenido_inicial, (dict, list)):
                json_lib.dump(contenido_inicial, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

ENV_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHAT_ID_ACTIVO = int(ENV_CHAT_ID) if ENV_CHAT_ID and ENV_CHAT_ID.strip().isdigit() else None

lock_voz = asyncio.Lock()
GEMINI_BLOQUEADO_POR_CUOTA = False
MODELO_GEMINI = "gemini-2.0-flash"

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# =====================================================================
# SYSTEM PROMPT (Versión directa y fluida sin JSON rígido)
# =====================================================================
SYSTEM_PROMPT = (
    "Sos Leandro, un compañero y colega de Telegram. Hablás en perfecto español rioplatense (porteño) con voseo natural ('che', 'vós', 'fijate', 'posta').\n"
    "Tenés acceso al historial completo de la charla guardado en conversaciones.txt. Usalo para entender de qué están hablando y responder con coherencia.\n"
    "No respondas con JSON. Respondé directamente con el texto de tu mensaje tal cual se lo dirías a un colega en un chat."
)


def sincronizar_con_github(mensaje_commit="🤖 Sincronización evolutiva y de código"):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        subprocess.run(["git", "add", "."], check=True)
        resultado = subprocess.run(["git", "commit", "-m", mensaje_commit], capture_output=True, text=True)
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Sincronizado y pusheado con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ Aviso de git (no crítico): {e}")


def obtener_historial_conversaciones(cant_lineas=80):
    with file_lock:
        if not os.path.exists(TXT_FILE):
            return ""
        try:
            lineas = []
            try:
                with open(TXT_FILE, "r", encoding="utf-8") as f:
                    lineas = f.readlines()
            except UnicodeDecodeError:
                with open(TXT_FILE, "r", encoding="latin-1", errors="ignore") as f:
                    lineas = f.readlines()
            
            recientes = [l.strip() for l in lineas if l.strip()]
            return "\n".join(recientes[-cant_lineas:])
        except Exception as e:
            print(f"⚠️ Error leyendo {TXT_FILE}: {e}")
            return ""


def registrar_conversacion(remitente, texto):
    with file_lock:
        try:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            linea = f"[{ts}] {remitente.upper()}: {texto}\n"
            with open(TXT_FILE, "a", encoding="utf-8") as f:
                f.write(linea)
                f.flush()
                os.fsync(f.fileno())
            print(f"📝 [TXT REGISTRADO]: {remitente}: {texto[:40]}...")
        except Exception as e:
            print(f"⚠️ Error escribiendo en {TXT_FILE}: {e}")
    sincronizar_con_github(f"📝 Actualización de bitácora ({remitente})")


# ==========================================
# GESTIÓN DE HISTORIALES Y EVOLUCIÓN AUTÓNOMA
# ==========================================
def cargar_json(path, tipo_defecto):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json_lib.load(f)
            except:
                return tipo_defecto
    return tipo_defecto


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


def registrar_correccion_inductiva(audio_path, error_whisper, correccion_real):
    historial = cargar_json(REGISTRO_INDUCCION, {})
    historial[error_whisper.lower().strip()] = {
        "correcto": correccion_real.strip(),
        "audio_muestra": audio_path
    }
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)
    print(f"🧠 [Inducción Registrada]: '{error_whisper}' -> '{correccion_real}'")
    sincronizar_con_github("🧠 Nueva inducción registrada")


def cotejar_y_corregir_induccion(texto_crudo):
    historial = cargar_json(REGISTRO_INDUCCION, {})
    if not historial:
        return texto_crudo
    
    texto_lower = texto_crudo.lower().strip()
    if texto_lower in historial:
        return historial[texto_lower]["correcto"]

    frases_conocidas = list(historial.keys())
    coincidencias = difflib.get_close_matches(texto_lower, frases_conocidas, n=1, cutoff=0.70)
    if coincidencias:
        return historial[coincidencias[0]]["correcto"]

    return texto_crudo


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


def generar_respuesta_ia(
