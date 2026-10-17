# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / Vibe Coding Autónomo con Contexto Total de Todo el Repositorio

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
import signal
import platform
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

PID_FILE = os.environ.get("BOT_PID_FILE", ".bot.pid")
SCRIPT_PRINCIPAL = os.environ.get("BOT_SCRIPT_NAME", "procesar.py")
TXT_FILE = os.environ.get("BOT_CHAT_LOG", "conversaciones.txt")
DATASET_ENTRENAMIENTO = os.environ.get("BOT_DATASET_FILE", "dataset_entrenamiento_chat.json")
CONFIG_TIMBRE = os.environ.get("BOT_TIMBRE_FILE", "config_timbre.json")
PERFIL_DINAMICO = os.environ.get("BOT_PROFILE_FILE", "perfil_personaje.json")
CORRECCIONES_WHISPER = os.environ.get("BOT_WHISPER_CORRECTIONS", "correcciones_whisper.json")
URL_REPOSITORIO = os.environ.get("BOT_URL_REPO", "https://github.com/LeandroViv/Bot")

DEFAULT_VOICE = os.environ.get("BOT_DEFAULT_VOICE", "es-AR-TomasNeural")
DEFAULT_PITCH = os.environ.get("BOT_DEFAULT_PITCH", "-4Hz")
DEFAULT_RATE = os.environ.get("BOT_DEFAULT_RATE", "-5%")
DEFAULT_VOLUME = os.environ.get("BOT_DEFAULT_VOLUME", "+10%")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

TIEMPO_INICIO = time.time()
CHAT_ID_ACTIVO = None

def matar_instancia_anterior():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                pid_viejo = int(f.read().strip())
            
            if pid_viejo != os.getpid():
                print(f"🔄 [SINGLE INSTANCE]: Cerrando instancia anterior (PID {pid_viejo})...", flush=True)
                os.kill(pid_viejo, signal.SIGTERM)
                time.sleep(1)
                try:
                    os.kill(pid_viejo, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        except (ValueError, ProcessLookupError, PermissionError) as e:
            print(f"ℹ️ Limpiando registro PID previo: {e}", flush=True)
        except Exception as e:
            print(f"⚠️ Aviso al cerrar instancia anterior: {e}", flush=True)

    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"⚠️ No se pudo guardar PID file: {e}", flush=True)

    gh_token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_BOT_TOKEN")
    current_run_id = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY", "LeandroViv/Bot")
    if gh_token and current_run_id:
        try:
            headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "LeandroBot"}
            for estado in ["in_progress", "queued"]:
                res = requests.get(f"https://api.github.com/repos/{repo}/actions/runs?status={estado}", headers=headers, timeout=10)
                if res.status_code == 200:
                    runs = res.json().get("workflow_runs", [])
                    for r in runs:
                        r_id = str(r.get("id"))
                        if r_id != str(current_run_id):
                            print(f"🛑 [RUNNER CI]: Cancelando runner {estado} anterior (Run ID: {r_id})...", flush=True)
                            requests.post(f"https://api.github.com/repos/{repo}/actions/runs/{r_id}/cancel", headers=headers, timeout=10)
        except Exception as e:
            print(f"⚠️ Aviso al cancelar runner anterior en GitHub: {e}", flush=True)

matar_instancia_anterior()

print("🚀 [INIT]: Inicializando LeandroBot Adaptativo (Contexto Total de Repositorio)...", flush=True)

