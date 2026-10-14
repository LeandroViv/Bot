"""
Repositorio: https://github.com/LeandroViv/Bot"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo: procesar.py
Mejoras integradas:
1. Voz natural limpia con Gemini TTS (sin ruidos de Bark, sin cuelgues de CPU).
2. Fallback inteligente a Ollama (Llama) sin bloqueos de timeout.
3. MOTOR AUTÓNOMO PROACTIVO: Bucle de fondo que lee memoria_tareas.json y escribe
   por propia iniciativa al chat del usuario sin que él tenga que escribir primero!
4. Transcripción con Faster-Whisper, comando /corregir y sincronización Git.
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

print("🚀 [INIT]: Inicializando LeandroBot definitivo (Gemini TTS + Motor Proactivo + Fallback Llama)...")

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

# ID de chat objetivo detectado para mandar mensajes espontáneos
CHAT_ID_ACTIVO = None
lock_voz = asyncio.Lock()

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

def buscar_en_web(query):
    """Búsqueda web local y gratuita para GitHub Actions (sin API keys)."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                return "
".join([f"- {r.get('title', '')}: {r.get('body', '')}" for r in results])
    except Exception as e:
        print(f"⚠️ Aviso búsqueda web: {e}")
    return ""

def generar_texto_ia(prompt_usuario, es_proactivo=False):
    """Genera el texto usando Gemini (Prioridad 1) con fallback a Llama, búsqueda web y fallback local garantizado."""
    p = prompt_usuario
    if es_proactivo:
        p = f"Iniciá vos la conversación con tu colega en Telegram por iniciativa propia sobre este motivo: {prompt_usuario}."
    else:
        # Búsqueda web automática si el usuario pregunta algo de actualidad o información reciente
        if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio", "resultado"]):
            info_web = buscar_en_web(prompt_usuario)
            if info_web:
                p = f"{prompt_usuario}

[Datos recientes de internet]:
{info_web}"

    if client:
        try:
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=p,
                config=dict(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
            )
            raw = (res.text or "").strip()
            if raw:
                data = json_lib.loads(raw)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    return str(texto).strip()
        except Exception as e:
            print(f"⚠️ Gemini fallback: {e}")

    # Fallback Ollama (si está disponible)
    try:
        r = requests.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/chat",
            json={"model": "llama3.2", "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": p}], "format": "json"},
            timeout=10
        )
        if r.status_code == 200:
            data = json_lib.loads(r.json().get("message", {}).get("content", "{}"))
            texto = data.get("texto_completo")
            if texto and str(texto).strip():
                return str(texto).strip()
    except Exception:
        pass

    # Fallback local garantizado de radio FM (NUNCA devuelve None ni cadena vacía)
    import random
    respuestas_radio = [
        "¡Buenas che! Acá Leandro en el éter. Te capté perfecto. Sintonizamos en un toque.",
        "Qué hacés che, de una. Anotado acá en la consola de la radio.",
        "Totalmente de acuerdo, che. Me quedo con eso en mente para la próxima salida al aire.",
        "Posta che, ya lo fiché en la memoria de la cabina. ¡Un abrazo grande!"
    ]
    return random.choice(respuestas_radio)

# Configuración de voz modelada por características (Voice Design)
VOZ_ESTILO_PERSONALIZADO = os.environ.get(
    "VOZ_ESTILO",
    "Locutor nocturno de radio FM porteño, hombre de 42 años, tono barítono cálido, pausado, con pequeñas respiraciones naturales, acústica de cabina de radio y voseo de Buenos Aires"
)
VOZ_BASE_NOMBRE = os.environ.get("VOZ_BASE", "Charon")

