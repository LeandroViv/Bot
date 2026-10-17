# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / Vibe Coding Atómico por TXT Puente + Single Instance PID + DSP + Whisper

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

PID_FILE = ".bot.pid"
TIEMPO_INICIO = time.time()

def matar_instancia_anterior():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                pid_viejo = int(f.read().strip())
            
            if pid_viejo != os.getpid():
                print(f"🔄 [SINGLE INSTANCE]: Cerrando instancia anterior (PID {pid_viejo})...", flush=True)
                os.kill(pid_viejo, signal.SIGTERM)
                time.sleep(1)
        except (ValueError, ProcessLookupError, PermissionError) as e:
            print(f"ℹ️ Limpiando registro PID previo: {e}", flush=True)
        except Exception as e:
            print(f"⚠️ Aviso al cerrar instancia anterior: {e}", flush=True)

    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"⚠️ No se pudo guardar PID file: {e}", flush=True)

matar_instancia_anterior()

print("🚀 [INIT]: Inicializando LeandroBot Adaptativo (Vibe Coding Atómico por TXT Puente)...", flush=True)

URL_REPOSITORIO = "https://github.com/LeandroViv/Bot"
TXT_FILE = "conversaciones.txt"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
PERFIL_DINAMICO = "perfil_personaje.json"
CAMBIO_PROPUESTO_FILE = "cambio_propuesto.txt"
CORRECCIONES_WHISPER = "correcciones_whisper.json"

for f_path, default_val in [
    (TXT_FILE, ""),
    (DATASET_ENTRENAMIENTO, []),
    (CORRECCIONES_WHISPER, {}),
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

def obtener_codigo_actual():
    """Lee procesar.py completo para entregarlo como contexto base al modelo"""
    if os.path.exists("procesar.py"):
        try:
            with open("procesar.py", "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"⚠️ Error leyendo procesar.py: {e}", flush=True)
    return ""

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
                mapa.append(f"  📄 {path_completo}")
                
    return "\n".join(mapa) if mapa else "  📄 procesar.py\n  📄 config_timbre.json"

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
            print("ℹ️ No hay cambios pendientes para pushear a GitHub.", flush=True)
            return True

        subprocess.run(["git", "commit", "-m", mensaje_commit], check=True)
        subprocess.run(["git", "push", "origin", "HEAD"], check=True)
        
        print(f"🚀 [GIT PUSH EN CALIENTE]: Cambios en '{archivo_modificado}' pusheados como LeandroBot[bot].", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ Aviso git push automático: {e}", flush=True)
        return False

def aplicar_cambio_por_txt_completo(ruta_destino="procesar.py", ruta_txt=CAMBIO_PROPUESTO_FILE):
    """
    Lee el archivo de texto puente completo, valida sintaxis con AST,
    hace backup y sobreescribe de forma atómica sin parches parciales ni inflación.
    """
    if not os.path.exists(ruta_txt):
        print(f"⚠️ No se encontró el archivo puente {ruta_txt}", flush=True)
        return False

    with open(ruta_txt, "r", encoding="utf-8") as f:
        nuevo_contenido = f.read()

    try:
        ast.parse(nuevo_contenido)
    except SyntaxError as e:
        print(f"❌ [ERROR DE SINTAXIS]: El código en {ruta_txt} tiene un error: {e}", flush=True)
        return False

    if os.path.exists(ruta_destino):
        shutil.copy2(ruta_destino, f"{ruta_destino}.bak")

    ruta_tmp = f"{ruta_destino}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        f.write(nuevo_contenido)
    os.replace(ruta_tmp, ruta_destino)

    print(f"✅ [VIBE CODING ATÓMICO]: {ruta_destino} actualizado limpiamente desde {ruta_txt}.", flush=True)
    return guardar_y_pushear_como_leandrobot(ruta_destino, "vibe-coding: actualización atómica por txt puente")

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            cfg = json_lib.load(f)
            vol_raw = str(cfg.get("volume", "+10%"))
            if "db" in vol_raw.lower():
                vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
                cfg["volume"] = f"{vol_num}%"
            return cfg
    except Exception:
        return {
            "voice": "es-AR-TomasNeural",
            "pitch": "-4Hz",
            "rate": "-5%",
            "volume": "+10%",
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

    vol_raw = str(cfg.get("volume", "+10%"))
    vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
    try:
        v_pct = float(vol_num)
        if v_pct != 0:
            mult = round(10 ** (v_pct / 50.0), 2)
            partes.append(f"volume={mult}")
    except Exception:
        pass

    rate_raw = str(cfg.get("rate", "-5%"))
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

def construir_prompt_sistema():
    memoria = obtener_memoria_aprendizaje()
    mapa_repo = obtener_mapa_repositorio()
    codigo_vivo = obtener_codigo_actual()
    return (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense.\n"
        f"REPOSITORIO AUTÓNOMO DE TRABAJO: {URL_REPOSITORIO}\n\n"
        "REGLAS CRÍTICAS DE CÓDIGO Y VIBE CODING ATÓMICO:\n"
        "1. EL USUARIO ES LEANDRO (tu colega). Hablale de 'vos' o 'che'. NUNCA hables de Leandro en tercera persona.\n"
        "2. REGLA LINGÜÍSTICA RIOPLATENSE: Usá voseo porteño real ('mirá', 'fijate', 'decime', 'dale', 'che', 'posta').\n"
        "3. CERO PARCHES PARCIALES NI SED: PROHIBIDO usar comandos sed, expresiones regulares a ciegas o parches parciales.\n"
        "4. PUENTE ATÓMICO Y CÓDIGO COMPLETO: Cuando debas proponer cambios en 'procesar.py', debés usar el código actual provisto a continuación como base, aplicar las mejoras y escribir la TOTALIDAD DEL ARCHIVO de punta a punta dentro de 'cambio_propuesto.txt'. PROHIBIDO omitir o resumir funciones existentes.\n"
        "5. COMANDO /ESTADO COMPLETO: Mantené siempre el handler /estado reportando Uptime, RAM, CPU, OS, Motor IA y Audio.\n"
        "6. CERO RELLENO: Respondé directo, natural para Edge-TTS, sin asteriscos ni markdown roto.\n\n"
        f"MAPA DE ARCHIVOS:\n{mapa_repo}\n\n"
        f"CÓDIGO FUENTE ACTUAL (procesar.py):\n```python\n{codigo_vivo}\n```\n\n"
        f"Historial reciente:\n{memoria}\n"
    )

def generar_texto_ia(prompt_usuario):
    system_prompt = construir_prompt_sistema()
    p = prompt_usuario
    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = prompt_usuario + chr(10) + chr(10) + "[Información fresca]:" + chr(10) + info_web

    if client:
        try:
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=p,
                config=dict(system_instruction=system_prompt)
            )
            raw = (res.text or "").strip()
            if raw: return raw
        except Exception: pass

    if asegurar_ollama_en_runner():
        try:
            prompt_completo = f"{system_prompt}\n\nUsuario: {p}\nLeandro:"
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt_completo, "stream": False},
                timeout=60
            )
            if r.status_code == 200:
                texto = r.json().get("response", "").strip()
                if texto: return texto
        except Exception: pass

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
    voice = cfg.get("voice", "es-AR-TomasNeural")
    pitch = cfg.get("pitch", "-4Hz")
    rate = cfg.get("rate", "-5%")
    volume = f"{re.sub(r'[^0-9+-]', '', str(cfg.get('volume', '+10%')))}%"
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
            "• /codigo <comando o tarea>: Ejecuta comandos de consola o aplica cambios desde un .txt puente.\n"
            "• /estado: Muestra métricas detalladas en tiempo real (Uptime, RAM, CPU, OS, Motor IA y Audio)."
        )