for f_path, default_val in [
    (TXT_FILE, ""),
    (DATASET_ENTRENAMIENTO, []),
    (CORRECCIONES_WHISPER, {}),
    ("memoria_tareas.json", [{"tarea": "Escribirle a Leandro en el día", "pendiente": True, "estado": "pendiente"}]),
    (PERFIL_DINAMICO, {
        "nombre": "Leandro",
        "estilo": "Colega y compañero de vibe coding con tonada rioplatense, yeísmo y ritmo auténtico",
        "notas_aprendizaje": []
    }),
    (CONFIG_TIMBRE, {
        "voice": DEFAULT_VOICE,
        "pitch": DEFAULT_PITCH,
        "rate": DEFAULT_RATE,
        "volume": DEFAULT_VOLUME,
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

try:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    GENAI_DISPONIBLE = True if client else False
except Exception:
    client = None
    GENAI_DISPONIBLE = False

def asegurar_ollama_en_runner():
    try:
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3.0)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        print(f"🦙 [OLLAMA RUNNER]: Intentando conectar / levantar servicio en {OLLAMA_HOST}...", flush=True)
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(3)
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3.0)
        if r.status_code == 200:
            print("🦙 [OLLAMA RUNNER]: ¡Servicio conectado con éxito en el runner!", flush=True)
            return True
    except Exception as ex:
        print(f"⚠️ Aviso conexión Ollama en runner: {ex}", flush=True)
    return False

def ejecutar_comando_runner_en_vivo(cmd_str):
    try:
        print(f"💻 [TERMINAL RUNNER]: Ejecutando -> {cmd_str}", flush=True)
        res = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        salida = res.stdout.strip() if res.stdout else res.stderr.strip()
        if not salida:
            salida = "Comando ejecutado con éxito (sin salida gráfica)."
        return True, salida
    except Exception as e:
        return False, f"Error ejecutando comando: {str(e)}"

def obtener_contexto_total_repositorio(root_dir="."):
    """
    Lee y concatena el contenido íntegro de TODOS los archivos del repositorio 
    (py, json, md, txt, sh, yml) para pasárselo completo a la IA como contexto absoluto.
    """
    contexto_partes = []
    ignorar_dirs = {".git", "__pycache__", ".github", "venv", "downloads", ".pytest_cache"}
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in ignorar_dirs]
        rel_dir = os.path.relpath(dirpath, root_dir)
        if rel_dir == ".":
            rel_dir = ""
            
        for f in filenames:
            if f.endswith((".py", ".json", ".md", ".txt", ".sh", ".yml", ".env.example")):
                ruta_rel = os.path.join(rel_dir, f) if rel_dir else f
                try:
                    with open(ruta_rel, "r", encoding="utf-8") as ar:
                        contenido = ar.read()
                        contexto_partes.append(f"=== ARCHIVO: {ruta_rel} ===\n```\n{contenido}\n```")
                except Exception as e:
                    contexto_partes.append(f"=== ARCHIVO: {ruta_rel} (Error de lectura: {e}) ===\n")
                    
    return "\n\n".join(contexto_partes) if contexto_partes else "Repositorio vacío."

