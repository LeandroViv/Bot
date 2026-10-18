# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / Vibe Coding Atómico por Lotes Universal sobre Cualquier Archivo

import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
import ast
import shutil
from datetime import datetime

# Importación defensiva y autogestionada de psutil
try:
    import psutil
except ImportError:
    print("⚠️ [INIT]: psutil no detectado. Instalando automáticamente...", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "psutil"], check=True)
    import psutil

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

print("🚀 [TEST VIBE CODING]: Todo en orden, maestro", flush=True)
print("🚀 [INIT]: Inicializando LeandroBot Adaptativo (Vibe Coding Universal por Lotes + Ollama)...", flush=True)

URL_REPOSITORIO = "https://github.com/LeandroViv/Bot"
TXT_FILE = "conversaciones.txt"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
PERFIL_DINAMICO = "perfil_personaje.json"
CAMBIO_PROPUESTO_FILE = "cambio_propuesto.txt"
CORRECCIONES_WHISPER = "correcciones_whisper.json"
HISTORIAL_METRICAS = "historial_metricas_voz.json"

TIEMPO_INICIO = time.time()

for f_path, default_val in [
    (TXT_FILE, ""),
    (DATASET_ENTRENAMIENTO, []),
    (CORRECCIONES_WHISPER, {}),
    (HISTORIAL_METRICAS, []),
    (PERFIL_DINAMICO, {
        "nombre": "Leandro",
        "estilo": "Colega y compañero de vibe coding con tonada rioplatense, yeísmo y ritmo auténtico",
        "notas_aprendizaje": []
    }),
    (CONFIG_TIMBRE, {
        "voice": "es-AR-TomasNeural",
        "pitch": "-4Hz",
        "rate": "-5%",
        "volume": "+10%",
        "f0Hz": 125,
        "harmonics": [],
        "descripcion": "Motor acústico dinámico por Vibe Coding"
    })
]:
    if not os.path.exists(f_path):
        if isinstance(default_val, str):
            with open(f_path, "w", encoding="utf-8") as f:
                f.write(default_val)
        else:
            with open(f_path, "w", encoding="utf-8") as f:
                json_lib.dump(default_val, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

CHAT_ID_ACTIVO = None

try:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    GENAI_DISPONIBLE = True if client else False
except Exception:
    client = None
    GENAI_DISPONIBLE = False

def registrar_metrica_voz(cfg, texto_limpio):
    try:
        metrica = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "voice": cfg.get("voice", "es-AR-TomasNeural"),
            "pitch": cfg.get("pitch", "-4Hz"),
            "rate": cfg.get("rate", "-5%"),
            "volume": cfg.get("volume", "+10%"),
            "harmonics": cfg.get("harmonics", []),
            "longitud_texto": len(texto_limpio),
            "fragmento_texto": texto_limpio[:120]
        }
        historial = []
        if os.path.exists(HISTORIAL_METRICAS):
            try:
                with open(HISTORIAL_METRICAS, "r", encoding="utf-8") as f:
                    historial = json_lib.load(f)
                    if not isinstance(historial, list):
                        historial = []
            except Exception:
                historial = []
        historial.append(metrica)
        if len(historial) > 500:
            historial = historial[-500:]
        with open(HISTORIAL_METRICAS, "w", encoding="utf-8") as f:
            json_lib.dump(historial, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error registrando métrica de voz: {e}", flush=True)

def asegurar_ollama_en_runner():
    try:
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3.0)
        if r.status_code == 200:
            return True
    except Exception:
        pass
    for intento in range(3):
        try:
            print(f"🦙 [OLLAMA]: Levantando servicio local (Intento {intento+1}/3)...", flush=True)
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(3)
            r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3.0)
            if r.status_code == 200:
                return True
        except Exception as ex:
            print(f"⚠️ Aviso conexión Ollama: {ex}", flush=True)
            time.sleep(2)
    return False

def ejecutar_comando_runner_en_vivo(cmd_str):
    try:
        res = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=120)
        salida = res.stdout.strip() if res.stdout else res.stderr.strip()
        if not salida:
            salida = "Comando ejecutado con éxito."
        return True, salida
    except Exception as e:
        return False, f"Error ejecutando comando: {str(e)}"

def obtener_mapa_repositorio(root_dir="."):
    mapa = []
    ignorar = {".git", "__pycache__", ".github", "venv", "downloads"}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in ignorar]
        rel_path = os.path.relpath(dirpath, root_dir)
        if rel_path == ".":
            rel_path = ""
        for f in filenames:
            if f.endswith((".py", ".json", ".txt", ".md", ".sh", ".yml")):
                path_completo = os.path.join(rel_path, f) if rel_path else f
                mapa.append(path_completo)
    return mapa