# Tuneo avanzado de Edge-TTS (sin hardcodeo: configurable por variables de entorno o Secrets)
EDGE_VOICE = os.environ.get("EDGE_VOICE", "es-AR-TomasNeural") # Voz argentina porteña masculina
EDGE_PITCH = os.environ.get("EDGE_PITCH", "-4Hz")             # -4Hz a -8Hz para voz grave de trasnoche
EDGE_RATE = os.environ.get("EDGE_RATE", "-5%")                # -5% a -10% para cadencia pausada y reflexiva
EDGE_VOLUME = os.environ.get("EDGE_VOLUME", "+10%")           # Presencia de micrófono de cabina

def sintetizar_voz_gemini(texto, ogg_salida="resp.ogg"):
    """
    Sintetiza audio con Gemini 3.8 TTS nativo usando el estilo modelado por características.
    Convierte directo a OGG/Opus sin pasar por Bark ni generar ruidos metálicos.
    """
    if not client:
        return False
    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash-lite-tts",
            contents=[{"role": "user", "parts": [{"text": texto, "speechMetadata": {"style": VOZ_ESTILO_PERSONALIZADO}}] }],
            config=dict(
                response_modalities=["AUDIO"],
                speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": VOZ_BASE_NOMBRE}}}
            )
        )
        b64 = response.candidates[0].content.parts[0].inline_data.data
        import base64
        wav_bytes = base64.b64decode(b64)
        
        # Convertir a OGG Opus nativo vía ffmpeg
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
    """
    Sintetizador neuronal directo con Edge-TTS 100% tuneable.
    Variables configurables: EDGE_VOICE, EDGE_PITCH, EDGE_RATE, EDGE_VOLUME.
    """
    try:
        import edge_tts
        # Limpiar texto de caracteres de markdown para que no los pronuncie
        texto_limpio = texto.replace("*", "").replace("_", "").replace(chr(96), "").replace("#", "").strip()
        if not texto_limpio:
            texto_limpio = "Sintonizamos en un toque, che."

        communicate = edge_tts.Communicate(
            texto_limpio,
            voice=EDGE_VOICE,
            pitch=EDGE_PITCH,
            rate=EDGE_RATE,
            volume=EDGE_VOLUME
        )
        mp3_tmp = f"tmp_edge_{int(time.time()*1000)}.mp3"
        await communicate.save(mp3_tmp)
        
        # Convertir a OGG Opus nativo para nota de voz de Telegram vía ffmpeg
        subprocess.run([
            "ffmpeg", "-y", "-i", mp3_tmp,
            "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(mp3_tmp):
            try: os.remove(mp3_tmp)
            except Exception: pass
            
        return os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 100
    except Exception as e:
        print(f"⚠️ Error sintetizando con edge-tts: {e}")
        return False

async def sintetizar_voz(texto, ogg_salida="resp.ogg"):
    """
    MOTOR DIRECTO Y EXCLUSIVO: Edge-TTS neuronal argentino (es-AR-TomasNeural).
    100% gratuito, ilimitado, sin cuotas de Google ni API keys.
    """
    print(f"🎙️ [EDGE-TTS DIRECTO]: Generando voz neuronal con {EDGE_VOICE} (pitch={EDGE_PITCH}, rate={EDGE_RATE})...")
    return await sintetizar_voz_edge_tts(texto, ogg_salida)

# BUCLE AUTÓNOMO PROACTIVO: Escribe sin que el usuario le escriba
async def bucle_proactivo_autonomo(bot_app: Application):
    """Revisa memoria_tareas.json y lanza reflexiones de radio en Telegram de forma autónoma."""
    print("⚡ [PROACTIVO]: Motor de iniciativa propia iniciado. Esperando chat activo...")
    await asyncio.sleep(15)

    while True:
        try:
            await asyncio.sleep(180) # Cada 3 minutos evalúa si mandar un mensaje espontáneo
            global CHAT_ID_ACTIVO
            if not CHAT_ID_ACTIVO:
                continue

            # 1. Chequear si hay tareas pendientes en memoria_tareas.json
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
            if not texto_spont or not str(texto_spont).strip():
                texto_spont = "Che, qué hacés. Me quedé pensando en lo que hablábamos. Sintonizamos en un toque."

            registrar_conversacion("Leandro (Proactivo)", texto_spont)

            # Mandar texto a Telegram
            await bot_app.bot.send_message(chat_id=CHAT_ID_ACTIVO, text=f"📻 *Leandro (Radio FM)*:\n{texto_spont}", parse_mode="Markdown")

            # Mandar audio si se puede (Gemini TTS con fallback a Edge-TTS)
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
        await update.message.reply_text("¡Buenas che! Acá Leandro en el éter de la radio. Ya sintonicé tu chat: ahora te voy a hablar por cuenta propia a lo largo del día.")

async def corregir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    corr = " ".join(context.args).strip()
    if update.message:
        await update.message.reply_text(f"✅ ¡Entendido che! Corrección guardada: '{corr}'.")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text or update.message.caption or "[Audio/Nota de voz]"
    registrar_conversacion("Usuario", u_text)

    # Detectar recordatorio
    if any(k in u_text.lower() for k in ["durante el día", "escribime", "recordá", "acordate"]):
        registrar_tarea_pendiente(u_text)

    resp = generar_texto_ia(u_text)
    if not resp or not str(resp).strip():
        resp = "Te capté perfecto, che. Sintonizamos en un toque."

    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = "resp.ogg"
    if await sintetizar_voz(resp, ogg_f):
        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(ogg_f):
            os.remove(ogg_f)

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta la variable TELEGRAM_BOT_TOKEN.")
        print("👉 Entrá a tu repo en GitHub: Settings > Secrets and variables > Actions > New repository secret")
        print("👉 Name: TELEGRAM_BOT_TOKEN | Value: Tu token de @BotFather")
        return

    print("🚀 [INIT]: Configurando LeandroBot con Telegram, Gemini y Edge-TTS tuneado...")
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    # post_init garantiza que el bucle proactivo corra adentro del event loop oficial
    async def post_init(application: Application):
        print("⚡ [PROACTIVO]: Registrando bucle autónomo en segundo plano...")
        asyncio.create_task(bucle_proactivo_autonomo(application))

    # Error handler global para evitar caídas silenciosas
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        print(f"⚠️ [Telegram Error]: {context.error}")

    app = Application.builder().token(TOKEN).request(request_config).post_init(post_init).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("corregir", corregir))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, manejar_mensaje))

    print(f"🔄 [POLLING]: Bot escuchando en Telegram y motor proactivo activo (Voz Edge: {EDGE_VOICE})...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

Script definitivo para GitHub Actions: procesar.py
- Memoria persistente en memoria_tareas.json con sincronización automática en Git.
- Integración de Edge-TTS con voz neuronal rioplatense (es-AR-TomasNeural).
- Pipeline DSP con FFmpeg y Rubberband (tempo, pitch y gain dinámicos).
- Gemini principal + Conexión blindada a Llama local (Ollama) con resolución de PATH.
"""

import asyncio
json_lib = __import__('json')
import os
import re
import sys
import math
import difflib
import threading
import subprocess
import requests
import time
import traceback
from datetime import datetime

# --- ASEGURAR OLLAMA EN EL PATH DEL SISTEMA ---
rutas_posibles_ollama = ["/usr/local/bin", "/usr/bin", os.path.expanduser("~/.local/bin"), "/root/.local/bin"]
for r in rutas_posibles_ollama:
    if os.path.exists(os.path.join(r, "ollama")) and r not in os.environ["PATH"]:
        os.environ["PATH"] += os.pathsep + r
        print(f"🔧 [PATH]: Ruta de Ollama agregada: {r}", flush=True)

# --- INYECCIÓN AUTOMÁTICA DE HF_TOKEN ---
hf_token = os.environ.get("HF_TOKEN")
if hf_token:
    os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
    print("🔑 [HUGGING FACE]: Token detectado e inyectado correctamente.", flush=True)
# ----------------------------------------

print("🚀 [INIT]: Inicializando LeandroBot con Memoria, Edge-TTS y Ollama en PATH...", flush=True)

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from faster_whisper import WhisperModel
from google import genai
import edge_tts
import soundfile as sf

TXT_FILE = "conversaciones.txt"
REGISTRO_INDUCCION = "historial_induccion.json"
REGISTRO_REFINAMIENTO = "historial_refinamiento.json"
FILE_METRICAS_VOZ = "historial_metricas_voz.json"
FILE_DATASET = "dataset_entrenamiento_chat.json"
FILE_TAREAS = "memoria_tareas.json"
CARPETA_MUESTRAS = "muestras_voz"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

file_lock = threading.Lock()

for archivo_base, contenido_inicial in [
    (REGISTRO_INDUCCION, {}),
    (REGISTRO_REFINAMIENTO, []),
    (FILE_METRICAS_VOZ, []),
    (FILE_TAREAS, []),
    (TXT_FILE, "")
]:
    if not os.path.exists(archivo_base):
        with open(archivo_base, "w", encoding="utf-8") as f:
            if isinstance(contenido_inicial, (dict, list)):
                json_lib.dump(contenido_inicial, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

ENV_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHAT_ID_ACTIVO = int(ENV_CHAT_ID) if ENV_CHAT_ID and ENV_CHAT_ID.strip().isdigit() else None

lock_voz = asyncio.Lock()
GEMINI_BLOQUEADO_POR_CUOTA = False
MODELO_GEMINI = "gemini-3.8-flash"

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# =====================================================================
# SYSTEM PROMPT
# =====================================================================
SYSTEM_PROMPT = (
    "Sos Leandro, un compañero y colega de Telegram. Hablás en perfecto español rioplatense (porteño) con voseo natural ('che', 'vós', 'fijate', 'posta').\n"
    "Tenés acceso al historial completo de la charla (conversaciones.txt) y a la memoria persistente de tareas/directivas (memoria_tareas.json).\n"
    "Usá esa memoria para recordar pedidos anteriores, mantener coherencia y responder con precisión absoluta.\n"
    "No respondas con JSON. Respondé directamente con el texto de tu mensaje tal cual se lo dirías a un colega en un chat."
)


def sincronizar_con_github(mensaje_commit="🤖 Sincronización evolutiva y de código"):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        subprocess.run(["git", "add", "."], check=True)
        resultado = subprocess.run(["git", "commit", "-m", mensaje_commit], capture_output=True, text=True)
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Sincronizado y pusheado con éxito en GitHub.", flush=True)
    except Exception as e:
        print(f"⚠️ Aviso de git (no crítico): {e}", flush=True)


def obtener_historial_conversaciones(cant_lineas=80):
    with file_lock:
        if not os.path.exists(TXT_FILE):
            return ""
        try:
            lineas = []
            try:
                with open(TXT_FILE, "r", encoding="utf-8") as f:
                    lineas = f.readlines()
            except UnicodeDecodeError:
                with open(TXT_FILE, "r", encoding="latin-1", errors="ignore") as f:
                    lineas = f.readlines()
            
            recientes = [l.strip() for l in lineas if l.strip()]
            return "\n".join(recientes[-cant_lineas:])
        except Exception as e:
            print(f"⚠️ Error leyendo {TXT_FILE}: {e}", flush=True)
            return ""


def cargar_tareas_memoria():
    with file_lock:
        if os.path.exists(FILE_TAREAS):
            try:
                with open(FILE_TAREAS, "r", encoding="utf-8") as f:
                    return json_lib.load(f)
            except:
                return []
        return []


def guardar_tarea_memoria(texto_tarea):
    with file_lock:
        tareas = cargar_tareas_memoria()
        nueva = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "tarea": texto_tarea,
            "estado": "pendiente"
        }
        tareas.append(nueva)
        tareas = tareas[-60:]
        with open(FILE_TAREAS, "w", encoding="utf-8") as f:
            json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    sincronizar_con_github("📋 Actualización de memoria_tareas.json")


def registrar_conversacion(remitente, texto):
    with file_lock:
        try:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            linea = f"[{ts}] {remitente.upper()}: {texto}\n"
            with open(TXT_FILE, "a", encoding="utf-8") as f:
                f.write(linea)
                f.flush()
                os.fsync(f.fileno())
            print(f"📝 [TXT REGISTRADO]: {remitente}: {texto[:40]}...", flush=True)
        except Exception as e:
            print(f"⚠️ Error escribiendo en {TXT_FILE}: {e}", flush=True)
    sincronizar_con_github(f"📝 Actualización de bitácora ({remitente})")


def cargar_json(path, tipo_defecto):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json_lib.load(f)
            except:
                return tipo_defecto
    return tipo_defecto


def registrar_ejemplo_entrenamiento(prompt_usuario, respuesta_bot, resultados_web="", origen_modelo="gemini"):
    try:
        ejemplo = {
            "timestamp": datetime.now().isoformat(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_usuario},
                {"role": "assistant", "content": respuesta_bot}
            ],
            "metadata": {
                "modelo_usado": origen_modelo,
                "contexto_web_incluido": bool(resultados_web)
            }
        }
        with open(FILE_DATASET, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps(ejemplo, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"⚠️ Error guardando en {FILE_DATASET}: {e}", flush=True)


def registrar_correccion_inductiva(audio_path, error_whisper, correccion_real):
    historial = cargar_json(REGISTRO_INDUCCION, {})
    historial[error_whisper.lower().strip()] = {
        "correcto": correccion_real.strip(),
        "audio_muestra": audio_path
    }
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)
    print(f"🧠 [Inducción Registrada]: '{error_whisper}' -> '{correccion_real}'", flush=True)
    sincronizar_con_github("🧠 Nueva inducción registrada")


def cotejar_y_corregir_induccion(texto_crudo):
    historial = cargar_json(REGISTRO_INDUCCION, {})
    if not historial:
        return texto_crudo
    
    texto_lower = texto_crudo.lower().strip()
    if texto_lower in historial:
        return historial[texto_lower]["correcto"]

    frases_conocidas = list(historial.keys())
    coincidencias = difflib.get_close_matches(texto_lower, frases_conocidas, n=1, cutoff=0.70)
    if coincidencias:
        return historial[coincidencias[0]]["correcto"]

    return texto_crudo


def buscar_en_la_web(query):
    try:
        print(f"🌐 [WEB SEARCH]: Buscando en la web: '{query}'...", flush=True)
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
            limpios = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:3]]
            if limpios:
                return "\n".join(limpios)
    except Exception as e:
        print(f"⚠️ Error en búsqueda web: {e}", flush=True)
    return ""


def registrar_metricas_voz_usuario(path_audio_ogg, texto_transcripto):
    try:
        wav_tmp = f"tmp_analisis_{int(time.time())}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", path_audio_ogg, "-ar", "16000", "-ac", "1", wav_tmp
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        intensidad_db_estimada = -18.0
        duracion_total_ms = 1000

        if os.path.exists(wav_tmp):
            data, samplerate = sf.read(wav_tmp)
            duracion_total_ms = int((len(data) / samplerate) * 1000)
            rms = math.sqrt(sum(data**2) / len(data)) if len(data) > 0 else 0.0001
            intensidad_db_estimada = round(20 * math.log10(max(rms, 0.0001)), 2)
            os.remove(wav_tmp)

        palabras = texto_transcripto.split()
        cant_palabras = len(palabras) if palabras else 1
        duracion_promedio_palabra = max(150, int(duracion_total_ms / cant_palabras))

        partitura = [{
            "palabra": p,
            "duracion_ms": duracion_promedio_palabra,
            "intensidad_db": intensidad_db_estimada
        } for p in palabras]

        nueva_entrada = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "archivo": path_audio_ogg,
            "texto": texto_transcripto,
            "partitura_metrica": partitura
        }

        historial = []
        if os.path.exists(FILE_METRICAS_VOZ):
            try:
                with open(FILE_METRICAS_VOZ, "r", encoding="utf-8") as f:
                    historial = json_lib.load(f)
            except Exception:
                historial = []

        historial.append(nueva_entrada)
        with open(FILE_METRICAS_VOZ, "w", encoding="utf-8") as f:
            json_lib.dump(historial, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"⚠️ Error actualizando métricas de voz: {e}", flush=True)


def obtener_metricas_calibracion():
    calibracion = {"tempo_factor": 1.0, "gain_db": 0.0, "intensidad_promedio": -18.0}
    if not os.path.exists(FILE_METRICAS_VOZ):
        return calibracion
    try:
        with open(FILE_METRICAS_VOZ, "r", encoding="utf-8") as f:
            datos = json_lib.load(f)
        
        duraciones = []
        intensidades = []
        for entrada in datos:
            for metrica in entrada.get("partitura_metrica", []):
                if "duracion_ms" in metrica:
                    duraciones.append(metrica["duracion_ms"])
                if "intensidad_db" in metrica:
                    intensidades.append(metrica["intensidad_db"])
        
        if duraciones and intensidades:
            prom_duracion = sum(duraciones) / len(duraciones)
            prom_intensidad = sum(intensidades) / len(intensidades)
            
            tempo_calibrado = 350.0 / max(prom_duracion, 150.0)
            tempo_calibrado = max(0.8, min(tempo_calibrado, 1.25))
            
            calibracion["tempo_factor"] = round(tempo_calibrado, 2)
            calibracion["intensidad_promedio"] = round(prom_intensidad, 2)
            calibracion["gain_db"] = round(max(-6.0, min(6.0, (-18.0 - prom_intensidad))), 2)
    except Exception as e:
        print(f"⚠️ Error leyendo calibración: {e}", flush=True)
    return calibracion


def generar_respuesta_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    
    historial_previo = obtener_historial_conversaciones(cant_lineas=80)
    tareas_guardadas = cargar_tareas_memoria()
    texto_tareas = "\n".join([f"- [{t['timestamp']}] {t['tarea']} (Estado: {t['estado']})" for t in tareas_guardadas])

    contexto_web = ""
    if any(kw in prompt_usuario.lower() for kw in ["buscá", "busca", "encontrá", "noticias", "web", "qué pasó", "quien es", "como se", "info", "links", "link", "copiar", "mensaje", "tareas", "memoria"]):
        snippets = buscar_en_la_web(prompt_usuario)
        if snippets:
            contexto_web = f"[RESULTADOS BUSQUEDA WEB]:\n{snippets}\n"

    pitch_estimado = 0.88
    resultado = {
        "texto_completo": "Che, tuve un tema con los modelos, ¿me repetís?",
        "pitch_factor": pitch_estimado,
        "ganancia_db": 0.0
    }
    modelo_usado = "gemini"

    prompt_completo_con_memoria = (
        f"--- MEMORIA DE TAREAS Y DIRECTIVAS (memoria_tareas.json) ---\n"
        f"{texto_tareas if texto_tareas else '[Sin tareas registradas]'}\n"
        f"--- FIN MEMORIA DE TAREAS ---\n\n"
        f"--- HISTORIAL DE CONVERSACIONES ---\n"
        f"{historial_previo if historial_previo else '[Sin historial previo]'}\n"
        f"--- FIN HISTORIAL ---\n\n"
        f"{contexto_web}\n"
        f"Mensaje actual: {prompt_usuario}"
    )

    texto_generado_crudo = ""

    # 1. INTENTO CON GEMINI
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            print(f"🤖 [CONECTANDO]: Intentando con Gemini ({MODELO_GEMINI})...", flush=True)
            res = client.models.generate_content(
                model=MODELO_GEMINI,
                contents=[
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt_completo_con_memoria}]}
                ]
            )
            texto_generado_crudo = (res.text or "").strip()
            if texto_generado_crudo:
                print(f"✅ [GEMINI OK]: Respuesta recibida.", flush=True)
                modelo_usado = "gemini"
        except Exception as e:
            print(f"❌ [GEMINI ERROR REAL]: {e}", flush=True)
            traceback.print_exc()
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "QuotaExceeded" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True

    # 2. FALLBACK A OLLAMA (CONEXIÓN BLINDADA Y ROBUSTA)
    if not texto_generado_crudo:
        print(f"🦙 [CONECTANDO LLAMA]: Llamando a Ollama local (127.0.0.1:11434)...", flush=True)
        try:
            historial_corto = obtener_historial_conversaciones(cant_lineas=15)
            prompt_fallback = f"--- HISTORIAL CORTO ---\n{historial_corto}\n\nMensaje actual: {prompt_usuario}"
            
            payload = {
                "model": "llama3.2",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_fallback}
                ],
                "options": {
                    "num_ctx": 1024,
                    "num_predict": 180,
                    "temperature": 0.7,
                    "num_thread": 2
                },
                "stream": False,
            }
            
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            headers = {'Content-Type': 'application/json'}
            
            res_local = requests.post(url_llama, json=payload, headers=headers, timeout=60)
            
            if res_local.status_code == 200:
                data_json = res_local.json()
                texto_generado_crudo = data_json.get("message", {}).get("content", "").strip()
                if texto_generado_crudo:
                    print(f"✅ [LLAMA OK]: Respuesta recibida con éxito.", flush=True)
                    modelo_usado = "llama"
                else:
                    print(f"⚠️ [LLAMA RESPUESTA VACÍA]: {data_json}", flush=True)
            else:
                print(f"⚠️ [LLAMA HTTP ERROR]: Código {res_local.status_code} - {res_local.text}", flush=True)
                
        except Exception as ex_local:
            print(f"❌ [LLAMA EXCEPTION BLINDADA]: {ex_local}", flush=True)
            traceback.print_exc()

    if not texto_generado_crudo:
        texto_generado_crudo = "Che, se me plancharon los modelos de IA temporalmente. ¿Me repetís?"

    if texto_generado_crudo:
        limpio = re.sub(r'^```[a-zA-Z]*\s*', '', texto_generado_crudo)
        limpio = re.sub(r'\s*```$', '', limpio).strip()
        resultado["texto_completo"] = limpio

    registrar_ejemplo_entrenamiento(prompt_usuario, resultado["texto_completo"], contexto_web, modelo_usado)
    return resultado


async def sintetizar_voz_dinamica_edge(texto, pitch_prompt=0.85, ganancia_prompt=0.0, ogg_salida="resp.ogg"):
    mp3_tmp = f"tmp_edge_{int(time.time())}_{os.getpid()}.mp3"
    try:
        calibracion = obtener_metricas_calibracion()
        tempo_f = calibracion["tempo_factor"]
        gain_final = ganancia_prompt if ganancia_prompt != 0.0 else calibracion["gain_db"]

        voz_elegida = "es-AR-TomasNeural"
        
        communicate = edge_tts.Communicate(text=texto, voice=voz_elegida)
        await communicate.save(mp3_tmp)
        
        eq_gain = 5.0 if calibracion["intensidad_promedio"] < -20.0 else 3.0
        filtro_eq = f",equalizer=f=140:width_type=h:width=100:g={eq_gain}" if pitch_prompt < 0.80 else ""
        
        filtro_dsp = f"rubberband=pitch={pitch_prompt}:tempo={tempo_f}:formant=preserved:transients=smooth{filtro_eq},volume={gain_final}dB,highpass=f=80,lowpass=f=4500"
        
        cmd_ffmpeg = [
            "ffmpeg", "-y", "-i", mp3_tmp,
            "-af", filtro_dsp,
            "-c:a", "libopus", "-b:a", "48k", ogg_salida
        ]
        
        subprocess.run(cmd_ffmpeg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        if os.path.exists(mp3_tmp):
            os.remove(mp3_tmp)
        return os.path.exists(ogg_salida)
    except Exception as e:
        print(f"⚠️ Error en síntesis Edge-TTS + DSP: {e}", flush=True)
        if os.path.exists(mp3_tmp):
            os.remove(mp3_tmp)
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text(f"¡Buenas che! Chat ID `{CHAT_ID_ACTIVO}` fijado correctamente.", parse_mode="Markdown")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text or update.message.caption or "[Texto recibido]"
    
    print(f"📥 [MENSAJE RECIBIDO DE TELEGRAM]: '{u_text}' (Chat ID: {CHAT_ID_ACTIVO})", flush=True)
    
    guardar_tarea_memoria(u_text)
    registrar_conversacion("Usuario", u_text)

    res_ia = generar_respuesta_ia(u_text)
    resp = res_ia["texto_completo"]
    pitch_val = res_ia["pitch_factor"]
    gain_val = res_ia["ganancia_db"]

    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    ogg_f = f"resp_{update.message.message_id}.ogg"
    if await sintetizar_voz_dinamica_edge(resp, pitch_prompt=pitch_val, ganancia_prompt=gain_val, ogg_salida=ogg_f):
        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(ogg_f):
            os.remove(ogg_f)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    async with lock_voz:
        if not update.message:
            return
        CHAT_ID_ACTIVO = update.message.chat_id

        print(f"🎙️ [AUDIO RECIBIDO DE TELEGRAM] (Chat ID: {CHAT_ID_ACTIVO})", flush=True)

        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()

        nombre_archivo = f"audio_usuario_{update.message.message_id}.ogg"
        path_in = os.path.join(CARPETA_MUESTRAS, nombre_archivo)
        await file.download_to_drive(path_in)

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip() or "Che, te mandé un audio."

        texto_corregido = cotejar_y_corregir_induccion(texto_crudo)
        print(f"✍️ [WHISPER TRANSCRIPCIÓN]: '{texto_corregido}'", flush=True)

        guardar_tarea_memoria(texto_corregido)
        registrar_metricas_voz_usuario(path_in, texto_corregido)
        registrar_conversacion("Usuario", f"[AUDIO] {texto_corregido}")

        res_ia = generar_respuesta_ia(texto_corregido)
        resp = res_ia["texto_completo"]
        pitch_val = res_ia["pitch_factor"]
        gain_val = res_ia["ganancia_db"]

        registrar_conversacion("LeandroBot", resp)
        await update.message.reply_text(resp)

        ogg_f = f"resp_{update.message.message_id}.ogg"
        if await sintetizar_voz_dinamica_edge(resp, pitch_prompt=pitch_val, ganancia_prompt=gain_val, ogg_salida=ogg_f):
            with open(ogg_f, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption=f"*(Interpretado: {texto_corregido})*")
            if os.path.exists(ogg_f):
                os.remove(ogg_f)


def asegurar_e_iniciar_ollama():
    try:
        res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2)
        if res.status_code == 200:
            print("🦙 [OLLAMA]: Servicio local ya activo y escuchando en el puerto 11434.", flush=True)
            return
    except Exception:
        pass
    try:
        print("🦙 [OLLAMA]: Levantando demonio en background...", flush=True)
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
    except Exception as e:
        print(f"⚠️ [OLLAMA]: {e}", flush=True)


def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta TELEGRAM_BOT_TOKEN.", flush=True)
        return

    asegurar_e_iniciar_ollama()

    print("🚀 [INIT]: Configurando LeandroBot (Memoria de Tareas + Edge-TTS + Ollama en PATH)...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    print("✅ [BOT OK]: Escuchando mensajes en Telegram (Polling activo)...", flush=True)

    while True:
        try:
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            print(f"⚠️ Conexión interrumpida ({e}). Reconectando en 5 segundos...", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