def guardar_y_pushear_como_leandrobot(archivo_modificado, mensaje_commit):
    gh_token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_BOT_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "LeandroViv/Bot")
    try:
        subprocess.run(["git", "config", "--global", "--add", "safe.directory", "*"], check=False)
        subprocess.run(["git", "config", "user.name", "LeandroBot[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "leandrobot@users.noreply.github.com"], check=True)
        
        if gh_token:
            remote_url = f"https://x-access-token:{gh_token}@github.com/{repo}.git"
            subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)

        subprocess.run(["git", "add", archivo_modificado], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print("ℹ️ No hay cambios pendientes para pushear a GitHub.", flush=True)
            return True

        subprocess.run(["git", "commit", "-m", mensaje_commit], check=True)
        res_push = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
        if res_push.returncode != 0:
            print("⚠️ [GIT PUSH RETRY]: Intentando pull --rebase antes de reintentar push...", flush=True)
            subprocess.run(["git", "pull", "--rebase", "origin", "HEAD"], check=False)
            subprocess.run(["git", "push", "origin", "HEAD"], check=True)
        
        print(f"🚀 [GIT PUSH EN CALIENTE]: Cambios en '{archivo_modificado}' pusheados con éxito.", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ Aviso git push automático: {e}", flush=True)
        return False

def aplicar_cambio_llave_maestra(ruta_archivo, nuevo_contenido):
    try:
        dir_name = os.path.dirname(ruta_archivo)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        if ruta_archivo.endswith(".py"):
            try:
                ast.parse(nuevo_contenido)
            except SyntaxError as e:
                return False, f"Error de sintaxis Python en {ruta_archivo}: {e}"

        if os.path.exists(ruta_archivo):
            shutil.copy2(ruta_archivo, f"{ruta_archivo}.bak")

        ruta_tmp = f"{ruta_archivo}.tmp"
        with open(ruta_tmp, "w", encoding="utf-8") as f:
            f.write(nuevo_contenido)
        os.replace(ruta_tmp, ruta_archivo)

        print(f"✅ [LLAVE MAESTRA]: Archivo '{ruta_archivo}' actualizado correctamente.", flush=True)
        guardar_y_pushear_como_leandrobot(ruta_archivo, f"vibe-coding: actualización universal de {ruta_archivo}")
        return True, ""
    except Exception as e:
        return False, str(e)

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            cfg = json_lib.load(f)
            vol_raw = str(cfg.get("volume", DEFAULT_VOLUME))
            if "db" in vol_raw.lower():
                vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
                cfg["volume"] = f"{vol_num}%"
            return cfg
    except Exception:
        return {
            "voice": DEFAULT_VOICE,
            "pitch": DEFAULT_PITCH,
            "rate": DEFAULT_RATE,
            "volume": DEFAULT_VOLUME,
            "f0Hz": 125,
            "harmonics": [],
            "descripcion": "Motor acústico dinámico"
        }

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}" + chr(10))
        print(f"📝 [LOG CHAT] [{remitente}]: {texto[:80]}...", flush=True)
    except Exception as e:
        print(f"⚠️ Error conversacion: {e}", flush=True)

def obtener_memoria_aprendizaje():
    if not os.path.exists(TXT_FILE):
        return ""
    try:
        with open(TXT_FILE, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        ultimas = lineas[-14:] if len(lineas) >= 14 else lineas
        return "".join(ultimas)
    except Exception:
        return ""

def buscar_en_web(query):
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        with DDGS() as ddgs_instance:
            results = list(ddgs_instance.text(query, max_results=3))
            if results:
                lineas = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
                print(f"🌐 [WEB SEARCH]: {query[:40]}...", flush=True)
                return "\n".join(lineas)
    except Exception as e:
        print(f"⚠️ Aviso búsqueda web: {e}", flush=True)
    return ""

def construir_filtro_ffmpeg_desde_armonicos(cfg):
    partes = []
    harmonics = cfg.get("harmonics", [])
    
    for h in harmonics:
        if h.get("enabled", True) and h.get("gainDb", 0) != 0:
            hz = h.get("hz", 0)
            gain = max(-18.0, min(12.0, float(h.get("gainDb", 0))))
            q = max(1.0, min(4.0, float(h.get("q", 2.0))))
            if 50 < hz < 16000:
                partes.append(f"equalizer=f={hz}:width_type=q:w={q}:g={gain}")

    vol_raw = str(cfg.get("volume", DEFAULT_VOLUME))
    vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
    try:
        v_pct = float(vol_num)
        if v_pct != 0:
            mult = round(10 ** (v_pct / 50.0), 2)
            partes.append(f"volume={mult}")
    except Exception:
        pass

    rate_raw = str(cfg.get("rate", DEFAULT_RATE))
    rate_num = re.sub(r'[^0-9+-]', '', rate_raw)
    try:
        r_pct = float(rate_num)
        if r_pct != 0:
            tempo = max(0.7, min(1.4, round(1.0 + r_pct / 100.0, 2)))
            if tempo != 1.0:
                partes.append(f"atempo={tempo}")
    except Exception:
        pass

    return ",".join(partes)

def construir_prompt_sistema(es_modo_codigo=False):
    contexto_repo = obtener_contexto_total_repositorio()

    if es_modo_codigo:
        return (
            "SOS UN AGENTE DE VIBE CODING AUTÓNOMO CON LLAVE MAESTRA ABSOLUTA SOBRE EL REPOSITORIO.\n"
            f"REPOSITORIO OFICIAL: {URL_REPOSITORIO}\n\n"
            f"CONTENIDO ÍNTEGRO DE TODOS LOS ARCHIVOS DEL REPOSITORIO:\n{contexto_repo}\n\n"
            "INSTRUCCIONES CRÍTICAS DE EJECUCIÓN:\n"
            "1. NO HABLES, NO SALUDES, NO EXPLIQUES, NO PIDAS CONFIRMACIÓN.\n"
            "2. DEBES INDICAR LA RUTA EXACTA DEL ARCHIVO AL INICIO DEL BLOQUE (Ejemplo: `# ARCHIVO: procesar.py` o `# ARCHIVO: memoria_tareas.json`).\n"
            "3. DEVOLVÉ ÚNICAMENTE EL BLOQUE ```python ... ``` CON EL CONTENIDO COMPLETO O MODIFICADO DEL ARCHIVO.\n"
        )

    memoria = obtener_memoria_aprendizaje()
    return (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense.\n"
        f"REPOSITORIO OFICIAL: {URL_REPOSITORIO}\n\n"
        "REGLAS LINGÜÍSTICAS Y DE CHAT:\n"
        "1. EL USUARIO ES LEANDRO. Hablale de 'vos' o 'che'. Usá voseo porteño real ('mirá', 'fijate', 'decime', 'dale', 'che', 'posta').\n"
        "2. CERO RELLENO: Respondé directo y al pie.\n\n"
        f"Historial reciente:\n{memoria}\n"
    )

def generar_texto_ia(prompt_usuario, es_modo_codigo=False):
    system_prompt = construir_prompt_sistema(es_modo_codigo=es_modo_codigo)
    p = prompt_usuario
    if not es_modo_codigo and any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = prompt_usuario + chr(10) + chr(10) + "[Información fresca]:" + chr(10) + info_web

    if client:
        try:
            print(f"🤖 [IA ENGINE]: Consultando Gemini API (Modo Contexto Total: {es_modo_codigo})...", flush=True)
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=p,
                config=dict(system_instruction=system_prompt)
            )
            raw = (res.text or "").strip()
            if raw: 
                print(f"✅ [IA ENGINE]: Respuesta recibida de Gemini ({len(raw)} chars).", flush=True)
                return raw
        except Exception as e:
            print(f"⚠️ [IA ENGINE ERROR - Gemini]: {e}", flush=True)

    if asegurar_ollama_en_runner():
        try:
            print(f"🤖 [IA ENGINE]: Fallback a Ollama ({OLLAMA_MODEL})...", flush=True)
            prompt_completo = f"{system_prompt}\n\nUsuario: {p}\nLeandro:"
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt_completo, "stream": False, "keep_alive": "5m"},
                timeout=180
            )
            if r.status_code == 200:
                texto = r.json().get("response", "").strip()
                if texto: 
                    print(f"✅ [IA ENGINE]: Respuesta recibida de Ollama ({len(texto)} chars).", flush=True)
                    return texto
        except Exception as ex:
            print(f"⚠️ [IA ENGINE ERROR - Ollama]: {ex}", flush=True)

    print("❌ [IA ENGINE]: Todos los motores fallaron, devolviendo respuesta default.", flush=True)
    return "¡Qué hacés che! Te capté perfecto. Mandale nomás."

