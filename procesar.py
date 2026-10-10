import asyncio
json_lib = __import__('json')
import os
import re
import sys
import shutil
import difflib
import subprocess
import requests
import time

print("🚀 [INIT]: Importando librerías...")

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
from gtts import gTTS

try:
    from google import genai
    GENAI_DISPONIBLE = True
    print("✅ [INIT]: Google GenAI disponible.")
except ImportError:
    GENAI_DISPONIBLE = False
    print("⚠️ [INIT]: Google GenAI NO disponible.")

TXT_FILE = "conversaciones.txt"
REGISTRO_INDUCCION = "historial_induccion.json"
REGISTRO_REFINAMIENTO = "historial_refinamiento.json"
ARCHIVO_PERILLAS = "perillas_voz.json"
ARCHIVO_PROSODIA = "prosodia_cadencia.json"
CARPETA_MUESTRAS = "muestras_voz"
CARPETA_ORIGINALES = "originales"
CARPETA_RECURSIVA = "evolucion_recursiva"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)
os.makedirs(CARPETA_ORIGINALES, exist_ok=True)
os.makedirs(CARPETA_RECURSIVA, exist_ok=True)

PERILLAS_DEFAULT = {
    "serie_armonica": [
        [1.0, 0.0],
        [2.0, -5.0],
        [3.0, -10.0],
        [4.0, -15.0],
        [5.0, -20.0]
    ],
    "pitch": 1.05,
    "fundamental_freq": 140,
    "treble_gain": 5.0,
    "treble_freq": 3800,
    "bass_gain": 1.5,
    "bass_freq": 90,
    "harmonic_drive": 0.6,
    "harmonic_freq": 400,
    "crusher_bits": 16,
    "volume_mult": 0.85,
    "modo_imitacion": "activo"
}

PROSODIA_DEFAULT = {
    "modo_imitacion": "activo",
    "patron_pausas": "natural_humano_porteno",
    "factor_ritmo_variable": 1.05,
    "dinamica_movil": "acentuacion_y_corte",
    "referencia_activa": "libre_y_arquetipos"
}

if not os.path.exists(ARCHIVO_PERILLAS):
    with open(ARCHIVO_PERILLAS, "w", encoding="utf-8") as f:
        json_lib.dump(PERILLAS_DEFAULT, f, indent=4, ensure_ascii=False)

if not os.path.exists(ARCHIVO_PROSODIA):
    with open(ARCHIVO_PROSODIA, "w", encoding="utf-8") as f:
        json_lib.dump(PROSODIA_DEFAULT, f, indent=4, ensure_ascii=False)

for archivo_base, contenido_inicial in [
    (REGISTRO_INDUCCION, {}),
    (REGISTRO_REFINAMIENTO, []),
    (TXT_FILE, "")
]:
    if not os.path.exists(archivo_base):
        with open(archivo_base, "w", encoding="utf-8") as f:
            if isinstance(contenido_inicial, (dict, list)):
                json_lib.dump(contenido_inicial, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY) if (GENAI_DISPONIBLE and GEMINI_API_KEY) else None
GEMINI_BLOQUEADO_POR_CUOTA = False

lock_voz = asyncio.Lock()
ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}


def cargar_json_seguro(path, defecto):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json_lib.load(f)
        except:
            return defecto
    return defecto


def guardar_json_seguro(path, datos, mensaje_git):
    with open(path, "w", encoding="utf-8") as f:
        json_lib.dump(datos, f, indent=4, ensure_ascii=False)
    sincronizar_con_github(mensaje_git)


def inicializar_directorios_control(archivo_actual="procesar.py"):
    try:
        path_original = os.path.join(CARPETA_ORIGINALES, archivo_actual)
        if os.path.exists(archivo_actual) and not os.path.exists(path_original):
            shutil.copy(archivo_actual, path_original)
        path_recursivo = os.path.join(CARPETA_RECURSIVA, archivo_actual)
        if os.path.exists(archivo_actual):
            shutil.copy(archivo_actual, path_recursivo)
    except Exception as e:
        print(f"⚠️ Error en control de directorios: {e}")


def sincronizar_con_github(mensaje_commit="🤖 Sincronización autónoma"):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        token_git = os.environ.get("GITHUB_TOKEN")
        if token_git:
            subprocess.run(["git", "remote", "set-url", "origin", f"https://{token_git}@github.com/LeandroViv/Bot.git"], check=True)
        subprocess.run(["git", "add", "procesar.py", "perillas_voz.json", "prosodia_cadencia.json", "historial_induccion.json", "historial_refinamiento.json", "conversaciones.txt", "muestras_voz/"], check=True)
        resultado = subprocess.run(["git", "commit", "-m", mensaje_commit], capture_output=True, text=True)
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Sincronizado con GitHub.")
    except Exception as e:
        print(f"⚠️ Aviso git: {e}")


def guardar_en_txt(rol, texto):
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")


def registrar_refinamiento_ia(prompt_usuario, respuesta_generada):
    refinamientos = cargar_json_seguro(REGISTRO_REFINAMIENTO, [])
    refinamientos.append({"entrada_usuario": prompt_usuario, "respuesta_ia": respuesta_generada})
    if len(refinamientos) > 100:
        refinamientos = refinamientos[-100:]
    with open(REGISTRO_REFINAMIENTO, "w", encoding="utf-8") as f:
        json_lib.dump(refinamientos, f, indent=4, ensure_ascii=False)


