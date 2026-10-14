# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot con Filtro Inteligente de Tareas, Whisper y Fallback

import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
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

print("🚀 [INIT]: Inicializando LeandroBot con Filtro de Tareas Inteligente...", flush=True)

TXT_FILE = "conversaciones.txt"
FILE_TAREAS = "memoria_tareas.json"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
CARPETA_MUESTRAS = "muestras_voz"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

for f_path, default_val in [
    (TXT_FILE, ""),
    (FILE_TAREAS, []),
    (DATASET_ENTRENAMIENTO, []),
    (CONFIG_TIMBRE, {
        "voice": "es-AR-TomasNeural",
        "pitch": "-4Hz",
        "rate": "-5%",
        "volume": "+10%",
        "descripcion": "Locutor nocturno porteño con barítono cálido, pausado y presencia de radio"
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

def asegurar_e_iniciar_ollama():
    print("🦙 [OLLAMA]: Verificando estado del servicio local...", flush=True)
    for _ in range(3):
        try:
            res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2)
            if res.status_code == 200:
                print("🦙 [OLLAMA]: ¡Servicio activo y listo en el puerto 11434!", flush=True)
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
                    print(f"🦙 [OLLAMA]: Demonio levantado con éxito en el segundo {i+1}.", flush=True)
                    break
            except Exception:
                continue
                
        print(f"🦙 [OLLAMA]: Verificando si el modelo '{OLLAMA_MODEL}' está disponible...", flush=True)
        subprocess.run(["ollama", "pull", OLLAMA_MODEL], check=False)
        print(f"🦙 [OLLAMA]: Modelo '{OLLAMA_MODEL}' listo para usar.", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ [OLLAMA ERROR INICIANDO]: {e}", flush=True)
        return False

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            return json_lib.load(f)
    except Exception:
        return {
            "voice": "es-AR-TomasNeural",
            "pitch": "-4Hz",
            "rate": "-5%",
            "volume": "+10%",
            "descripcion": "Locutor porteño cálido"
        }

def guardar_config_timbre(cfg):
    try:
        with open(CONFIG_TIMBRE, "w", encoding="utf-8") as f:
            json_lib.dump(cfg, f, indent=4, ensure_ascii=False)
        print(f"🎙️ [TIMBRE GUARDADO]: {cfg}", flush=True)
    except Exception as e:
        print(f"⚠️ Error guardando timbre: {e}", flush=True)

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}" + chr(10))
    except Exception as e:
        print(f"⚠️ Error escribiendo en {TXT_FILE}: {e}", flush=True)

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
        "código", "script", "bot", "función", "archivo", "tarea", "directiva"
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
        tareas = tareas[-80:]
        with open(FILE_TAREAS, "w", encoding="utf-8") as f:
            json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
        print(f"📋 [MEMORIA TAREAS]: Pedido guardado -> {texto_tarea[:40]}...", flush=True)
    except Exception as e:
        print(f"⚠️ Error guardando en memoria_tareas.json: {e}", flush=True)

def obtener_memoria_aprendizaje():
    historial_txt = ""
    if os.path.exists(TXT_FILE):
        try:
            with open(TXT_FILE, "r", encoding="utf-8") as f:
                lineas = f.readlines()
            historial_txt = "".join(lineas[-20:])
        except Exception:
            pass

    tareas = cargar_tareas_memoria()
    texto_tareas = "\n".join([
        f"- [{t.get('timestamp', 'Reciente')}] {t.get('tarea', str(t))} ({t.get('estado', 'pendiente')})" 
        for t in tareas[-15:] if isinstance(t, dict)
    ])

    return f"--- TAREAS Y DIRECTIVAS GUARDADAS (memoria_tareas.json) ---\n{texto_tareas if texto_tareas else '[Sin tareas]'}\n\n--- HISTORIAL RECIENTE ---\n{historial_txt}"

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

def parsear_timbre_con_lenguaje_natural(descripcion_natural):
    prompt_ia = (
        f"Sos un director de sonido y acústica. El usuario quiere calibrar el timbre de voz con esta descripción: '{descripcion_natural}'.\n"
        "Configurá los parámetros exactos de Edge-TTS:\n"
        "- voice: 'es-AR-TomasNeural' (hombre porteño) o 'es-AR-ElenaNeural' (mujer porteña) o 'es-UY-MateoNeural' (uruguayo)\n"
        "- pitch: entre -12Hz (muy grave/ronco) y +10Hz (agudo/joven). Ejemplo: '-6Hz', '-2Hz', '+4Hz'\n"
        "- rate: entre -20% (muy pausado/nocturno) y +20% (muy rápido). Ejemplo: '-8%', '-3%', '+5%'\n"
        "- volume: entre -15% y +15%. Ejemplo: '+10%'\n\n"
        "Respondé ÚNICAMENTE con este JSON válido (sin código markdown):\n"
        "{\n"
        '  "voice": "es-AR-TomasNeural",\n'
        '  "pitch": "-6Hz",\n'
        '  "rate": "-6%",\n'
        '  "volume": "+10%",\n'
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

    b_pitch = "-6Hz" if any(w in descripcion_natural.lower() for w in ["grave", "ronco", "nocturno", "pesado", "maduro"]) else "-2Hz"
    b_rate = "-8%" if any(w in descripcion_natural.lower() for w in ["lento", "pausado", "tranquilo", "calmo"]) else "+5%" if "rápido" in descripcion_natural.lower() else "-3%"
    return {
        "voice": "es-AR-TomasNeural",
        "pitch": b_pitch,
        "rate": b_rate,
        "volume": "+10%",
        "descripcion": descripcion_natural
    }

def construir_prompt_sistema():
    timbre = cargar_config_timbre()
    memoria = obtener_memoria_aprendizaje()

    return (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense.\n"
        "INSTRUCCIONES CLAVE:\n"
        "1. NO SOS UN ROBOT: Adaptá tu estilo aprendiendo de la conversación del usuario y consultando memoria_tareas.json.\n"
        "2. REGLA LINGÜÍSTICA RIOPLATENSE: Hablá con voseo porteño real, yeísmo rehilado, e imperativos agudos acentuados: "
        "'mirá', 'vení', 'decime', 'escuchá', 'pasame', 'hacé', 'fijate', 'poné', 'dale', 'posta', 'che'.\n"
        "3. RITMO Y CADENCIA ORAL: Escribí usando comas y puntos suspensivos para dar respiración y ritmo natural al leerse en voz alta.\n"
        "4. VIBE CODING: Si te piden programar, corregir, modificar o crear código de cualquier tipo, respondé con código limpio, "
        "bien explicado y listo para usar en producción.\n"
        "5. SIN SPAM: Respondé únicamente a lo que te pide el usuario, sin relleno innecesario.\n\n"
        f"Timbre de voz activo solicitado: '{timbre.get('descripcion', 'Natural')}'\n\n"
        f"{memoria}\n"
    )

def generar_texto_ia(prompt_usuario):
    system_prompt = construir_prompt_sistema()
    p = prompt_usuario

    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio", "resultado", "googlea"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = prompt_usuario + chr(10) + chr(10) + "[Información fresca de internet]:" + chr(10) + info_web

    if client:
        try:
            print("🤖 [GEMINI]: Consultando nube...", flush=True)
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=p,
                config=dict(system_instruction=system_prompt)
            )
            raw = (res.text or "").strip()
            if raw:
                print("✅ [GEMINI OK]: Respuesta obtenida.", flush=True)
                return raw
        except Exception as e:
            print(f"⚠️ [GEMINI FALLÓ]: {e}. Activando fallback a Ollama...", flush=True)

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
                "options": {
                    "num_ctx": 1024,
                    "num_predict": 200,
                    "temperature": 0.7
                },
                "stream": False
            },
            timeout=35
        )
        if r.status_code == 200:
            texto = r.json().get("message", {}).get("content", "").strip()
            if texto:
                print("✅ [OLLAMA OK]: Respuesta local generada con éxito.", flush=True)
                return texto
    except Exception as e_ollama:
        print(f"⚠️ [OLLAMA FALLÓ]: {e_ollama}. Activando respuesta de emergencia...", flush=True)

    return "Che, se me plancharon los motores de IA por un segundo. Decime de nuevo cómo lo seguimos."

