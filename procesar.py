# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - Bot Autónomo con Comprensión Dinámica de Personaje, Auto-Corrección de Whisper, Métricas de Voz, Búsqueda Web y Hot-Deploy

import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
import math
import traceback
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

print("🚀 [INIT]: Arrancando Bot con Comprensión Dinámica y DSP Total...", flush=True)

TXT_FILE = "conversaciones.txt"
FILE_TAREAS = "memoria_tareas.json"
FILE_DATASET = "dataset_entrenamiento_chat.json"
FILE_METRICAS_VOZ = "historial_metricas_voz.json"
CONFIG_TIMBRE = "config_timbre.json"
FILE_CORRECCIONES = "correcciones_whisper.json"
CARPETA_MUESTRAS = "muestras_voz"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

for f_path, default_val in [
    (TXT_FILE, ""),
    (FILE_TAREAS, []),
    (FILE_DATASET, []),
    (FILE_METRICAS_VOZ, []),
    (FILE_CORRECCIONES, {}),
    (CONFIG_TIMBRE, {
        "voice": "es-AR-TomasNeural",
        "volume": "+0dB",
        "tempo": "1.0",
        "sample_rate_factor": "1.0",
        "persona_prompt": "Sos un interlocutor colega y locutor rioplatense experto en vibe coding.",
        "descripcion": "Locutor base dinámico",
        "armonicos_hz_db": {}
    })
]:
    if not os.path.exists(f_path):
        if isinstance(default_val, str):
            with open(f_path, "w", encoding="utf-8") as f:
                f.write(default_val)
                f.flush()
                os.fsync(f.fileno())
        else:
            with open(f_path, "w", encoding="utf-8") as f:
                json_lib.dump(default_val, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

CHAT_ID_ACTIVO = None
lock_voz = asyncio.Lock()

try:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    GENAI_DISPONIBLE = True if client else False
except Exception:
    client = None
    GENAI_DISPONIBLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_DISPONIBLE = True
except Exception:
    WHISPER_DISPONIBLE = False
    print("⚠️ [WHISPER]: No se pudo importar faster_whisper.", flush=True)

def sincronizar_con_github(mensaje_commit="chg: sincronización automática de estado y código [skip ci]"):
    try:
        subprocess.run(["git", "config", "user.name", "LeandroBot[bot]"], check=False)
        subprocess.run(["git", "config", "user.email", "leandrobot@users.noreply.github.com"], check=False)
        archivos = [TXT_FILE, FILE_TAREAS, FILE_DATASET, FILE_METRICAS_VOZ, CONFIG_TIMBRE, FILE_CORRECCIONES, "procesar.py"]
        for a in archivos:
            if os.path.exists(a):
                subprocess.run(["git", "add", a], check=False)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", mensaje_commit], check=False)
            subprocess.run(["git", "push"], check=False)
            print("📦 [GIT AUTO-SYNC]: Sincronizado con GitHub.", flush=True)
    except Exception as e:
        print(f"⚠️ [GIT AUTO-SYNC ERROR]: {e}", flush=True)

def asegurar_e_iniciar_ollama():
    print("🦙 [OLLAMA]: Verificando estado del servicio local...", flush=True)
    for _ in range(3):
        try:
            res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2)
            if res.status_code == 200:
                print("🦙 [OLLAMA]: ¡Servicio activo y listo!", flush=True)
                return True
        except Exception:
            pass
        time.sleep(1)

    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for i in range(15):
            time.sleep(1)
            try:
                res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2)
                if res.status_code == 200:
                    break
            except Exception:
                continue
        subprocess.run(["ollama", "pull", OLLAMA_MODEL], check=False)
        return True
    except Exception as e:
        print(f"⚠️ [OLLAMA ERROR]: {e}", flush=True)
        return False