def llamar_ia_externa_o_local(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    system_prompt = "Sos Leandro hablando con un colega por Telegram. Porteño, directo, sin introducciones de robot, usando 'vos' y 'che', con cadencia conversacional natural y fraseada."
    respuesta = ""

    # 1. Intento con Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=f"Colega dice: \"{prompt_usuario}\"",
                config=genai.types.GenerateContentConfig(system_instruction=system_prompt)
            )
            if res and res.text:
                respuesta = res.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
            print(f"⚠️ Gemini falló o se quedó sin cuota, usando Ollama local: {e}")

    # 2. Fallback Automático a Llama 3.2 local (Ollama)
    if not respuesta:
        print("llama [OLLAMA LOCAL]: Generando respuesta con Llama 3.2...")
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.4},
            "stream": False,
        }
        try:
            res_local = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=15)
            if res_local.status_code == 200:
                respuesta = res_local.json().get("message", {}).get("content", "").strip()
        except Exception as ex:
            print(f"⚠️ Error conectando a Ollama local: {ex}")

    if not respuesta:
        respuesta = "Che, me quedé sin conexión por todos lados, tirámela de nuevo en un ratito."
    else:
        registrar_refinamiento_ia(prompt_usuario, respuesta)
    return respuesta


def responder_usuario(orden):
    if not orden or not orden.strip():
        return "Che, no te entendí nada."
    respuesta = llamar_ia_externa_o_local(orden)
    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    return respuesta


def generar_audio_parametrico(texto, ogg_salida):
    mp3_f, wav_f = "resp.mp3", "resp.wav"
    gTTS(text=texto, lang="es", tld="com.ar").save(mp3_f)
    subprocess.run(["ffmpeg", "-y", "-i", mp3_f, wav_f], check=True)
    if os.path.exists(mp3_f): os.remove(mp3_f)

    p = cargar_json_seguro(ARCHIVO_PERILLAS, PERILLAS_DEFAULT)
    prosodia = cargar_json_seguro(ARCHIVO_PROSODIA, PROSODIA_DEFAULT)
    
    pitch = float(p.get("pitch", 1.05))
    fund = float(p.get("fundamental_freq", 140))
    treble_g = float(p.get("treble_gain", 5.0))
    treble_f = float(p.get("treble_freq", 3800))
    bass_g = float(p.get("bass_gain", 1.5))
    bass_f = float(p.get("bass_freq", 90))
    vol = float(p.get("volume_mult", 0.85))

    tempo_base = float(p.get("tempo_factor", 1.10))
    factor_ritmo = float(prosodia.get("factor_ritmo_variable", 1.05))
    tempo = tempo_base * factor_ritmo
    
    serie = p.get("serie_armonica", [])

    filtros = [
        f"atempo={max(0.5, min(2.0, tempo))}",
        f"asetrate=24000*{max(0.4, min(2.0, pitch))}",
        f"equalizer=f={treble_f}:t=h:w=300:g={treble_g}",
        f"equalizer=f={bass_f}:t=h:w=100:g={bass_g}"
    ]

    for item in serie:
        try:
            if isinstance(item, list) and len(item) == 2:
                m, db = float(item[0]), float(item[1])
            elif isinstance(item, dict):
                m, db = float(item.get("multiplicador", 1.0)), float(item.get("gain_db", 0.0))
            else:
                continue
                
            freq = fund * m
            if 20.0 <= freq <= 11000.0:
                filtros.append(f"equalizer=f={freq:.2f}:t=h:w={max(15, int(freq*0.08))}:g={db}")
        except:
            pass

    filtros.extend([
        "dynaudnorm=f=120:g=18:p=0.9",
        f"volume={vol}"
    ])

    subprocess.run(["ffmpeg", "-y", "-i", wav_f, "-filter:a", ",".join(filtros), "-c:a", "libopus", "-b:a", "48k", "-ar", "24000", ogg_salida], check=True)
    if os.path.exists(wav_f): os.remove(wav_f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot paramétrico activo con soporte dual Gemini / Llama 3.2 local.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    quiere_voz = any(w in texto_usuario.lower() for w in ["imitá", "imitar", "voz", "audio", "hablá", "explicame", "chiste"])

    if quiere_voz:
        await update.message.chat.send_action(action="record_voice")
        respuesta = responder_usuario(texto_usuario)
        
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

        ogg_f = "resp.ogg"
        generar_audio_parametrico(texto_limpio, ogg_f)

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption="🎚️ *(Audio paramétrico adaptado)*")

        if os.path.exists(ogg_f): os.remove(ogg_f)
    else:
        await update.message.chat.send_action(action="typing")
        respuesta = responder_usuario(texto_usuario)
        await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        path_in = os.path.join(CARPETA_MUESTRAS, f"audio_{update.message.message_id}.ogg")
        await file.download_to_drive(path_in)

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip()

        if not texto_crudo:
            await update.message.reply_text("Che, no te capté bien.")
            return

        respuesta = responder_usuario(texto_crudo)
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

        ogg_f = "resp.ogg"
        generar_audio_parametrico(texto_limpio, ogg_f)

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"-Interpretado: {texto_crudo}\n🎚️ *(Audio paramétrico)*")

        if os.path.exists(ogg_f): os.remove(ogg_f)


def main():
    inicializar_directorios_control("procesar.py")
    if not TOKEN:
        print("❌ ERROR: Falta TELEGRAM_BOT_TOKEN.")
        return

    print("🧹 Limpiando webhooks...")
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except Exception as e:
        print(f"⚠️ Aviso webhook: {e}")

    print("🚀 Iniciando Bot optimizado (Gemini + Ollama local)...")
    
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)
    app = Application.builder().token(TOKEN).request(request_config).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))

    while True:
        try:
            print("🔄 [POLLING]: Escuchando eventos...")
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            print(f"⚠️ Red interrumpida ({e}). Reconectando en 5 segundos...")
            time.sleep(5)


if __name__ == "__main__":
    main()
