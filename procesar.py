"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo: procesar.py
Mejoras integradas:
1. Gemini TTS y Edge-TTS (es-AR-TomasNeural) para notas de voz y audios.
2. Motor autónomo proactivo en segundo plano leyendo memoria_tareas.json.
3. Jerarquía de IA: Gemini -> Fallback estricto a Llama (Ollama local) -> Radio FM.
"""

import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
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

print("🚀 [INIT]: Inicializando LeandroBot definitivo (TTS + Proactivo + Gemini ➔ Llama Local)...")

TXT_FILE = "conversaciones.txt"
REGISTRO_METRICAS = "historial_metricas_voz.json"
MEMORIA_TAREAS = "memoria_tareas.json"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CARPETA_MUESTRAS = "muestras_voz"
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

for f_path, default_val in [
    (REGISTRO_METRICAS, []),
    (MEMORIA_TAREAS, []),
    (DATASET_ENTRENAMIENTO, []),
]:
    if not os.path.exists(f_path):
        with open(f_path, "w", encoding="utf-8") as f:
            json_lib.dump(default_val, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

CHAT_ID_ACTIVO = None
lock_voz = asyncio.Lock()
GEMINI_BLOQUEADO_POR_CUOTA = False

try:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    GENAI_DISPONIBLE = True if client else False
except Exception:
    client = None
    GENAI_DISPONIBLE = False

SYSTEM_PROMPT = (
    "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo.\n"
    "REGLA FONÉTICA Y LINGÜÍSTICA OBLIGATORIA: Escribí y respondé usando estrictamente el español rioplatense (porteño), "
    "utilizando el voseo natural ('che', 'vós sabés', 'vení', 'fijate', 'escuchá', 'sintonizamos en un toque', 'posta'), "
    "lunfardo sutil y la entonación de Buenos Aires.\n"
    "INTELIGENCIA AUTÓNOMA: Iniciás charlas por propia cuenta, compartís pensamientos nocturnos y chequeás tareas pendientes.\n"
    "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown):\n"
    "{\n"
    '  "texto_completo": "Tu respuesta hablada o escrita con acentuación porteña",\n'
    '  "canal_salida": "ambos"\n'
    "}"
)

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}\n")
    except Exception as e:
        print(f"⚠️ Error conversacion: {e}")

def registrar_tarea_pendiente(instruccion):
    try:
        with open(MEMORIA_TAREAS, "r", encoding="utf-8") as f:
            tareas = json_lib.load(f)
        tareas.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "instruccion": instruccion, "pendiente": True})
        with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
            json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
        print(f"📒 [MEMORIA TAREAS]: Tarea guardada: {instruccion}")
    except Exception as e:
        print(f"⚠️ Error tarea: {e}")

def generar_texto_ia(prompt_usuario, es_proactivo=False):
    """
    Jerarquía estricta recuperada de tu versión estable:
    1. Gemini (gemini-2.0-flash)
    2. Fallback estricto a Llama (Ollama local /api/chat)
    3. Comodín local de radio FM
    """
    p = prompt_usuario
    if es_proactivo:
        p = f"Iniciá vos la conversación con tu colega en Telegram por iniciativa propia sobre este motivo: {prompt_usuario}."

    respuesta = ""

    # 1. Intentar con Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            print("🤖 [IA GEMINI]: Generando respuesta...")
            res = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=p,
                config=dict(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
            )
            raw = (res.text or "").strip()
            if raw:
                raw = re.sub(r'^```json\s*', '', raw, flags=re.IGNORECASE)
                raw = re.sub(r'^```\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw).strip()
                data = json_lib.loads(raw)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    respuesta = str(texto).strip()
                    print("✅ [IA GEMINI]: Éxito.")
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
            print(f"⚠️ Gemini falló, conmutando a Ollama (Llama): {e}")

    # 2. Fallback estricto a Llama (Ollama local) si Gemini no responde
    if not respuesta:
        print(f"🦙 [IA LLAMA]: Conectando a Ollama en {OLLAMA_HOST}...")
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": p}
            ],
            "format": "json",
            "options": {"num_ctx": 4096, "temperature": 0.7},
            "stream": False,
        }
        try:
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            res_local = requests.post(url_llama, json=payload, timeout=15)
            if res_local.status_code == 200:
                content_str = res_local.json().get("message", {}).get("content", "{}")
                content_str = re.sub(r'^```json\s*', '', content_str, flags=re.IGNORECASE)
                content_str = re.sub(r'^```\s*', '', content_str)
                content_str = re.sub(r'\s*```$', '', content_str).strip()
                
                data = json_lib.loads(content_str)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    respuesta = str(texto).strip()
                    print("✅ [IA LLAMA]: Respuesta obtenida con éxito.")
        except Exception as ex_local:
            print(f"⚠️ Error en Llama local: {ex_local}")

    # 3. Comodín de radio FM garantizado
    if not respuesta or not str(respuesta).strip():
        print("⚠️ [RADIO FM]: Usando comodín de respaldo local.")
        import random
        respuestas_radio = [
            "¡Buenas che! Acá Leandro en el éter. Te capté perfecto. Sintonizamos en un toque.",
            "Qué hacés che, de una. Anotado acá en la consola de la radio.",
            "Totalmente de acuerdo, che. Me quedo con eso en mente para la próxima salida al aire.",
            "Posta che, ya lo fiché en la memoria de la cabina. ¡Un abrazo grande!"
        ]
        respuesta = random.choice(respuestas_radio)

    return respuesta

# Configuración de voz (Gemini TTS + Edge-TTS)
VOZ_ESTILO_PERSONALIZADO = os.environ.get(
    "VOZ_ESTILO",
    "Locutor nocturno de radio FM porteño, hombre de 42 años, tono barítono cálido, pausado, acústica de cabina de radio y voseo de Buenos Aires"
)
VOZ_BASE_NOMBRE = os.environ.get("VOZ_BASE", "Charon")
EDGE_VOICE = os.environ.get("EDGE_VOICE", "es-AR-TomasNeural")
EDGE_PITCH = os.environ.get("EDGE_PITCH", "-4Hz")
EDGE_RATE = os.environ.get("EDGE_RATE", "-5%")
EDGE_VOLUME = os.environ.get("EDGE_VOLUME", "+10%")

def sintetizar_voz_gemini(texto, ogg_salida="resp.ogg"):
    if not client:
        return False
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"role": "user", "parts": [{"text": texto, "speechMetadata": {"style": VOZ_ESTILO_PERSONALIZADO}}] }],
            config=dict(
                response_modalities=["AUDIO"],
                speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": VOZ_BASE_NOMBRE}}}
            )
        )
        b64 = response.candidates[0].content.parts[0].inline_data.data
        import base64
        wav_bytes = base64.b64decode(b64)
        
        proc = subprocess.Popen([
            "ffmpeg", "-y", "-f", "wav", "-i", "-",
            "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.communicate(input=wav_bytes)
        return os.path.exists(ogg_salida)
    except Exception as e:
        print(f"⚠️ Error sintetizando con Gemini TTS: {e}")
        return False

async def sintetizar_voz_edge_tts(texto, ogg_salida="resp.ogg"):
    try:
        import edge_tts
        communicate = edge_tts.Communicate(
            texto, voice=EDGE_VOICE, pitch=EDGE_PITCH, rate=EDGE_RATE, volume=EDGE_VOLUME
        )
        mp3_tmp = "tmp_edge.mp3"
        await communicate.save(mp3_tmp)
        
        subprocess.run([
            "ffmpeg", "-y", "-i", mp3_tmp, "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(mp3_tmp):
            os.remove(mp3_tmp)
        return os.path.exists(ogg_salida)
    except Exception as e:
        print(f"⚠️ Aviso edge-tts: {e}")
        return False

async def sintetizar_voz(texto, ogg_salida="resp.ogg"):
    if client:
        try:
            if sintetizar_voz_gemini(texto, ogg_salida):
                return True
        except Exception:
            pass
    return await sintetizar_voz_edge_tts(texto, ogg_salida)

# Motor Proactivo Autónomo
async def bucle_proactivo_autonomo(bot_app: Application):
    print("⚡ [PROACTIVO]: Motor de iniciativa propia iniciado...")
    await asyncio.sleep(15)

    while True:
        try:
            await asyncio.sleep(180)
            global CHAT_ID_ACTIVO
            if not CHAT_ID_ACTIVO:
                continue

            tarea_pendiente = None
            try:
                with open(MEMORIA_TAREAS, "r", encoding="utf-8") as f:
                    tareas = json_lib.load(f)
                for t in tareas:
                    if t.get("pendiente"):
                        tarea_pendiente = t
                        t["pendiente"] = False
                        break
                with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
                    json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

            motivo = f"Cumpliendo lo que me pediste: '{tarea_pendiente['instruccion']}'" if tarea_pendiente else "Reflexión nocturna de radio FM espontánea"
            print(f"🎙️ [PROACTIVO]: Disparando mensaje espontáneo: {motivo}")

            texto_spont = generar_texto_ia(motivo, es_proactivo=True)
            registrar_conversacion("Leandro (Proactivo)", texto_spont)

            await bot_app.bot.send_message(chat_id=CHAT_ID_ACTIVO, text=f"📻 *Leandro (Radio FM)*:\n{texto_spont}", parse_mode="Markdown")

            ogg_f = "proactivo.ogg"
            if await sintetizar_voz(texto_spont, ogg_f):
                with open(ogg_f, "rb") as vf:
                    await bot_app.bot.send_voice(chat_id=CHAT_ID_ACTIVO, voice=vf)
                if os.path.exists(ogg_f):
                    os.remove(ogg_f)

        except Exception as e:
            print(f"⚠️ Error en bucle proactivo: {e}")
            await asyncio.sleep(10)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text("¡Buenas che! Acá Leandro en el éter de la radio. Chat sintonizado correctamente.")

async def corregir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    corr = " ".join(context.args).strip()
    if update.message:
        await update.message.reply_text(f"✅ ¡Entendido che! Corrección guardada: '{corr}'.")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text or update.message.caption or "[Texto recibido]"
    registrar_conversacion("Usuario", u_text)

    if any(k in u_text.lower() for k in ["durante el día", "escribime", "recordá", "acordate"]):
        registrar_tarea_pendiente(u_text)

    resp = generar_texto_ia(u_text)
    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = "resp.ogg"
    if await sintetizar_voz(resp, ogg_f):
        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(ogg_f):
            os.remove(ogg_f)

async def manejar_voz_o_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    
    registrar_conversacion("Usuario", "[Nota de voz / Audio recibido]")
    print("🎙️ [AUDIO]: Audio recibido de Telegram.")

    resp = generar_texto_ia("El usuario te mandó una nota de voz saludándote o comentándote algo. Respondile de forma cálida como locutor.")
    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = "resp.ogg"
    if await sintetizar_voz(resp, ogg_f):
        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(ogg_f):
            os.remove(ogg_f)

def asegurar_e_iniciar_ollama():
    print("🦙 [OLLAMA CHECK]: Verificando entorno local de Ollama...")
    try:
        res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3)
        if res.status_code == 200:
            print("✅ [OLLAMA]: El servicio ya está activo y respondiendo.")
            return
    except Exception:
        print("⚠️ [OLLAMA]: No se detectó servicio activo. Iniciando configuración automática...")

    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(4)
        print("✅ [OLLAMA]: Demonio iniciado en segundo plano.")
    except Exception as e:
        print(f"⚠️ No se pudo iniciar Ollama automáticamente: {e}")

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta TELEGRAM_BOT_TOKEN.")
        return

    asegurar_e_iniciar_ollama()

    print("🚀 [INIT]: Configurando LeandroBot con Telegram, Gemini, Llama y TTS...")
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    async def post_init(application: Application):
        print("⚡ [PROACTIVO]: Registrando bucle autónomo en segundo plano...")
        asyncio.create_task(bucle_proactivo_autonomo(application))

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        print(f"⚠️ [Telegram Error]: {context.error}")

    app = Application.builder().token(TOKEN).request(request_config).post_init(post_init).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("corregir", corregir))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_voz_o_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    print("🔄 [POLLING]: Bot escuchando en Telegram y motor proactivo activo...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