def preparar_texto_para_voz(texto):
    t = re.sub(r'```[\s\S]*?```', 'Te pasé el bloque de código por texto para que lo mires tranqui.', texto)
    t = t.replace("*", "").replace("_", "").replace(chr(96), "").replace("#", "").strip()
    t = re.sub(r'\b(che|mirá|fijate|escuchá|vení|posta)\b', r'\g<1>...', t, flags=re.IGNORECASE)
    palabras = t.split()
    if len(palabras) > 60:
        t = " ".join(palabras[:55]) + "... te lo resumo hasta acá, che."
    return t.strip()

async def sintetizar_voz_edge_tts(texto, ogg_salida="resp.ogg"):
    cfg = cargar_config_timbre()
    voice = cfg.get("voice", DEFAULT_VOICE)
    pitch = cfg.get("pitch", DEFAULT_PITCH)
    rate = cfg.get("rate", DEFAULT_RATE)
    volume = f"{re.sub(r'[^0-9+-]', '', str(cfg.get('volume', DEFAULT_VOLUME)))}%"
    texto_oral = preparar_texto_para_voz(texto)

    try:
        import edge_tts
        communicate = edge_tts.Communicate(texto_oral, voice=voice, pitch=pitch, rate=rate, volume=volume)
        mp3_tmp = f"tmp_edge_{int(time.time()*1000)}.mp3"
        await communicate.save(mp3_tmp)

        if not os.path.exists(mp3_tmp) or os.path.getsize(mp3_tmp) < 100:
            return False, None

        filtro_af = construir_filtro_ffmpeg_desde_armonicos(cfg)
        cmd_ffmpeg = ["ffmpeg", "-y", "-i", mp3_tmp]
        if filtro_af: cmd_ffmpeg.extend(["-af", filtro_af])
        cmd_ffmpeg.extend(["-ar", "48000", "-ac", "1", "-c:a", "libopus", "-b:a", "48k", ogg_salida])
        subprocess.run(cmd_ffmpeg, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if os.path.exists(mp3_tmp):
            try: os.remove(mp3_tmp)
            except Exception: pass

        if os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 200:
            return True, ogg_salida
        return False, None
    except Exception:
        return False, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text(
            f"¡Qué hacés che! Acá Leandro.\nRepo: {URL_REPOSITORIO}\n\n"
            f"• /codigo <instrucción>: Modifica cualquier archivo del repo con Llave Maestra y contexto total.\n"
            "• /estado: Muestra métricas detalladas y tareas pendientes."
        )

async def manejar_vibe_coding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    texto_raw = (update.message.text or "").strip('\u200b\ufeff\t\r\n ')
    instruccion = re.sub(r'^[/\\]*(codigo|código|vibe)\s*', '', texto_raw, flags=re.IGNORECASE).strip()

    if not instruccion and context.args:
        instruccion = " ".join(context.args).strip()

    if not instruccion:
        await update.message.reply_text(f"Decime qué comando querés correr o qué archivo modificamos, che.")
        return

    u_low = instruccion.lower()
    if u_low.startswith(("pip ", "python ", "git ", "ls", "pwd", "apt", "curl", "npm")) or "instalar" in u_low:
        cmd = instruccion
        if "instalar " in u_low:
            paquete = instruccion.split("instalar ", 1)[1].strip()
            cmd = f"{sys.executable} -m pip install --upgrade {paquete}"
        ok, salida = ejecutar_comando_runner_en_vivo(cmd)
        await update.message.reply_text(f"💻 **Consola Runner Output:**\n```\n{salida[:1500]}\n```", parse_mode="Markdown")
        return

    print(f"🤖 [CONTEXTO TOTAL]: Procesando instrucción de Leandro: '{instruccion[:60]}...'", flush=True)
    await update.message.reply_text(f"🧠 Leyendo todos los archivos del repo y aplicando cambio autónomo...")

    t0 = time.time()
    resp = generar_texto_ia(instruccion, es_modo_codigo=True)
    duracion = round(time.time() - t0, 2)

    print(f"🤖 [CONTEXTO TOTAL]: IA respondió en {duracion}s (Longitud: {len(resp)} chars)", flush=True)

    match_code = re.search(r'```python\s*([\s\S]*?)\s*```', resp)
    if match_code:
        fragmento_generado = match_code.group(1).strip()
        
        ruta_destino = SCRIPT_PRINCIPAL
        match_archivo = re.search(r'#\s*(?:ARCHIVO|PATH|FILE):\s*([^\s\n]+)', fragmento_generado, re.IGNORECASE)
        if match_archivo:
            ruta_destino = match_archivo.group(1).strip()
            fragmento_generado = re.sub(r'#\s*(?:ARCHIVO|PATH|FILE):\s*[^\s\n]+\n?', '', fragmento_generado, count=1).strip()

        print(f"📄 [CONTEXTO TOTAL]: Destino detectado -> '{ruta_destino}' ({len(fragmento_generado)} chars). Aplicando...", flush=True)
        
        exito, err = aplicar_cambio_llave_maestra(ruta_destino, fragmento_generado)
        if exito:
            await update.message.reply_text(
                f"🚀 **¡Modificación aplicada con éxito en {duracion}s!**\n\n"
                f"Archivo modificado: `{ruta_destino}`.\nIntegrado, validado y pusheado a GitHub.",
                parse_mode="Markdown"
            )
            return
        else:
            await update.message.reply_text(f"⚠️ Error al aplicar cambio (`{err}`). No se modificó el archivo.")
            return

    print("⚠️ [CONTEXTO TOTAL]: La respuesta no incluyó un bloque ```python ... ``` válido.", flush=True)
    await update.message.reply_text(resp)

async def manejar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    segundos = int(time.time() - TIEMPO_INICIO)
    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    secs = segundos % 60
    uptime_str = f"{horas}h {minutos}m {secs}s"

    try:
        import psutil
        process = psutil.Process(os.getpid())
        ram_mb = process.memory_info().rss / (1024 * 1024)
        ram_str = f"{ram_mb:.2f} MB"
        cpu_pct = f"{psutil.cpu_percent(interval=None)}%"
    except Exception:
        ram_str = "psutil no disponible"
        cpu_pct = "N/A"

    motor_ia = "Gemini 3.8 Flash" if GENAI_DISPONIBLE else f"Ollama ({OLLAMA_MODEL})"
    cfg_audio = cargar_config_timbre()
    v_pitch = cfg_audio.get("pitch", DEFAULT_PITCH)
    v_vol = cfg_audio.get("volume", DEFAULT_VOLUME)
    v_voice = cfg_audio.get("voice", DEFAULT_VOICE)

    sis_info = f"{platform.system()} {platform.release()}"
    total_lineas = 0
    if os.path.exists(SCRIPT_PRINCIPAL):
        try:
            with open(SCRIPT_PRINCIPAL, "r", encoding="utf-8") as f:
                total_lineas = len(f.readlines())
        except Exception:
            pass

    tareas_pendientes = []
    if os.path.exists("memoria_tareas.json"):
        try:
            with open("memoria_tareas.json", "r", encoding="utf-8") as f:
                datos = json_lib.load(f)
                lista = datos if isinstance(datos, list) else datos.get("tareas", [])
                for t in lista:
                    if isinstance(t, dict):
                        if t.get("pendiente", True) and t.get("estado") != "completada":
                            tareas_pendientes.append(t.get("tarea", str(t)))
                    else:
                        tareas_pendientes.append(str(t))
        except Exception as e:
            print(f"⚠️ Error leyendo memoria_tareas.json: {e}", flush=True)

    bloque_tareas = "\n".join([f"• {t}" for t in tareas_pendientes]) if tareas_pendientes else "• Ninguna tarea pendiente."

    await update.message.reply_text(
        f"¡Qué hacés, Leandro! 🚀\n\n"
        f"📊 **Estado del Sistema (Contexto Total Repo):**\n"
        f"• Uptime: {uptime_str}\n"
        f"• RAM en uso: {ram_str}\n"
        f"• CPU: {cpu_pct}\n"
        f"• Entorno / OS: {sis_info}\n"
        f"• Motor IA principal: {motor_ia}\n"
        f"• Audio / Timbre: {v_voice} (Pitch: {v_pitch}, Vol: {v_vol})\n"
        f"• PID Activo: {os.getpid()}\n"
        f"• Estado: Operativo y respondiendo impecable, che.\n"
        f"• Total de líneas en {SCRIPT_PRINCIPAL}: {total_lineas}\n\n"
        f"📋 **Tareas Pendientes (`memoria_tareas.json`):**\n{bloque_tareas}"
    )

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id

    u_text = (update.message.text or update.message.caption or "").strip('\u200b\ufeff\t\r\n ')
    if re.search(r'^[/\\]*(codigo|código|vibe)', u_text, re.IGNORECASE):
        await manejar_vibe_coding(update, context)
        return

    if not u_text:
        u_text = "¡Qué hacés che! Decime cómo andás."

    registrar_conversacion("Usuario", u_text)
    resp = generar_texto_ia(u_text, es_modo_codigo=False)
    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = f"resp_{int(time.time())}.ogg"
    exito, archivo_audio = await sintetizar_voz_edge_tts(resp, ogg_f)
    if exito and archivo_audio and os.path.exists(archivo_audio):
        try:
            with open(archivo_audio, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption="📻 Leandro")
        except Exception: pass
        try: os.remove(archivo_audio)
        except Exception: pass

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta la variable TELEGRAM_BOT_TOKEN.", flush=True)
        return

    print("🚀 [INIT]: Arrancando polling con Contexto Total de Repositorio...", flush=True)
    
    if os.path.exists("memoria_tareas.json"):
        try:
            with open("memoria_tareas.json", "r", encoding="utf-8") as f:
                datos = json_lib.load(f)
                lista = datos if isinstance(datos, list) else datos.get("tareas", [])
                pendientes = [
                    t.get("tarea", str(t)) if isinstance(t, dict) else str(t) 
                    for t in lista 
                    if not isinstance(t, dict) or (t.get("pendiente", True) and t.get("estado") != "completada")
                ]
                if pendientes:
                    print(f"📋 [TAREAS EN ARRANQUE]: {len(pendientes)} tarea(s) pendiente(s):", flush=True)
                    for t in pendientes:
                        print(f"  ▫️ {t}", flush=True)
                else:
                    print("📋 [TAREAS EN ARRANQUE]: Sin tareas pendientes.", flush=True)
        except Exception as e:
            print(f"⚠️ Error leyendo memoria_tareas.json en arranque: {e}", flush=True)
    else:
        print("📋 [TAREAS EN ARRANQUE]: memoria_tareas.json no existe aún.", flush=True)

    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("codigo", manejar_vibe_coding))
    app.add_handler(CommandHandler("vibe", manejar_vibe_coding))
    app.add_handler(CommandHandler("estado", manejar_estado))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, manejar_mensaje))

    print("🔄 [POLLING]: Bot escuchando en Telegram...", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
