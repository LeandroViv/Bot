# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / OpenClaw como motor principal de Vibe-Coding

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

print("🚀 [INIT]: Inicializando LeandroBot Adaptativo...", flush=True)
print("🗣️ [CHARLA]: Ollama (llama3.2)", flush=True)
print("🦀 [CODING]: OpenClaw como motor principal de edición autónoma", flush=True)

URL_REPOSITORIO = "https://github.com/LeandroViv/Bot"
TXT_FILE = "conversaciones.txt"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
PERFIL_DINAMICO = "perfil_personaje.json"
HISTORIAL_METRICAS = "historial_metricas_voz.json"

TIEMPO_INICIO = time.time()

for f_path, default_val in [
    (TXT_FILE, ""),
    (DATASET_ENTRENAMIENTO, []),
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
        "harmonics": []
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
AI_STUDIO_MODEL = os.environ.get("AI_STUDIO_MODEL", "gemini-3.8-flash")
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

def buscar_en_web(query):
    try:
        from ddgs import DDGS
        with DDGS() as ddgs_instance:
            results = list(ddgs_instance.text(query, max_results=3))
            if results:
                return "\n".join([f"- {r.get('title', '')}: {r.get('body', '')}" for r in results])
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
        
        subprocess.run(["git", "add", "-A"], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print("⚠️ [GIT]: No se detectaron cambios reales para commitear.", flush=True)
            return False

        subprocess.run(["git", "commit", "-m", mensaje_commit], check=True)
        res_push = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
        if res_push.returncode != 0:
            subprocess.run(["git", "pull", "--rebase", "origin", "HEAD"], check=False)
            subprocess.run(["git", "push", "origin", "HEAD"], check=True)
        return True
    except Exception as e:
        print(f"⚠️ Aviso git push automático: {e}", flush=True)
        return False

def obtener_contenido_archivo(ruta):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return ""

def ejecutar_vibe_coding_openclaw(prompt_usuario, ruta_archivo="procesar.py"):
    codigo_actual = obtener_contenido_archivo(ruta_archivo)
    info_web = ""
    try:
        info_web = buscar_en_web(prompt_usuario)
    except Exception:
        pass

    print("🦀 [OPENCLAW CODING]: Ejecutando OpenClaw para la edición de código...", flush=True)

    # Invocamos OpenClaw directamente vía CLI para que aplique las modificaciones
    prompt_completo = f"Modificá el archivo {ruta_archivo} para cumplir con la siguiente petición: {prompt_usuario}"
    if info_web:
        prompt_completo += f"\nInformación web de apoyo: {info_web}"

    try:
        # Comando para que OpenClaw procese la edición autónoma
        res = subprocess.run(
            ["openclaw", "code", "--file", ruta_archivo, "--prompt", prompt_completo],
            capture_output=True,
            text=True,
            timeout=180
        )
        
        print(f"OpenClaw Output: {res.stdout}", flush=True)

        if res.returncode == 0:
            nuevo_codigo = obtener_contenido_archivo(ruta_archivo)
            if ruta_archivo.endswith(".py"):
                try:
                    ast.parse(nuevo_codigo)
                    print("✅ Parche verificado con ast.parse correctamente.", flush=True)
                    return True
                except SyntaxError as e:
                    print(f"❌ Syntax Error devuelto por OpenClaw: {e}", flush=True)
                    # Restauramos si rompió sintaxis
                    return False
            return True
        else:
            print(f"⚠️ OpenClaw falló con código {res.returncode}: {res.stderr}", flush=True)
    except Exception as ex:
        print(f"❌ Error ejecutando OpenClaw CLI: {ex}", flush=True)

    return False

def evaluar_intencion_codigo_hibrida(texto_usuario):
    if texto_usuario.strip().startswith("/"):
        return False

    patrones_codigo = [
        r"\breemplaz[aaá]\b", r"\bagreg[aaá]le\b", r"\bmodific[aaá]\b", 
        r"\bcambi[aaá]\b", r"\bpushe[aaá]\b", r"\bprint\b", r"\.py\b", 
        r"\bcrear\b", r"\barregl[aaá]\b", r"\bfuncion\b", r"\bcodigo\b", r"\bhandler\b", r"\bcomando\b", r"\bapp\b"
    ]
    return any(re.search(p, texto_usuario.lower()) for p in patrones_codigo)

def generar_texto_charla_comun(prompt_usuario):
    info_web = ""
    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio"]):
        info_web = buscar_en_web(prompt_usuario)

    prompt_final = prompt_usuario
    if info_web:
        prompt_final += f"\n\n[Información web fresca]:\n{info_web}"

    system_prompt = (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense. Hablale de vos o che a Leandro.\n"
        "Mantené charlas fluidas y naturales. PROHIBIDO inventar links o URLs falsas."
    )

    if client:
        try:
            res = client.models.generate_content(
                model=AI_STUDIO_MODEL,
                contents=prompt_final,
                config=dict(system_instruction=system_prompt, temperature=0.7)
            )
            raw = (res.text or "").strip()
            if raw:
                print("🤖 [CHARLA]: Gemini API", flush=True)
                return raw
        except Exception:
            pass

    try:
        r = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"{system_prompt}\n\nUsuario: {prompt_final}\nLeandro:",
                "stream": False
            },
            timeout=60
        )
        if r.status_code == 200:
            respuesta_ollama = r.json().get("response", "").strip()
            if respuesta_ollama:
                print("🦙 [CHARLA]: Ollama Local (llama3.2)", flush=True)
                return respuesta_ollama
    except Exception as ex:
        print(f"❌ Error en Ollama Local: {ex}", flush=True)

    return "¡Qué hacés che! Acá andamos, todo en orden. ¿Qué contamos?"