def obtener_contenido_archivo(ruta):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return ""

def guardar_y_pushear_como_leandrobot(archivo_modificado, mensaje_commit):
    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_BOT_TOKEN")
    try:
        subprocess.run(["git", "config", "user.name", "LeandroBot[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "leandrobot@users.noreply.github.com"], check=True)
        if gh_token:
            remote_url = f"https://x-access-token:{gh_token}@github.com/LeandroViv/Bot.git"
            subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)
        subprocess.run(["git", "add", archivo_modificado], check=True)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            return True
        subprocess.run(["git", "commit", "-m", mensaje_commit], check=True)
        res_push = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
        if res_push.returncode != 0:
            subprocess.run(["git", "pull", "--rebase", "origin", "HEAD"], check=False)
            subprocess.run(["git", "push", "origin", "HEAD"], check=True)
        return True
    except Exception as e:
        print(f"⚠️ Aviso git push automático: {e}", flush=True)
        return False

def aplicar_cambio_universal(ruta_destino, nuevo_contenido):
    # Validaciones según tipo de archivo
    if ruta_destino.endswith(".py"):
        try:
            ast.parse(nuevo_contenido)
        except SyntaxError as e:
            print(f"❌ [ERROR SINTAXIS AST Python]: {e}", flush=True)
            return False
        if len(nuevo_contenido.splitlines()) < 40 and "procesar.py" in ruta_destino:
            print("❌ [CANCELADO]: Código sospechosamente enano para procesar.py.", flush=True)
            return False

    elif ruta_destino.endswith(".json"):
        try:
            json_lib.loads(nuevo_contenido)
        except Exception as e:
            print(f"❌ [ERROR JSON]: {e}", flush=True)
            return False

    if os.path.exists(ruta_destino):
        shutil.copy2(ruta_destino, f"{ruta_destino}.bak")

    ruta_tmp = f"{ruta_destino}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        f.write(nuevo_contenido)
    os.replace(ruta_tmp, ruta_destino)

    return guardar_y_pushear_como_leandrobot(ruta_destino, f"vibe-coding: modificación autónoma en {ruta_destino}")

def detectar_archivo_objetivo(prompt_usuario):
    archivos = obtener_mapa_repositorio()
    prompt_lc = prompt_usuario.lower()
    for arch in archivos:
        if os.path.basename(arch).lower() in prompt_lc or arch.lower() in prompt_lc:
            return arch
    return "procesar.py"

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            cfg = json_lib.load(f)
            vol_raw = str(cfg.get("volume", "+10%"))
            if "db" in vol_raw.lower():
                vol_num = re.sub(r"[^0-9+-]", "", vol_raw)
                cfg["volume"] = f"{vol_num}%"
            return cfg
    except Exception:
        return {"voice": "es-AR-TomasNeural", "pitch": "-4Hz", "rate": "-5%", "volume": "+10%", "f0Hz": 125, "harmonics": []}

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}\n")
    except Exception:
        pass

def buscar_en_web(query):
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs_instance:
            results = list(ddgs_instance.text(query, max_results=3))
            if results:
                return "\n".join([f"- {r.get('title', '')}: {r.get('body', '')}" for r in results])
    except Exception:
        pass
    return ""

