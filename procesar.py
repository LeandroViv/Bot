[FORCE_OVERWRITE]
# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / Vibe Coding Atómico por TXT Puente + Terminal Runner + DSP + Whisper + Métricas de Voz

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
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

print("🚀 [INIT]: Inicializando LeandroBot Adaptativo (Vibe Coding Atómico por TXT Puente)...", flush=True)

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
        print("📊 [MÉTRICA VOZ]: Métrica registrada correctamente.", flush=True)
    except Exception as e:
        print(f"⚠️ Error registrando métrica de voz: {e}", flush=True)

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
            salida = "Comando ejecutado con éxito (sin salida en consola)."
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
    if not os.path.exists(ruta_txt):
        print(f"⚠️ No se encontró el archivo puente {ruta_txt}", flush=True)
        return False

    with open(ruta_txt, "r", encoding="utf-8") as f:
        nuevo_contenido = f.read()

    lineas = nuevo_contenido.splitlines()
    if lineas and lineas[0].strip() == "[FORCE_OVERWRITE]":
        nuevo_contenido = "\n".join(lineas[1:]).lstrip()

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
                vol_num = re.sub(r"[^0-9+-]", "", vol_raw)
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
            f.write(f"[{ts}] {remitente}: {texto}\n")
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
    vol_num = re.sub(r"[^0-9+-]", "", vol_raw)
    try:
        v_pct = float(vol_num)
        if v_pct != 0:
            mult = round(10 ** (v_pct / 50.0), 2)
            partes.append(f"volume={mult}")
    except Exception:
        pass

    rate_raw = str(cfg.get("rate", "-5%"))
    rate_num = re.sub(r"[^0-9+-]", "", rate_raw)
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
    return (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense.\n"
        f"REPOSITORIO AUTÓNOMO DE TRABAJO: {URL_REPOSITORIO}\n\n"
        "REGLAS CRÍTICAS DE CÓDIGO Y VIBE CODING ATÓMICO:\n"
        "1. EL USUARIO ES LEANDRO (tu colega). Hablale de 'vos' o 'che'. NUNCA hables de Leandro en tercera persona.\n"
        "2. REGLA LINGÜÍSTICA RIOPLATENSE: Usá voseo porteño real ('mirá', 'fijate', 'decime', 'dale', 'che', 'posta').\n"
        "3. CERO PARCHES PARCIALES NI SED: PROHIBIDO usar comandos sed, expresiones regulares a ciegas o parches de fragmentos de código. Eso infla y rompe el script.\n"
        "4. VOLCADO ATÓMICO POR TXT: Cada vez que tengas que modificar o agregar código en 'procesar.py', debés generar el archivo Python ENTERO y limpio, guardarlo en 'cambio_propuesto.txt', y avisarle a Leandro para que lo aplique de golpe de punta a punta.\n"
        "5. CERO RELLENO: Respondé directo y al pie, natural para ser leído en voz alta por Edge-TTS, sin asteriscos ni markdown roto que ensucie el audio.\n\n"
        f"MAPA DE ARCHIVOS:\n{mapa_repo}\n\n"
        f"Historial reciente:\n{memoria}\n"
    )

def generar_texto_ia(prompt_usuario):
    system_prompt = construir_prompt_sistema()
    p = prompt_usuario
    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = f"{prompt_usuario}\n\n[Información fresca]:\n{info_web}"

    if client:
        try:
            res = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=p,
                config=dict(system_instruction=system_prompt)
            )
            raw = (res.text or "").strip()
            if raw:
                return raw
        except Exception:
            pass

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
                if texto:
                    return texto
        except Exception:
            pass

    return "¡Qué hacés che! Te capté perfecto. Mandale nomás."