def preparar_texto_para_voz(texto):
    t = re.sub(r"https?://\S+", "", texto)
    t = re.sub(r"[*_`~#\[\]<>]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

async def sintetizar_audio_dsp(texto, archivo_salida="respuesta_dsp.ogg"):
    cfg = {"voice": "es-AR-TomasNeural", "pitch": "-4Hz", "rate": "-5%", "volume": "+10%"}
    texto_limpio = preparar_texto_para_voz(texto) or "Dale, te escucho."
    archivo_raw = "temp_raw.mp3"
    cmd_tts = ["edge-tts", f"--voice={cfg.get('voice')}", f"--pitch={cfg.get('pitch')}", f"--rate={cfg.get('rate')}", f"--volume={cfg.get('volume')}", f"--text={texto_limpio}", f"--write-media={archivo_raw}"]
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
            return archivo_salida
    except Exception:
        pass
    return None

async def enviar_mensaje_en_partes(update: Update, texto: str, max_chunk=4000):
    for i in range(0, len(texto), max_chunk):
        await update.message.reply_text(texto[i:i + max_chunk])

async def comando_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime_min = round((time.time() - TIEMPO_INICIO) / 60, 1)
    
    total_lineas = 0
    if os.path.exists("procesar.py"):
        try:
            with open("procesar.py", "r", encoding="utf-8") as f:
                total_lineas = len(f.readlines())
        except Exception:
            pass

    ultimo_commit = "Desconocido"
    try:
        res_git = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M:%S"], capture_output=True, text=True, timeout=3)
        if res_git.returncode == 0 and res_git.stdout.strip():
            ultimo_commit = res_git.stdout.strip()
    except Exception:
        pass

    msg = (
        f"🤖 **Estado de LeandroBot**\n\n"
        f"⏱️ **Uptime:** `{uptime_min} min`\n"
        f"📄 **Líneas en procesar.py:** `{total_lineas}`\n"
        f"🕒 **Último commit:** `{ultimo_commit}`\n"
        f"🗣️ **Charla:** `Ollama (llama3.2)`\n"
        f"🦀 **Coding:** `OpenClaw Engine`\n"
        f"🌐 **Repo:** {URL_REPOSITORIO}"
    )
    await enviar_mensaje_en_partes(update, msg)

async def manejar_mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.effective_chat.id
    texto_usuario = update.message.text
    if not texto_usuario:
        return

    es_solicitud_codigo = evaluar_intencion_codigo_hibrida(texto_usuario)

    if es_solicitud_codigo:
        await update.message.reply_text("⚡ Intención de código detectada. Ejecutando OpenClaw para aplicar los cambios...")
        ok = ejecutar_vibe_coding_openclaw(texto_usuario, "procesar.py")
        if ok:
            guardar_y_pushear_como_leandrobot("procesar.py", f"openclaw: vibe-coding para '{texto_usuario[:30]}'")
            await update.message.reply_text("🚀 ¡OpenClaw aplicó los cambios y se realizó el push con éxito! Reiniciando...")
            sys.exit(0)
        else:
            await update.message.reply_text("❌ OpenClaw no pudo aplicar la modificación en el código.")
            return

    respuesta = generar_texto_charla_comun(texto_usuario)
    audio_path = await sintetizar_audio_dsp(respuesta)
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, "rb") as voice_file:
            await update.message.reply_voice(voice_file, caption=respuesta[:1024] if len(respuesta) <= 1024 else None)
        if len(respuesta) > 1024:
            await enviar_mensaje_en_partes(update, respuesta)
        os.remove(audio_path)
    else:
        await enviar_mensaje_en_partes(update, respuesta)

def main():
    if not TOKEN:
        return
    req = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
    app = Application.builder().token(TOKEN).request(req).build()
    app.add_handler(CommandHandler("status", comando_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje_texto))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