def generar_texto_ia(prompt_usuario, es_modo_codigo=False, ruta_archivo="procesar.py"):
    codigo_actual = obtener_contenido_archivo(ruta_archivo)
    
    if es_modo_codigo:
        system_prompt = (
            f"Sos un motor de Vibe Coding por lotes. Tenés que modificar el archivo '{ruta_archivo}'.\n"
            "MANTÉN EL CÓDIGO EXISTENTE Y APLICA ÚNICAMENTE LA MODIFICACIÓN SOLICITADA.\n"
            "DEVUELVE ÚNICAMENTE EL ARCHIVO COMPLETO Y ACTUALIZADO EN UN BLOQUE MARKDOWN (```python, ```json, o ```txt según corresponda) SIN TEXTO ADICIONAL.\n\n"
            f"--- CONTENIDO ACTUAL DE {ruta_archivo} ---\n```\n{codigo_actual[:6000]}\n```"
        )
    else:
        system_prompt = (
            "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense. Hablale de vos o che a Leandro.\n"
            "Mantené charlas fluidas y naturales."
        )

    p = prompt_usuario

    # 1. Intentar Gemini con fallback de modelos
    if client:
        for modelo in ["gemini-2.5-flash", "gemini-3.8-flash"]:
            try:
                res = client.models.generate_content(
                    model=modelo,
                    contents=p,
                    config=dict(system_instruction=system_prompt)
                )
                raw = (res.text or "").strip()
                if raw:
                    return raw
            except Exception:
                continue

    # 2. Fallback Ollama Local por lotes y reintentos ante timeout
    if asegurar_ollama_en_runner():
        for intento in range(3):
            try:
                prompt_ollama = (
                    f"Modifica el archivo {ruta_archivo} aplicando: {p}. Devuelve el bloque de código actualizado completo."
                ) if es_modo_codigo else f"{system_prompt}\n\nUsuario: {p}\nLeandro:"
                
                r = requests.post(
                    f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": prompt_ollama,
                        "stream": False,
                        "options": {"num_ctx": 4096, "temperature": 0.2}
                    },
                    timeout=60
                )
                if r.status_code == 200:
                    texto = r.json().get("response", "").strip()
                    if texto:
                        return texto
            except Exception as ex:
                print(f"⚠️ Aviso Ollama (intento {intento+1}/3): {ex}", flush=True)
                time.sleep(2)

    return "¡Qué hacés che! Tuvimos un problemita técnico con las IAs. Probá de nuevo en un toque."

def procesar_cambio_por_lotes(prompt_usuario, ruta_archivo):
    contenido_actual = obtener_contenido_archivo(ruta_archivo)
    lineas = contenido_actual.splitlines()

    # Si el archivo es chico, se procesa en una sola llamada
    if len(lineas) <= 120:
        respuesta_raw = generar_texto_ia(prompt_usuario, es_modo_codigo=True, ruta_archivo=ruta_archivo)
        match_code = re.search(r"```(?:\w+)?\s*([\s\S]*?)\s*```", respuesta_raw)
        return match_code.group(1).strip() if match_code else respuesta_raw

    # Batch / Fragmentación para archivos grandes
    print(f"🧩 [BATCH]: Dividiendo '{ruta_archivo}' en lotes para procesamiento seguro...", flush=True)
    mitad = len(lineas) // 2
    bloque_head = "\n".join(lineas[:mitad])
    bloque_tail = "\n".join(lineas[mitad:])

    prompt_batch = (
        f"Analiza si la siguiente solicitud afecta a la primera mitad o a la segunda mitad del archivo '{ruta_archivo}'.\n"
        f"Solicitud: {prompt_usuario}\n"
        f"Devuelve ÚNICAMENTE la palabra 'PARTE1' o 'PARTE2'."
    )
    res_lote = generar_texto_ia(prompt_batch, es_modo_codigo=False)

    if "PARTE1" in res_lote.upper():
        print("🧩 [BATCH]: Procesando Lote 1/2...", flush=True)
        res_mod = generar_texto_ia(f"Modifica solo esta sección inicial del archivo segun: {prompt_usuario}\n```\n{bloque_head}\n```", es_modo_codigo=True, ruta_archivo=ruta_archivo)
        match_code = re.search(r"```(?:\w+)?\s*([\s\S]*?)\s*```", res_mod)
        new_head = match_code.group(1).strip() if match_code else bloque_head
        return f"{new_head}\n{bloque_tail}"
    else:
        print("🧩 [BATCH]: Procesando Lote 2/2...", flush=True)
        res_mod = generar_texto_ia(f"Modifica solo esta sección final del archivo segun: {prompt_usuario}\n```\n{bloque_tail}\n```", es_modo_codigo=True, ruta_archivo=ruta_archivo)
        match_code = re.search(r"```(?:\w+)?\s*([\s\S]*?)\s*```", res_mod)
        new_tail = match_code.group(1).strip() if match_code else bloque_tail
        return f"{bloque_head}\n{new_tail}"