async def manejar_vibe_coding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    texto_raw = (update.message.text or "").strip('\u200b\ufeff\t\r\n ')
    instruccion = re.sub(r'^[/\\]*(codigo|código|vibe)\s*', '', texto_raw, flags=re.IGNORECASE).strip()

    if not instruccion and context.args:
        instruccion = " ".join(context.args).strip()

    if os.path.exists(CAMBIO_PROPUESTO_FILE) and ("aplicar" in instruccion.lower() or "txt" in instruccion.lower() or not instruccion):
        await update.message.reply_text("🔄 Aplicando actualización atómica desde `cambio_propuesto.txt`...")
        exito = aplicar_cambio_por_txt_completo("procesar.py", CAMBIO_PROPUESTO_FILE)
        if exito:
            await update.message.reply_text("🚀 ¡`procesar.py` actualizado limpiamente y pusheado a GitHub sin inflación!")
        else:
            await update.message.reply_text("❌ Error de sintaxis o no se pudo aplicar el `cambio_propuesto.txt`.")
        return

    if not instruccion:
        await update.message.reply_text("Decime qué comando querés correr o mandame el código en `cambio_propuesto.txt`, che.")
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

    resp = generar_texto_ia(instruccion)
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
    v_pitch = cfg_audio.get("pitch", "-4Hz")
    v_vol = cfg_audio.get("volume", "+10%")
    v_voice = cfg_audio.get("voice", "es-AR-TomasNeural")

    sis_info = f"{platform.system()} {platform.release()}"

    await update.message.reply_text(
        f"📊 **Estado del Sistema (Vibe Coding Atómico):**\n"
        f"• Uptime: {uptime_str}\n"
        f"• RAM en uso: {ram_str}\n"
        f"• CPU: {cpu_pct}\n"
        f"• Entorno / OS: {sis_info}\n"
        f"• Motor IA principal: {motor_ia}\n"
        f"• Audio / Timbre: {v_voice} (Pitch: {v_pitch}, Vol: {v_vol})\n"
        f"• PID Activo: {os.getpid()}\n"
        f"• Estado: Operativo y respondiendo impecable, che."
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
    resp = generar_texto_ia(u_text)
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

    print("🚀 [INIT]: Arrancando polling con Vibe Coding Atómico...", flush=True)
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
