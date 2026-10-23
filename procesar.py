# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot Runner GitHub Actions + Aider Rápido

import asyncio
import json
import os
import re
import sys
import subprocess
import requests
import time
import ast
import urllib.parse

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

print("🚀 [INIT]: Inicializando LeandroBot con Aider optimizado...", flush=True)

URL_REPOSITORIO = "https://github.com/LeandroViv/Bot"
TXT_FILE = "conversaciones.txt"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
PERFIL_DINAMICO = "perfil_personaje.json"
HISTORIAL_METRICAS = "historial_metricas_voz.json"

TIEMPO_INICIO = time.time()

# Inicialización de archivos locales con json nativo
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
        "volume": "+10%"
    })
]:
    if not os.path.exists(f_path):
        if isinstance(default_val, str):
            with open(f_path, "w", encoding="utf-8") as f:
                f.write(default_val)
        else:
            with open(f_path, "w", encoding="utf-8") as f:
                json.dump(default_val, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3")

def buscar_en_web(query):
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            titulos = re.findall(r'<a class="result__url"[^>]*>(.*?)</a>', res.text)
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', res.text)
            
            resultados = []
            for t, s in zip(titulos[:3], snippets[:3]):
                t_limpio = re.sub(r'<[^>]+>', '', t).strip()
                s_limpio = re.sub(r'<[^>]+>', '', s).strip()
                if t_limpio and s_limpio:
                    resultados.append(f"- {t_limpio}: {s_limpio}")
            
            return "\n".join(resultados)
    except Exception as e:
        print(f"⚠️ Error en búsqueda web: {e}", flush=True)
    return ""

def guardar_y_pushear_como_leandrobot(archivo_modificado, mensaje_commit):
    gh_token = os.environ.get("GH_BOT_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        subprocess.run(["git", "config", "user.name", "LeandroBot[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "leandrobot@users.noreply.github.com"], check=True)
        
        if gh_token:
            remote_url = f"https://x-access-token:{gh_token}@github.com/LeandroViv/Bot.git"
            subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)
        
        subprocess.run(["git", "add", "-A"], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print("⚠️ [GIT]: No se detectaron cambios para commitear.", flush=True)
            return False

        subprocess.run(["git", "commit", "-m", mensaje_commit], check=True)
        res_push = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
        
        if res_push.returncode != 0:
            subprocess.run(["git", "pull", "--rebase", "origin", "HEAD"], check=False)
            subprocess.run(["git", "push", "origin", "HEAD"], check=True)
            
        print("✅ [GIT]: Cambios pusheados a GitHub correctamente.", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ Error en git push automático: {e}", flush=True)
        return False

def obtener_contenido_archivo(ruta):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return ""

def ejecutar_vibe_coding_aider(prompt_usuario, ruta_archivo="procesar.py"):
    """Usa Aider para aplicar parches quirúrgicos rápidos sin reescribir todo el archivo."""
    try:
        env = os.environ.copy()
        env["OLLAMA_API_BASE"] = OLLAMA_HOST

        cmd = [
            "aider",
            "--model", f"ollama/{OLLAMA_MODEL}",
            "--message", prompt_usuario,
            "--yes",
            "--no-auto-commits",
            "--no-pretty",
            "--map-tokens", "256",
            ruta_archivo
        ]

        print(f"🤖 [AIDER RÁPIDO]: Modificando {ruta_archivo}...", flush=True)
        res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)

        if res.returncode == 0:
            codigo_nuevo = obtener_contenido_archivo(ruta_archivo)
            if ruta_archivo.endswith(".py"):
                try:
                    ast.parse(codigo_nuevo)
                except SyntaxError as e:
                    print(f"❌ Error de Sintaxis (AST): {e}", flush=True)
                    return False
            print("✅ ¡Aider aplicó los cambios correctamente!", flush=True)
            return True
        else:
            print(f"⚠️ Aider devolvió error: {res.stderr}", flush=True)
    except subprocess.TimeoutExpired:
        print("❌ Error: Aider superó el tiempo límite.", flush=True)
    except Exception as ex:
        print(f"❌ Error ejecutando Aider: {ex}", flush=True)
    
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
    palabras_busqueda = ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio", "quién es", "cuándo", "resultado", "dólar", "merval"]
    
    info_web = ""
    if any(k in prompt_usuario.lower() for k in palabras_busqueda):
        info_web = buscar_en_web(prompt_usuario)

    prompt_final = prompt_usuario
    if info_web:
        prompt_final += f"\n\n[Información web fresca obtenida en tiempo real]:\n{info_web}"

    system_prompt = (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense. Hablale de vos o che a Leandro.\n"
        "Mantené charlas fluidas y naturales."
    )

    try:
        r = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"{system_prompt}\n\nUsuario: {prompt_final}\nLeandro:",
                "stream": False,
                "options": {"num_predict": 256, "temperature": 0.7}
            },
            timeout=30
        )
        if r.status_code == 200:
            respuesta_ollama = r.json().get("response", "").strip()
            if respuesta_ollama:
                return respuesta_ollama
    except Exception as ex:
        print(f"❌ Error en Ollama: {ex}", flush=True)

    return "¡Qué hacés che! Acá andamos, todo en orden desde el runner. ¿En qué andamos?"