def preparar_texto_para_voz(texto):
    t = re.sub(r"https?://\S+", "", texto)
    t = re.sub(r"[*_`~#\[\]<>]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

async def sintetizar_audio_dsp(texto, archivo_salida="respuesta_dsp.ogg"):
    cfg = cargar_config_timbre()
    texto_limpio = preparar_texto_para_voz(texto) or "Dale, te escucho."
    archivo_raw = "temp_raw.mp3"
    cmd_tts = ["edge-tts", f"--voice={cfg.get('voice', 'es-AR-TomasNeural')}", f"--pitch={cfg.get('pitch', '-4Hz')}", f"--rate={cfg.get('rate', '-5%')}", f"--volume={cfg.get('volume', '+10%')}", f"--text={texto_limpio}", f"--write-media={archivo_raw}"]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd_tts, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        if not os.path.exists(archivo_raw) or os.path.getsize(archivo_raw) == 0:
            return None
        cmd_ffmpeg = ["ffmpeg", "-y", "-i", archivo_raw, "-c:a", "libopus", "-b:a", "32k", "-vn", archivo_salida]
        proc_ff = await asyncio.create_subprocess_exec(*cmd_ffmpeg, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc_ff.communicate()
        if os.path.exists(archivo_raw):
            os.remove(archivo_raw)
        if os.path.exists(archivo_salida) and os.path.getsize(archivo_salida) > 0:
            registrar_metrica_voz(cfg, texto_limpio)
            return archivo_salida
    except Exception:
        pass
    return None

def transcribir_audio_local(audio_path):
    try:
        from faster_whisper import WhisperModel
        modelo = WhisperModel("base", device="cpu", compute_type="int8")
        segmentos, _ = modelo.transcribe(audio_path, language="es")
        return " ".join([seg.text for seg in segmentos]).strip()
    except Exception:
        return ""

async def enviar_mensaje_en_partes(update: Update, texto: str, max_chunk=4000):
    for i in range(0, len(texto), max_chunk):
        await update.message.reply_text(texto[i:i + max_chunk])

async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.effective_chat.id
    await update.message.reply_text("¡Qué hacés Leandro! LeandroBot activo con Vibe Coding por lotes universal.")

async def comando_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime_min = round((time.time() - TIEMPO_INICIO) / 60, 1)
    await enviar_mensaje_en_partes(update, f"🤖 Uptime: {uptime_min} min\nRepo: {URL_REPOSITORIO}")

async def comando_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        process = psutil.Process(os.getpid())
        ram_mb = process.memory_info().rss / (1024 * 1024)
    except Exception:
        ram_mb = 0.0

    uptime_sec = int(time.time() - TIEMPO_INICIO)
    horas, rem = divmod(uptime_sec, 3600)
    minutos, segundos = divmod(rem, 60)
    uptime_str = f"{horas}h {minutos}m {segundos}s" if horas else f"{minutos}m {segundos}s"

    gemini_status = "Operativo 🟢" if GENAI_DISPONIBLE else "Inactivo 🔴"
    
    ollama_ok = False
    try:
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2.0)
        if r.status_code == 200:
            ollama_ok = True
    except Exception:
        pass
    ollama_status = "Operativo 🟢" if ollama_ok else "Desconectado 🔴"

    msg = (
        "¡Acá andamos vivitos y coleando, che! 🚀\n\n"
        f"🧠 *RAM consumida:* `{ram_mb:.1f} MB`\n"
        f"⏱️ *Uptime:* `{uptime_str}`\n"
        f"⚡ *Gemini API:* `{gemini_status}`\n"
        f"🦙 *Ollama Local:* `{ollama_status}`\n\n"
        "¡El runner está como piña, maestro! 🟢"
    )
    await update.message.reply_text(msg, parse_mode="markdown")

async def comando_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /run <comando>")
        return
    ok, salida = ejecutar_comando_runner_en_vivo(" ".join(context.args))
    await enviar_mensaje_en_partes(update, f"{'✅ [Salida]:' if ok else '❌ [Error]:'}\n{salida}")

async def comando_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nuevo_codigo = " ".join(context.args) if context.args else ""
    if not nuevo_codigo and update.message.reply_to_message:
        nuevo_codigo = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    if not nuevo_codigo:
        await update.message.reply_text("⚠️ Mandame el código con `/codigo <tu_codigo>`.")
        return
    if nuevo_codigo.startswith("```"):
        lines = nuevo_codigo.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        nuevo_codigo = "\n".join(lines)
    with open(CAMBIO_PROPUESTO_FILE, "w", encoding="utf-8") as f:
        f.write(nuevo_codigo.strip())
    if aplicar_cambio_universal("procesar.py", nuevo_codigo.strip()):
        await update.message.reply_text("✅ ¡Código recibido y pusheado! Reiniciando...")
        sys.exit(0)
    else:
        await update.message.reply_text("❌ Error sintáctico o código incompleto en la propuesta.")

async def comando_aplicar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(CAMBIO_PROPUESTO_FILE):
        await update.message.reply_text("⚠️ No hay cambio_propuesto.txt")
        return
    with open(CAMBIO_PROPUESTO_FILE, "r", encoding="utf-8") as f:
        contenido = f.read()
    if aplicar_cambio_universal("procesar.py", contenido):
        await update.message.reply_text("✅ ¡Aplicado y pusheado con éxito! Reiniciando...")
        sys.exit(0)
    else:
        await update.message.reply_text("❌ Error al aplicar cambio.")

async def manejar_mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.effective_chat.id
    texto_usuario = update.message.text
    if not texto_usuario:
        return
    registrar_conversacion("Leandro", texto_usuario)

    prompt_intencion = (
        f"Analiza si el siguiente mensaje solicita modificar, corregir o agregar código/archivos en el repositorio.\n"
        f"Mensaje: '{texto_usuario}'\n"
        f"Responde ÚNICAMENTE 'SI' o 'NO'."
    )
    
    es_solicitud_codigo = False
    try:
        res_int = generar_texto_ia(prompt_intencion, es_modo_codigo=False)
        txt_intencion = (res_int or "").strip().upper()
        print(f"🧠 [INTENT CHECK]: '{texto_usuario[:30]}' -> {txt_intencion}", flush=True)
        if "SI" in txt_intencion:
            es_solicitud_codigo = True
    except Exception as e:
        print(f"⚠️ Error en clasificador: {e}", flush=True)

    if es_solicitud_codigo:
        ruta_archivo = detectar_archivo_objetivo(texto_usuario)
        await update.message.reply_text(f"🧠 Intención detectada sobre '{ruta_archivo}'. Procesando por lotes...")
        
        contenido_compuesto = procesar_cambio_por_lotes(texto_usuario, ruta_archivo)
        
        with open(CAMBIO_PROPUESTO_FILE, "w", encoding="utf-8") as f:
            f.write(contenido_compuesto)

        if aplicar_cambio_universal(ruta_archivo, contenido_compuesto):
            await update.message.reply_text(f"🚀 ¡Actualización en batch aplicada y pusheada para '{ruta_archivo}'! Reiniciando si corresponde...")
            if ruta_archivo == "procesar.py":
                sys.exit(0)
            return
        else:
            await update.message.reply_text(f"❌ Validación fallida para '{ruta_archivo}'. Cambio cancelado para evitar errores.")
            return

    respuesta = generar_texto_ia(texto_usuario, es_modo_codigo=False)
    registrar_conversacion("LeandroBot", respuesta)
    audio_path = await sintetizar_audio_dsp(respuesta)
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file, caption=respuesta[:1024] if len(respuesta) <= 1024 else None)
        if len(respuesta) > 1024:
            await enviar_mensaje_en_partes(update, respuesta)
        os.remove(audio_path)
    else:
        await enviar_mensaje_en_partes(update, respuesta)