def preparar_texto_para_voz(texto):
    t = re.sub(r'```[\s\S]*?```', 'Te pasé el bloque de código por texto para que lo mires tranqui.', texto)
    t = t.replace("*", "").replace("_", "").replace(chr(96), "").replace("#", "").strip()
    t = re.sub(r'\b(che|mirá|fijate|escuchá|vení|posta)\b', r'\g<1>...', t, flags=re.IGNORECASE)
    palabras = t.split()
    if len(palabras) > 60:
        t = " ".join(palabras[:55]) + "... te lo resumo hasta acá y cualquier cosa me avisás, che."
    return t.strip()

async def sintetizar_voz_edge_tts(texto, ogg_salida="resp.ogg"):
    cfg = cargar_config_timbre()
    voice = cfg.get("voice", "es-AR-TomasNeural")
    pitch = cfg.get("pitch", "-4Hz")
    rate = cfg.get("rate", "-5%")
    volume = cfg.get("volume", "+10%")

    texto_oral = preparar_texto_para_voz(texto)
    if not texto_oral:
        texto_oral = "Sintonizamos en un toque, che."

    try:
        import edge_tts
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
        await update.message.reply_text(
            "¡Qué hacés che! Acá Leandro. Listo para charlar, hacer vibe coding o tirar código.\n\n"
            "Comandos:\n"
            "• /timbre <descripción>\n"
            "• /codigo <tarea>\n"
            "• /ollama <texto>\n"
            "• O hablame por texto o nota de voz."
        )