def preparar_texto_para_voz(texto):
    t = re.sub(r"https?://\S+", "", texto)
    t = re.sub(r"[*_`~#\[\]<>]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

async def sintetizar_audio_dsp(texto, archivo_salida="respuesta_dsp.mp3"):
    cfg = {"voice": "es-AR-TomasNeural", "pitch": "-4Hz", "rate": "-5%", "volume": "+10%"}
    if os.path.exists(CONFIG_TIMBRE):
        try:
            with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass

    texto_limpio = preparar_texto_para_voz(texto) or "Dale, te escucho."
    cmd_tts = [
        "edge-tts",
        f"--voice={cfg.get('voice', 'es-AR-TomasNeural')}",
        f"--pitch={cfg.get('pitch', '-4Hz')}",
        f"--rate={cfg.get('rate', '-5%')}",
        f"--volume={cfg.get('volume', '+10%')}",
        f"--text={texto_limpio}",
        f"--write-media={archivo_salida}"
    ]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd_tts, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        if os.path.exists(archivo_salida) and os.path.getsize(archivo_salida) > 0:
            return archivo_salida
    except Exception as e:
        print(f"⚠️ Error en sintetizar_audio_dsp: {e}", flush=True)
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

    msg = (
        f"🤖 **Estado de LeandroBot (GitHub Actions)**\n\n"
        f"⏱️ **Uptime:** `{uptime_min} min`\n"
        f"📄 **Líneas en procesar.py:** `{total_lineas}`\n"
        f"☁️ **Entorno:** `GitHub Actions Runner + Aider`\n"
        f"🌐 **Repo Git:** {URL_REPOSITORIO}"
    )
    await enviar_mensaje_en_partes(update, msg)

async def manejar_mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.is_bot:
        return

    texto_usuario = update.message.text
    if not texto_usuario:
        return

    es_solicitud_codigo = evaluar_intencion_codigo_hibrida(texto_usuario)

    if es_solicitud_codigo:
        await update.message.reply_text("⚡ Modificando código con Aider...")
        ok = ejecutar_vibe_coding_aider(texto_usuario, "procesar.py")
        if ok:
            if os.path.exists("procesar.py"):
                with open("procesar.py", "rb") as py_doc:
                    await update.message.reply_document(
                        document=py_doc,
                        filename="procesar.py",
                        caption="📄 Código modificado por Aider."
                    )
            
            guardar_y_pushear_como_leandrobot("procesar.py", f"aider: cambio rápido para '{texto_usuario[:30]}'")
            await update.message.reply_text("🚀 Cambios subidos. Reiniciando runner...")
            
            await context.application.stop()
            sys.exit(0)
        else:
            await update.message.reply_text("❌ No se pudo aplicar la modificación.")
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
        print("❌ Error: Variable TELEGRAM_BOT_TOKEN no configurada.", flush=True)
        return
    req = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
    app = Application.builder().token(TOKEN).request(req).build()
    app.add_handler(CommandHandler("status", comando_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje_texto))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