def registrar_correccion_whisper(texto_mal, texto_corregido):
    try:
        correcciones = {}
        if os.path.exists(FILE_CORRECCIONES):
            try:
                with open(FILE_CORRECCIONES, "r", encoding="utf-8") as f:
                    correcciones = json_lib.load(f)
            except Exception:
                correcciones = {}
        
        correcciones[texto_mal.strip().lower()] = texto_corregido.strip()
        with open(FILE_CORRECCIONES, "w", encoding="utf-8") as f:
            json_lib.dump(correcciones, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        print(f"🧠 [WHISPER APRENDIDO]: '{texto_mal}' -> '{texto_corregido}'", flush=True)
        sincronizar_con_github("chg: nueva regla de corrección fonética en whisper")
    except Exception as e:
        print(f"⚠️ Error guardando corrección: {e}", flush=True)

def aplicar_correcciones_texto(texto):
    if not os.path.exists(FILE_CORRECCIONES):
        return texto
    try:
        with open(FILE_CORRECCIONES, "r", encoding="utf-8") as f:
            correcciones = json_lib.load(f)
            if isinstance(correcciones, dict):
                for mal, bien in correcciones.items():
                    if mal in texto.lower():
                        pattern = re.compile(re.escape(mal), re.IGNORECASE)
                        texto = pattern.sub(bien, texto)
    except Exception:
        pass
    return texto

def buscar_en_web(query):
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                lineas = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
                return chr(10).join(lineas)
    except Exception as e:
        print(f"⚠️ Aviso búsqueda web: {e}", flush=True)
    return ""

def crear_o_modificar_archivo_en_caliente(nombre_archivo, contenido_codigo):
    try:
        with open(nombre_archivo, "w", encoding="utf-8") as f:
            f.write(contenido_codigo)
            f.flush()
            os.fsync(f.fileno())
        print(f"⚡ [HOT-DEPLOY]: Archivo '{nombre_archivo}' creado/modificado en el runner.", flush=True)
        sincronizar_con_github(f"feat: despliegue en caliente de {nombre_archivo}")
        return True
    except Exception as e:
        print(f"⚠️ Error creando archivo en caliente: {e}", flush=True)
        return False

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            return json_lib.load(f)
    except Exception:
        return {
            "voice": "es-AR-TomasNeural",
            "volume": "+0dB",
            "tempo": "1.0",
            "sample_rate_factor": "1.0",
            "persona_prompt": "Sos un interlocutor colega y locutor rioplatense experto en vibe coding.",
            "descripcion": "Locutor base dinámico",
            "armonicos_hz_db": {}
        }

def guardar_config_timbre(cfg):
    try:
        with open(CONFIG_TIMBRE, "w", encoding="utf-8") as f:
            json_lib.dump(cfg, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        print(f"🎙️ [TIMBRE DSP GUARDADO]: {cfg}", flush=True)
        sincronizar_con_github("chg: actualización de timbre DSP y armónicos")
    except Exception as e:
        print(f"⚠️ Error guardando timbre: {e}", flush=True)

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}" + chr(10))
            f.flush()
            os.fsync(f.fileno())
        sincronizar_con_github("chg: actualización de conversaciones.txt")
    except Exception as e:
        print(f"⚠️ Error escribiendo en {TXT_FILE}: {e}", flush=True)

def registrar_dataset_entrenamiento(prompt_usuario, respuesta_bot, modelo="gemini"):
    try:
        entrada = {
            "timestamp": datetime.now().isoformat(),
            "messages": [
                {"role": "user", "content": prompt_usuario},
                {"role": "assistant", "content": respuesta_bot}
            ],
            "metadata": {"modelo": modelo}
        }
        with open(FILE_DATASET, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps(entrada, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        sincronizar_con_github("chg: nuevo registro en dataset_entrenamiento_chat.json")
    except Exception as e:
        print(f"⚠️ Error guardando dataset: {e}", flush=True)

def cargar_tareas_memoria():
    if not os.path.exists(FILE_TAREAS):
        return []
    try:
        with open(FILE_TAREAS, "r", encoding="utf-8") as f:
            datos = json_lib.load(f)
            return datos if isinstance(datos, list) else []
    except Exception:
        return []

def guardar_tarea_memoria(texto_tarea):
    try:
        tareas = cargar_tareas_memoria()
        nueva = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "tarea": texto_tarea,
            "estado": "pendiente"
        }
        tareas.append(nueva)
        tareas = tareas[-50:]
        with open(FILE_TAREAS, "w", encoding="utf-8") as f:
            json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        sincronizar_con_github("chg: actualización de memoria_tareas.json")
    except Exception as e:
        print(f"⚠️ Error guardando tarea: {e}", flush=True)

def registrar_metricas_voz_palabra_por_palabra(path_audio_ogg, texto_transcripto):
    try:
        wav_tmp = f"tmp_metricas_{int(time.time())}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", path_audio_ogg, "-ar", "16000", "-ac", "1", wav_tmp
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        duracion_total_ms = 1000
        intensidad_db_general = -18.0

        if os.path.exists(wav_tmp):
            import soundfile as sf
            data, samplerate = sf.read(wav_tmp)
            duracion_total_ms = int((len(data) / samplerate) * 1000)
            rms = math.sqrt(sum(data**2) / len(data)) if len(data) > 0 else 0.0001
            intensidad_db_general = round(20 * math.log10(max(rms, 0.0001)), 2)
            os.remove(wav_tmp)

        palabras = texto_transcripto.split()
        cant_palabras = len(palabras) if palabras else 1
        duracion_promedio_ms = max(120, int(duracion_total_ms / cant_palabras))

        partitura_palabras = [{
            "palabra": p,
            "duracion_ms": duracion_promedio_ms,
            "intensidad_db": round(intensidad_db_general, 2)
        } for p in palabras]

        nuevo_registro = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "texto": texto_transcripto,
            "metricas_palabras": partitura_palabras
        }

        historial = []
        if os.path.exists(FILE_METRICAS_VOZ):
            try:
                with open(FILE_METRICAS_VOZ, "r", encoding="utf-8") as f:
                    historial = json_lib.load(f)
                    if not isinstance(historial, list):
                        historial = []
            except Exception:
                historial = []

        historial.append(nuevo_registro)
        historial = historial[-30:]
        with open(FILE_METRICAS_VOZ, "w", encoding="utf-8") as f:
            json_lib.dump(historial, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        sincronizar_con_github("chg: actualización de historial_metricas_voz.json")
    except Exception as e:
        print(f"⚠️ Error registrando métricas: {e}", flush=True)

def interpretar_configuracion_dsp_dinamica(prompt_usuario):
    """Comprensión pura por IA: infiere voz de Edge-TTS, parámetros DSP y la persona/actitud idónea."""
    cfg_actual = cargar_config_timbre()
    persona_actual = cfg_actual.get("persona_prompt", "Sos un interlocutor colega y locutor rioplatense experto en vibe coding.")
    voz_actual = cfg_actual.get("voice", "es-AR-TomasNeural")

    prompt_ia = (
        f"Analizá con precisión el mensaje del usuario: '{prompt_usuario}'.\n"
        "Determina si el usuario pide cambiar la voz, el personaje, el tono o parámetros acústicos.\n"
        "- Si pide voz más aguda, fina o alta: asigná 'sample_rate_factor' mayor a 1.0 (ej: 1.25).\n"
        "- Si pide voz más grave, baja, profunda o tubo: asigná 'sample_rate_factor' menor a 1.0 (ej: 0.78).\n"
        "- Si pide voz de Elena o mujer: asigná 'voice': 'es-AR-ElenaNeural' y 'persona_prompt': 'Sos Elena, una interlocutora y colega rioplatense.'\n"
        "- Si pide voz de Leandro o varón: asigná 'voice': 'es-AR-TomasNeural' y 'persona_prompt': 'Sos un interlocutor colega y locutor rioplatense experto en vibe coding.'\n"
        f"Si el usuario no especifica personaje nuevo, conservá el 'persona_prompt' activo ('{persona_actual}') y la 'voice' activa ('{voz_actual}').\n"
        "Asegurate de poner 'aplica_cambio': true si hay una orden explícita de modificar audio/voz/tono, o false si es una charla normal.\n\n"
        "Devolvé ÚNICAMENTE JSON válido sin marcas de markdown:\n"
        "{\n"
        f'  "voice": "{voz_actual}",\n'
        '  "volume": "+0dB",\n'
        '  "tempo": "1.0",\n'
        '  "sample_rate_factor": "1.0",\n'
        '  "armonicos_hz_db": {},\n'
        f'  "persona_prompt": "{persona_actual}",\n'
        '  "aplica_cambio": true,\n'
        f'  "descripcion": "{prompt_usuario}"\n'
        "}"
    )

    if client:
        try:
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt_ia,
                config=dict(response_mime_type="application/json")
            )
            data = json_lib.loads((res.text or "").strip())
            if "aplica_cambio" in data:
                return data
        except Exception:
            pass

    return {
        "voice": voz_actual,
        "volume": "+0dB",
        "tempo": "1.0",
        "sample_rate_factor": "1.0",
        "persona_prompt": persona_actual,
        "armonicos_hz_db": {},
        "aplica_cambio": False,
        "descripcion": prompt_usuario
    }

def construir_prompt_sistema(info_web=""):
    cfg = cargar_config_timbre()
    persona_base = cfg.get("persona_prompt", "Sos un interlocutor colega y locutor rioplatense experto en vibe coding.")

    return (
        f"{persona_base}\n"
        "