async def cambiar_timbre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    desc = " ".join(context.args).strip() if context.args else ""
    if not desc:
        cfg = cargar_config_timbre()
        await update.message.reply_text(f"🎙️ Timbre actual: '{cfg.get('descripcion', 'Estándar')}'")
        return

    await update.message.reply_text(f"🔧 Calibrando timbre a: '{desc}'...")
    nuevo_timbre = parsear_timbre_con_lenguaje_natural(desc)
    guardar_config_timbre(nuevo_timbre)
    await update.message.reply_text(f"✅ Timbre configurado correctamente.")

async def manejar_vibe_coding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    instruccion = " ".join(context.args).strip() if context.args else ""
    if not instruccion:
        await update.message.reply_text("Decime qué querés programar o modificar, che.")
        return

    guardar_tarea_memoria(f"Vibe Coding: {instruccion}")
    await update.message.reply_text(f"💻 Procesando vibe coding: '{instruccion}'...")
    resp_codigo = generar_texto_ia(f"VIBE CODING: {instruccion}. Generá la solución de código completa y limpia.")
    await update.message.reply_text(resp_codigo)

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text or update.message.caption or "[Texto recibido]"
    
    print(f"📥 [MENSAJE TEXTO]: '{u_text}'", flush=True)

    # Filtrar y guardar solo si es pedido/tarea
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
                await update.message.reply_voice(voice=vf, caption="📻 Leandro")
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
        print("🎙️ [AUDIO RECIBIDO]: Procesando nota de voz...", flush=True)

        if not WHISPER_DISPONIBLE:
            await update.message.reply_text("Che, recibí tu audio pero Whisper no está disponible en este entorno.")
            return

        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        path_in = os.path.join(CARPETA_MUESTRAS, f"audio_{update.message.message_id}.ogg")
        await file.download_to_drive(path_in)

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip() or "Che, te mandé un audio."

        print(f"✍️ [WHISPER TRANSCRIPCIÓN]: '{texto_crudo}'", flush=True)

        # Filtrar y guardar en memoria si es pedido
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
                    await update.message.reply_voice(voice=vf, caption="📻 Leandro")
            except Exception as ex_send:
                print(f"⚠️ Error enviando audio de respuesta: {ex_send}", flush=True)
            try: os.remove(archivo_audio)
            except Exception: pass

        if os.path.exists(path_in):
            try: os.remove(path_in)
            except Exception: pass

async def test_ollama_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    query = " ".join(context.args).strip() if context.args else "Che Leandro, ¿cómo anda Ollama?"
    await update.message.reply_text(f"🦙 Consultando Ollama ({OLLAMA_MODEL})...")
    
    try:
        r = requests.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": query}], "stream": False},
            timeout=25
        )
        if r.status_code == 200:
            texto = r.json().get("message", {}).get("content", "").strip()
            if texto:
                await update.message.reply_text(f"🦙 [OLLAMA RESPUESTA]:\n\n{texto}")
                return
    except Exception as e:
        print(f"Error ollama cmd: {e}", flush=True)
    await update.message.reply_text(f"⚠️ No se pudo conectar a Ollama local.")

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta la variable TELEGRAM_BOT_TOKEN.", flush=True)
        return

    print("🦙 [INIT]: Asegurando Ollama antes de levantar Telegram...", flush=True)
    asegurar_e_iniciar_ollama()

    print("🚀 [INIT]: Configurando LeandroBot con Filtro Inteligente de Tareas...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    try:
        app = Application.builder().token(TOKEN).request(request_config).build()
        
        async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            print(f"❌ [TELEGRAM ERROR CRÍTICO]: {context.error}", flush=True)
            traceback.print_exc()

        app.add_error_handler(error_handler)

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("timbre", cambiar_timbre))
        app.add_handler(CommandHandler("codigo", manejar_vibe_coding))
        app.add_handler(CommandHandler("vibe", manejar_vibe_coding))
        app.add_handler(CommandHandler("ollama", test_ollama_cmd))
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_voz))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

        print("✅ [BOT OK]: Entrando en bucle de polling...", flush=True)
        app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        print(f"❌ [ERROR FATAL EN MAIN]: {e}", flush=True)
        traceback.print_exc()

if __name__ == "__main__":
    main()