async def manejar_mensaje_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.effective_chat.id
    audio_obj = update.message.voice or update.message.audio
    if not audio_obj:
        return
    archivo = await context.bot.get_file(audio_obj.file_id)
    ruta_temp = "input_audio.ogg"
    await archivo.download_to_drive(ruta_temp)
    texto_transcrito = transcribir_audio_local(ruta_temp)
    if os.path.exists(ruta_temp):
        os.remove(ruta_temp)
    texto_transcrito = texto_transcrito or "(Audio ininteligible)"
    registrar_conversacion("Leandro (Audio)", texto_transcrito)

    respuesta = generar_texto_ia(texto_transcrito, es_modo_codigo=False)
    registrar_conversacion("LeandroBot", respuesta)
    audio_path = await sintetizar_audio_dsp(respuesta)
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file, caption=f"🗣 {texto_transcrito[:200]}")
        if len(respuesta) > 200:
            await enviar_mensaje_en_partes(update, respuesta)
        os.remove(audio_path)
    else:
        await enviar_mensaje_en_partes(update, f"🗣 {texto_transcrito}\n\n{respuesta}")

def main():
    if not TOKEN:
        return
    asegurar_ollama_en_runner()
    req = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
    app = Application.builder().token(TOKEN).request(req).build()
    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(CommandHandler("status", comando_status))
    app.add_handler(CommandHandler("health", comando_health))
    app.add_handler(CommandHandler("run", comando_run))
    app.add_handler(CommandHandler("codigo", comando_codigo))
    app.add_handler(CommandHandler("aplicar", comando_aplicar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_mensaje_audio))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
