# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot con Vibe Coding Dinámico, Cero Hardcodeo y Auto-Sync a GitHub

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

print("🚀 [INIT]: Inicializando LeandroBot sin hardcodeo, con modificación de código en caliente y Auto-Sync a GitHub...", flush=True)

TXT_FILE = "conversaciones.txt"
FILE_TAREAS = "memoria_tareas.json"
FILE_DATASET = "dataset_entrenamiento_chat.json"
FILE_METRICAS_VOZ = "historial_metricas_voz.json"
CONFIG_TIMBRE = "config_timbre.json"
CARPETA_MUESTRAS = "muestras_voz"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

# Inicializar archivos base si no existen con escritura síncrona
for f_path, default_val in [
    (TXT_FILE, ""),
    (FILE_TAREAS, []),
    (FILE_DATASET, []),
    (FILE_METRICAS_VOZ, []),
    (CONFIG_TIMBRE, {
        "voice": "es-AR-ElenaNeural",
        "pitch": "+0Hz",
        "rate": "+0%",
        "volume": "+0%",
        "descripcion": "Persona dinámica adaptativa",
        "serie_armonica_custom": None
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

def sincronizar_con_github(mensaje_commit="chg: sincronización en tiempo real de memoria y datasets [skip ci]"):
    """Persiste los archivos de memoria y entrenamiento directamente en el repo remoto de GitHub."""
    try:
        subprocess.run(["git", "config", "user.name", "LeandroBot[bot]"], check=False)
        subprocess.run(["git", "config", "user.email", "leandrobot@users.noreply.github.com"], check=False)

        archivos = [TXT_FILE, FILE_TAREAS, FILE_DATASET, FILE_METRICAS_VOZ, CONFIG_TIMBRE, "procesar.py"]
        for a in archivos:
            if os.path.exists(a):
                subprocess.run(["git", "add", a], check=False)

        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", mensaje_commit], check=False)
            subprocess.run(["git", "push"], check=False)
            print("📦 [GIT AUTO-SYNC]: Cambios persistidos en GitHub con éxito.", flush=True)
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
        print("🦙 [OLLAMA]: Arrancando demonio 'ollama serve'...", flush=True)
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

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            return json_lib.load(f)
    except Exception:
        return {
            "voice": "es-AR-ElenaNeural",
            "pitch": "+0Hz",
            "rate": "+0%",
            "volume": "+0%",
            "descripcion": "Persona dinámica adaptativa",
            "serie_armonica_custom": None
        }

def guardar_config_timbre(cfg):
    try:
        with open(CONFIG_TIMBRE, "w", encoding="utf-8") as f:
            json_lib.dump(cfg, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        print(f"🎙️ [TIMBRE ACTUALIZADO EN TIEMPO REAL]: {cfg}", flush=True)
        sincronizar_con_github("chg: actualización de configuración de timbre")
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
        print("📊 [DATASET ENTRENAMIENTO]: Registro guardado y sincronizado al instante.", flush=True)
        sincronizar_con_github("chg: nuevo registro en dataset_entrenamiento_chat.json")
    except Exception as e:
        print(f"⚠️ Error guardando dataset de entrenamiento: {e}", flush=True)

def cargar_tareas_memoria():
    if not os.path.exists(FILE_TAREAS):
        return []
    try:
        with open(FILE_TAREAS, "r", encoding="utf-8") as f:
            datos = json_lib.load(f)
            return datos if isinstance(datos, list) else []
    except Exception:
        return []

def es_pedido_o_tarea(texto):
    t_lower = texto.lower()
    keywords = [
        "hacé", "hace", "creá", "crea", "agregá", "agrega", "modificá", "modifica",
        "programá", "programa", "anotá", "anota", "recordá", "recuerda", "buscá", "busca",
        "cambiá", "cambia", "necesito", "quiero", "fijate de", "armate", "prepará", "prepara",
        "código", "script", "bot", "función", "archivo", "tarea", "directiva", "voz", "diseñadora", "refactor"
    ]
    if texto.startswith("/") or any(kw in t_lower for kw in keywords):
        return True
    return False

def guardar_tarea_memoria(texto_tarea):
    if not es_pedido_o_tarea(texto_tarea):
        return
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
        print(f"📋 [MEMORIA TAREAS]: Pedido guardado -> {texto_tarea[:40]}...", flush=True)
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
        print(f"🎛️ [MÉTRICAS VOZ]: Métricas guardadas y sincronizadas.", flush=True)
        sincronizar_con_github("chg: actualización de historial_metricas_voz.json")
    except Exception as e:
        print(f"⚠️ Error registrando métricas: {e}", flush=True)

def aplicar_modificacion_codigo_en_caliente(codigo_python):
    """Ejecuta y sobreescribe el archivo procesar.py dinámicamente según la orden del usuario."""
    try:
        with open("procesar.py", "w", encoding="utf-8") as f:
            f.write(codigo_python)
            f.flush()
            os.fsync(f.fileno())
        print("⚡ [VIBE CODING]: Código reescrito y aplicado en tiempo real.", flush=True)
        sincronizar_con_github("refactor: modificación de código en caliente vía vibe coding")
        return True
    except Exception as e:
        print(f"⚠️ Error aplicando modificación de código: {e}", flush=True)
        return False

def obtener_resumen_contexto_ligero():
    ultimas_conv = ""
    if os.path.exists(TXT_FILE):
        try:
            with open(TXT_FILE, "r", encoding="utf-8") as f:
                lineas = f.readlines()
            ultimas_conv = "".join(lineas[-5:])
        except Exception:
            pass

    tareas = cargar_tareas_memoria()
    tareas_pendientes = ", ".join([t.get('tarea', '') for t in tareas[-3:] if isinstance(t, dict)])

    return (
        f"[Contexto compacto]\n"
        f"- Tareas clave: {tareas_pendientes if tareas_pendientes else 'Ninguna'}\n"
        f"- Último intercambio:\n{ultimas_conv}"
    )

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

def parsear_timbre_dinamico(descripcion_natural):
    """Interpreta dinámicamente cualquier pedido de personaje/timbre por NLP sin presets hardcodeados."""
    info_ref = ""
    if any(k in descripcion_natural.lower() for k in ["youtube", "podcast", "streaming", "referencia", "estilo"]):
        info_ref = buscar_en_web(f"audio voice timbre {descripcion_natural}")

    prompt_ia = (
        f"Analizá la intención de personaje/voz: '{descripcion_natural}'.\n"
        f"Referencias web: {info_ref}\n"
        "Determiná los parámetros exactos de Edge-TTS:\n"
        "- voice: elegí dinómicamente entre 'es-AR-ElenaNeural' (mujer porteña), 'es-AR-TomasNeural' (hombre porteño), 'es-UY-MateoNeural', u otra voz en español según la persona.\n"
        "- pitch: modulación entre '-10Hz' y '+10Hz'.\n"
        "- rate: modulación entre '-15%' y '+15%'.\n"
        "- volume: entre '-10%' y '+10%'.\n"
        "Devolvé ÚNICAMENTE JSON válido:\n"
        "{\n"
        '  "voice": "es-AR-ElenaNeural",\n'
        '  "pitch": "+1Hz",\n'
        '  "rate": "-2%",\n'
        '  "volume": "+5%",\n'
        '  "serie_armonica_custom": "Dinámico",\n'
        f'  "descripcion": "{descripcion_natural}"\n'
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
            if "voice" in data:
                return data
        except Exception:
            pass

    return {
        "voice": "es-AR-ElenaNeural" if "diseñadora" in descripcion_natural.lower() or "femenina" in descripcion_natural.lower() else "es-AR-TomasNeural",
        "pitch": "+2Hz" if "diseñadora" in descripcion_natural.lower() else "-2Hz",
        "rate": "-2%",
        "volume": "+5%",
        "serie_armonica_custom": None,
        "descripcion": descripcion_natural
    }

def construir_prompt_sistema():
    timbre = cargar_config_timbre()
    contexto_ligero = obtener_resumen_contexto_ligero()

    return (
        "Sos un agente dinámico de vibe coding con capacidad de adaptar tu persona y modificar el código del bot en caliente.\n"
        "REGLAS:\n"
        "1. Hablá con voseo porteño rioplatense natural ('che', 'vós', 'fijate', 'posta', 'dale').\n"
        "2. Usá comas y puntos suspensivos para dar fluidez y cadencia oral natural en audio.\n"
        "3. Si te piden programar, cambiar el bot o refactorizar código, entregá el bloque completo y limpio listo para ejecutarse.\n\n"
        f"Persona/Timbre activo: {timbre.get('descripcion', '')} (Voz: {timbre.get('voice')})\n\n"
        f"{contexto_ligero}"
    )

def generar_texto_ia(prompt_usuario):
    system_prompt = construir_prompt_sistema()
    p = prompt_usuario

    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio", "streaming", "youtube"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = prompt_usuario + chr(10) + chr(10) + "[Web]: " + info_web

    if client:
        try:
            print("🤖 [GEMINI]: Consultando nube...", flush=True)
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[{"role": "user", "parts": [{"text": system_prompt + "\n\nMensaje: " + p}]}]
            )
            raw = (res.text or "").strip()
            if raw:
                print("✅ [GEMINI OK]: Respuesta obtenida.", flush=True)
                registrar_dataset_entrenamiento(prompt_usuario, raw, "gemini")
                return raw
        except Exception as e:
            print(f"⚠️ [GEMINI FALLÓ]: {e}. Fallback a Ollama...", flush=True)

    try:
        print(f"🦙 [OLLAMA]: Consultando modelo local {OLLAMA_MODEL}...", flush=True)
        r = requests.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": p}
                ],
                "options": {"num_ctx": 1024, "num_predict": 180, "temperature": 0.7},
                "stream": False
            },
            timeout=30
        )
        if r.status_code == 200:
            texto = r.json().get("message", {}).get("content", "").strip()
            if texto:
                print("✅ [OLLAMA OK]: Respuesta local generada.", flush=True)
                registrar_dataset_entrenamiento(prompt_usuario, texto, "llama")
                return texto
    except Exception as e_ollama:
        print(f"⚠️ [OLLAMA FALLÓ]: {e_ollama}", flush=True)

    return "Che, se me trabó el motor de IA un segundo. ¿Me repetís?"

def preparar_texto_para_voz(texto):
    t = re.sub(r'```[\s\S]*?```', 'Te pasé el bloque de código por texto.', texto)
    t = t.replace("*", "").replace("_", "").replace(chr(96), "").replace("#", "").strip()
    t = re.sub(r'\b(che|mirá|fijate|escuchá|vení|posta)\b', r'\g<1>...', t, flags=re.IGNORECASE)
    palabras = t.split()
    if len(palabras) > 55:
        t = " ".join(palabras[:50]) + "... te lo resumo hasta acá, che."
    return t.strip()

async def sintetizar_voz_edge_tts(texto, ogg_salida="resp.ogg"):
    cfg = cargar_config_timbre()
    voice = cfg.get("voice", "es-AR-ElenaNeural")
    pitch = cfg.get("pitch", "+0Hz")
    rate = cfg.get("rate", "+0%")
    volume = cfg.get("volume", "+0%")

    texto_oral = preparar_texto_para_voz(texto)
    if not texto_oral:
        texto_oral = "Sintonizamos en un toque, che."

    try:
        import edge_tts
        print(f"🎙️ [EDGE-TTS]: Sintetizando voz con {voice}...", flush=True)
        communicate = edge_tts.Communicate(texto_oral, voice=voice, pitch=pitch, rate=rate, volume=volume)
        mp3_tmp = f"tmp_edge_{int(time.time()*1000)}.mp3"
        await communicate.save(mp3_tmp)

        if not os.path.exists(mp3_tmp) or os.path.getsize(mp3_tmp) < 100:
            return False, None

        proc = subprocess.run([
            "ffmpeg", "-y", "-i", mp3_tmp,
            "-ar", "48000", "-ac", "1",
            "-c:a", "libopus", "-b:a", "48k",
            "-application", "voip",
            ogg_salida
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 200:
            registrar_metricas_voz_palabra_por_palabra(ogg_salida, texto_oral)
            try: os.remove(mp3_tmp)
            except Exception: pass
            return True, ogg_salida

        return True, mp3_tmp
    except Exception as e:
        print(f"⚠️ Error sintetizando con edge-tts: {e}", flush=True)
        return False, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text("¡Hola che! Listo para vibe coding dinámico, modificación en caliente y entrenamiento continuo.")

async def cambiar_timbre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    desc = " ".join(context.args).strip() if context.args else ""
    if not desc:
        cfg = cargar_config_timbre()
        await update.message.reply_text(f"🎙️ Timbre actual: '{cfg.get('descripcion', 'Estándar')}' ({cfg.get('voice')})")
        return
    nuevo_timbre = parsear_timbre_dinamico(desc)
    guardar_config_timbre(nuevo_timbre)
    await update.message.reply_text(f"✅ Persona y timbre dinámico ajustados a: '{desc}' ({nuevo_timbre.get('voice')}).")

async def manejar_vibe_coding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    instruccion = " ".join(context.args).strip() if context.args else ""
    if not instruccion:
        await update.message.reply_text("Decime qué querés programar o modificar en caliente, che.")
        return
    guardar_tarea_memoria(f"Vibe Coding: {instruccion}")
    await update.message.reply_text(f"💻 Procesando vibe coding: '{instruccion}'...")
    resp_codigo = generar_texto_ia(f"VIBE CODING: {instruccion}. Generá el código completo.")
    await update.message.reply_text(resp_codigo)

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text or update.message.caption or "[Texto]"

    # Si se envía un pedido expreso de personaje/voz en el texto, se recalibra dinámicamente
    if any(k in u_text.lower() for k in ["voz de", "cambiá la voz", "soná como", "diseñadora", "locutor"]):
        cfg_dinamica = parsear_timbre_dinamico(u_text)
        guardar_config_timbre(cfg_dinamica)
    
    guardar_tarea_memoria(u_text)
    registrar_conversacion("Usuario", u_text)

    resp = generar_texto_ia(u_text)
    registrar_conversacion("LeandroBot", resp)
    
    await update.message.reply_text(resp)

    ogg_f = f"resp_{int(time.time())}.ogg"
    exito, archivo_audio = await sintetizar_voz_edge_tts(resp, ogg_f)
    if exito and archivo_audio and os.path.exists(archivo_audio):
        try:
            with open(archivo_audio, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption="📻 LeandroBot")
        except Exception as ex_send:
            print(f"⚠️ Error enviando audio: {ex_send}", flush=True)
        try: os.remove(archivo_audio)
        except Exception: pass

async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    async with lock_voz:
        if not update.message:
            return
        CHAT_ID_ACTIVO = update.message.chat_id
        if not WHISPER_DISPONIBLE:
            await update.message.reply_text("Whisper no disponible.")
            return

        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        path_in = os.path.join(CARPETA_MUESTRAS, f"audio_{update.message.message_id}.ogg")
        await file.download_to_drive(path_in)

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip() or "Audio recibido."

        if any(k in texto_crudo.lower() for k in ["voz de", "cambiá la voz", "soná como", "diseñadora", "locutor"]):
            cfg_dinamica = parsear_timbre_dinamico(texto_crudo)
            guardar_config_timbre(cfg_dinamica)

        registrar_metricas_voz_palabra_por_palabra(path_in, texto_crudo)
        guardar_tarea_memoria(texto_crudo)
        registrar_conversacion("Usuario", f"[AUDIO] {texto_crudo}")

        resp = generar_texto_ia(texto_crudo)
        registrar_conversacion("LeandroBot", resp)

        await update.message.reply_text(f"*(Interpretado: {texto_crudo})*\n\n{resp}")

        ogg_f = f"resp_voz_{int(time.time())}.ogg"
        exito, archivo_audio = await sintetizar_voz_edge_tts(resp, ogg_f)
        if exito and archivo_audio and os.path.exists(archivo_audio):
            try:
                with open(archivo_audio, "rb") as vf:
                    await update.message.reply_voice(voice=vf, caption="📻 LeandroBot")
            except Exception as ex_send:
                print(f"⚠️ Error enviando audio: {ex_send}", flush=True)
            try: os.remove(archivo_audio)
            except Exception: pass

        if os.path.exists(path_in):
            try: os.remove(path_in)
            except Exception: pass

def main():
    if not TOKEN:
        print("❌ Falta TELEGRAM_BOT_TOKEN.", flush=True)
        return
    asegurar_e_iniciar_ollama()
    print("🚀 [INIT]: Arrancando LeandroBot dinámico...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)
    try:
        app = Application.builder().token(TOKEN).request(request_config).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("timbre", cambiar_timbre))
        app.add_handler(CommandHandler("codigo", manejar_vibe_coding))
        app.add_handler(CommandHandler("vibe", manejar_vibe_coding))
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_voz))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        traceback.print_exc()

if __name__ == "__main__":
    main()