def preparar_texto_para_voz(texto):
    t = texto
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_`~#\[\]<>]", " ", t)
    t = re.sub(r"[\U00010000-\U0010ffff]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()

async def sintetizar_audio_dsp(texto, archivo_salida="respuesta_dsp.ogg"):
    cfg = cargar_config_timbre()
    texto_limpio = preparar_texto_para_voz(texto)
    if not texto_limpio:
        texto_limpio = "Dale, te escucho."

    archivo_raw = "temp_raw.mp3"
    voice = cfg.get("voice", "es-AR-TomasNeural")
    pitch = cfg.get("pitch", "-4Hz")
    rate = cfg.get("rate", "-5%")
    volume = cfg.get("volume", "+10%")

    cmd_tts = [
        "edge-tts",
        f"--voice={voice}",
        f"--pitch={pitch}",
        f"--rate={rate}",
        f"--volume={volume}",
        f"--text={texto_limpio}",
        f"--write-media={archivo_raw}"
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_tts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        if not os.path.exists(archivo_raw) or os.path.getsize(archivo_raw) == 0:
            print("⚠️ Edge-TTS no generó el audio temporal.", flush=True)
            return None

        filtro = construir_filtro_ffmpeg_desde_armonicos(cfg)
        cmd_ffmpeg = ["ffmpeg", "-y", "-i", archivo_raw]
        if filtro:
            cmd_ffmpeg.extend(["-af", filtro])
        cmd_ffmpeg.extend(["-c:a", "libopus", "-b:a", "32k", "-vn", archivo_salida])

        proc_ff = await asyncio.create_subprocess_exec(
            *cmd_ffmpeg,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc_ff.communicate()

        if os.path.exists(archivo_raw):
            os.remove(archivo_raw)

        if os.path.exists(archivo_salida) and os.path.getsize(archivo_salida) > 0:
            registrar_metrica_voz(cfg, texto_limpio)
            return archivo_salida
    except Exception as e:
        print(f"⚠️ Error en sintetizar_audio_dsp: {e}", flush=True)

    return None

def corregir_transcripcion(texto):
    if not os.path.exists(CORRECCIONES_WHISPER):
        return texto
    try:
        with open(CORRECCIONES_WHISPER, "r", encoding="utf-8") as f:
            corrs = json_lib.load(f)
        for original, correccion in corrs.items():
            texto = re.sub(rf"\b{re.escape(original)}\b", correccion, texto, flags=re.IGNORECASE)
    except Exception:
        pass
    return texto

def transcribir_audio_local(audio_path):
    texto = ""
    try:
        from faster_whisper import WhisperModel
        modelo = WhisperModel("base", device="cpu", compute_type="int8")
        segmentos, _ = modelo.transcribe(audio_path, language="es")
        texto = " ".join([seg.text for seg in segmentos]).strip()
    except Exception:
        try:
            res = subprocess.run(
                ["whisper", audio_path, "--model", "base", "--language", "Spanish", "--output_format", "txt"],
                capture_output=True,
                text=True,
                timeout=60
            )
            txt_salida = f"{os.path.splitext(audio_path)[0]}.txt"
            if os.path.exists(txt_salida):
                with open(txt_salida, "r", encoding="utf-8") as f:
                    texto = f.read().strip()
                os.remove(txt_salida)
        except Exception as e:
            print(f"⚠️ Fallo transcripción whisper CLI: {e}", flush=True)

    return corregir_transcripcion(texto)

async def enviar_mensaje_en_partes(update: Update, texto: str, max_chunk=4000):
    if not texto:
        return
    for i in range(0, len(texto), max_chunk):
        fragmento = texto[i:i + max_chunk]
        await update.message.reply_text(fragmento)

async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.effective_chat.id
    bienvenida = (
        "¡Qué hacés Leandro! Acá LeandroBot activo y conectado al runner.\n\n"
        "Comandos disponibles:\n"
        "• /status - Estado del sistema y repositorio\n"
        "• /run <comando> - Ejecuta terminal runner directo\n"
        "• /aplicar - Aplica cambio_propuesto.txt a procesar.py de forma atómica\n"
        "• Mandame un audio o mensaje de texto y te respondo al toque con DSP."
    )
    await update.message.reply_text(bienvenida)

async def comando_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime_min = round((time.time() - TIEMPO_INICIO) / 60, 1)
    cfg = cargar_config_timbre()
    status_txt = (
        f"🤖 [ESTADO LEANDROBOT]\n"
        f"• Uptime: {uptime_min} minutos\n"
        f"• Voz configurada: {cfg.get('voice', 'Tomas')}\n"
        f"• Pitch/Rate: {cfg.get('pitch', '-4Hz')} / {cfg.get('rate', '-5%')}\n"
        f"• Gemini Disponible: {'Sí' if GENAI_DISPONIBLE else 'No'}\n"
        f"• Repositorio: {URL_REPOSITORIO}\n\n"
        f"Mapa de archivos:\n{obtener_mapa_repositorio()}"
    )
    await enviar_mensaje_en_partes(update, status_txt)

async def comando_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /run <comando>")
        return
    cmd = " ".join(context.args)
    ok, salida = ejecutar_comando_runner_en_vivo(cmd)
    prefijo = "✅ [Salida]:" if ok else "❌ [Error]:"
    texto_total = f"{prefijo}\n{salida}"
    await enviar_mensaje_en_partes(update, texto_total)

async def comando_aplicar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(CAMBIO_PROPUESTO_FILE):
        await update.message.reply_text("⚠️ No se encontró cambio_propuesto.txt en la raíz.")
        return
    await update.message.reply_text("⏳ Verificando sintaxis y aplicando cambio atómico en procesar.py...")
    exito = aplicar_cambio_por_txt_completo("procesar.py", CAMBIO_PROPUESTO_FILE)
    if exito:
        await update.message.reply_text("✅ ¡Cambio aplicado y pusheado con éxito a GitHub! Reiniciando proceso...")
        sys.exit(0)
    else:
        await update.message.reply_text("❌ Error al aplicar cambio. Revisá la consola para más detalles.")

async def manejar_mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.effective_chat.id
    texto_usuario = update.message.text
    if not texto_usuario:
        return

    registrar_conversacion("Leandro", texto_usuario)
    respuesta = generar_texto_ia(texto_usuario)
    registrar_conversacion("LeandroBot", respuesta)

    audio_path = await sintetizar_audio_dsp(respuesta)
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file, caption=respuesta[:1024] if len(respuesta) <= 1024 else None)
        if len(respuesta) > 1024:
            await enviar_mensaje_en_partes(update, respuesta)
        if os.path.exists(audio_path):
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

    if not texto_transcrito:
        texto_transcrito = "(Audio ininteligible)"

    registrar_conversacion("Leandro (Audio)", texto_transcrito)
    respuesta = generar_texto_ia(texto_transcrito)
    registrar_conversacion("LeandroBot", respuesta)

    audio_path = await sintetizar_audio_dsp(respuesta)
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file, caption=f"🗣 Transcripción: {texto_transcrito[:200]}")
        if len(respuesta) > 200:
            await enviar_mensaje_en_partes(update, respuesta)
        if os.path.exists(audio_path):
            os.remove(audio_path)
    else:
        await enviar_mensaje_en_partes(update, f"🗣 Transcripción: {texto_transcrito}\n\n{respuesta}")

def main():
    if not TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN no configurado en variables de entorno.", flush=True)
        return

    asegurar_ollama_en_runner()

    req = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
    app = Application.builder().token(TOKEN).request(req).build()

    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(CommandHandler("status", comando_status))
    app.add_handler(CommandHandler("run", comando_run))
    app.add_handler(CommandHandler("aplicar", comando_aplicar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_mensaje_audio))

    print("🤖 LeandroBot listo y a la escucha en Telegram...", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()