import asyncio
import json as json_lib
import os
import re
import sys
import shutil
import subprocess
import requests
import time
import numpy as np

print("🚀 [INIT]: Importando librerías y configurando entorno con doble motor (Neuronal + Cuantitativo)...")

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

# Intentamos cargar dependencias para clonación liviana
try:
    from transformers import AutoProcessor, BarkModel
    import torch
    import soundfile as sf
    BARK_DISPONIBLE = True
    print("✅ [INIT]: Motor de clonación liviano (Bark) disponible.")
except ImportError:
    BARK_DISPONIBLE = False
    print("⚠️ [INIT]: Bark no disponible, se usará síntesis base.")

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
    "pitch": 1.05,
    "fundamental_freq": 140,
    "treble_gain": 5.0,
    "treble_freq": 3800,
    "bass_gain": 1.5,
    "bass_freq": 90,
    "volume_mult": 0.9,
    "modo_imitacion": "activo"
}

PROSODIA_DEFAULT = {
    "modo_imitacion": "activo",
    "patron_pausas": "natural_humano_porteno",
    "factor_ritmo_variable": 1.05
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


def cargar_json_seguro(path, defecto):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json_lib.load(f)
        except:
            return defecto
    return defecto


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


def llamar_ia_externa_o_local(prompt_usuario, system_prompt_custom=None):
    global GEMINI_BLOQUEADO_POR_CUOTA
    
    system_prompt = system_prompt_custom or (
        "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. "
        "Porteño, cálido, directo, usando 'vos' y 'che'. "
        "IMPORTANTE PARA LA VOZ: Escribí tus respuestas con una cadencia conversacional marcada, "
        "usando puntos suspensivos (...) donde el locutor respira o hace pausas naturales, "
        "y MAYÚSCULAS en las palabras clave para dar énfasis."
    )
    
    respuesta = ""

    # 1. Intento con Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=f"Solicitud: \"{prompt_usuario}\"",
                config=genai.types.GenerateContentConfig(system_instruction=system_prompt)
            )
            if res and res.text:
                respuesta = res.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
            print(f"⚠️ Gemini falló o sin cuota, usando Ollama local: {e}")

    # 2. Fallback Automático a Llama 3.2 local (Ollama)
    if not respuesta:
        print("🦙 [OLLAMA LOCAL]: Generando respuesta con Llama 3.2...")
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.6},
            "stream": False,
        }
        try:
            res_local = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=15)
            if res_local.status_code == 200:
                respuesta = res_local.json().get("message", {}).get("content", "").strip()
        except Exception as ex:
            print(f"⚠️ Error conectando a Ollama local: {ex}")

    if not respuesta:
        respuesta = "Che... me quedé sin conexión por todos lados... tirámela de nuevo en un ratito."
    return respuesta


def generar_audio_con_clonador(texto, ogg_salida="resp.ogg"):
    wav_temp = "temp_voz.wav"
    generado_ok = False

    if BARK_DISPONIBLE:
        try:
            print("🎙️ [CLONADOR]: Sintetizando voz neuronal con Bark...")
            processor = AutoProcessor.from_pretrained("suno/bark-small")
            model = BarkModel.from_pretrained("suno/bark-small")
            
            device = "cpu"
            model = model.to(device)

            texto_procesar = f"[es] {texto[:180]}"
            inputs = processor(texto_procesar, voice_preset="v2/es_speaker_2").to(device)
            
            with torch.no_grad():
                audio_array = model.generate(**inputs)
            
            audio_array = audio_array.cpu().numpy().squeeze()

            sf.write(wav_temp, audio_array, model.generation_config.sample_rate)
            generado_ok = os.path.exists(wav_temp)
            print("✅ [CLONADOR]: Audio neuronal generado con éxito.")
        except Exception as e:
            print(f"⚠️ Error en modelo Bark: {e}")

    if not generado_ok:
        print("⚠️ Usando fallback de emergencia con FFmpeg...")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", wav_temp], check=True)

    # Retoque final con FFmpeg (Estudio FM nocturno)
    filtros = [
        "dynaudnorm=f=125:g=15:p=0.9",
        "equalizer=f=90:t=h:w=100:g=3.0",
        "equalizer=f=3500:t=h:w=300:g=4.0",
        "volume=0.95"
    ]

    subprocess.run([
        "ffmpeg", "-y", "-i", wav_temp,
        "-filter:a", ",".join(filtros),
        "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
        ogg_salida
    ], check=True)

    if os.path.exists(wav_temp):
        os.remove(wav_temp)


def generar_audio_cuantitativo(partitura_json, ogg_salida="resp.ogg"):
    """Motor DSP cuantitativo: renderiza audio matemático milisegundo a milisegundo."""
    wav_temp = "temp_cuant.wav"
    sample_rate = 22050
    audio_total = np.array([], dtype=np.float32)

    try:
        print("🎛️ [DSP CUANTITATIVO]: Renderizando partitura numérica exacta...")
        for item in partitura_json:
            duracion_ms = item.get("duracion_ms", 100)
            pitch = item.get("pitch_hz", 150)
            intensidad_db = item.get("intensidad_db", 0.0)
            
            num_samples = int(sample_rate * (duracion_ms / 1000.0))
            if num_samples <= 0:
                continue
            
            t = np.linspace(0, duracion_ms / 1000.0, num_samples, endpoint=False)
            
            if pitch == 0:
                onda = np.zeros(num_samples, dtype=np.float32)
            else:
                onda = 0.5 * np.sin(2 * np.pi * pitch * t) + 0.2 * np.sin(2 * np.pi * (pitch * 2) * t)
                envolvente = np.hanning(num_samples) if num_samples > 1 else np.ones(1)
                onda = onda * envolvente
                
                mult_vol = 10 ** (intensidad_db / 20.0)
                onda = onda * mult_vol

            audio_total = np.concatenate((audio_total, onda))

        sf.write(wav_temp, audio_total, sample_rate)
        
    except Exception as e:
        print(f"⚠️ Error en motor cuantitativo, usando tono plano: {e}")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", wav_temp], check=True)

    subprocess.run([
        "ffmpeg", "-y", "-i", wav_temp,
        "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
        ogg_salida
    ], check=True)

    if os.path.exists(wav_temp):
        os.remove(wav_temp)
    print("✅ [DSP CUANTITATIVO]: Audio matemático generado con éxito.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con doble motor: Clonador Neuronal FM y Síntesis Cuantitativa DSP.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    es_cuantitativo = any(w in texto_usuario.lower() for w in ["cuantitativo", "paramétrico", "exacto", "frecuencia", "dsp"])

    await update.message.chat.send_action(action="record_voice")
    ogg_f = "resp.ogg"

    if es_cuantitativo:
        print("🔬 [MODO]: Activando síntesis cuantitativa paramétrica...")
        prompt_cuant = (
            "Analiza esta frase y genera EXCLUSIVAMENTE un JSON válido que sea una lista de objetos. "
            "Cada objeto debe contener exactamente: 'fonema' (string), 'duracion_ms' (entero entre 50 y 300), "
            "'pitch_hz' (frecuencia en Hz entre 80 y 300, o 0 para silencios/pausas), "
            "e 'intensidad_db' (entre -6 y 0). "
            f"Frase a procesar: \"{texto_usuario}\""
        )
        
        system_cuant = "Sos un motor de síntesis de voz paramétrica DSP. Devuelves únicamente JSON puro sin markdown ni texto extra."
        respuesta_ia = llamar_ia_externa_o_local(prompt_cuant, system_prompt_custom=system_cuant)
        
        try:
            inicio = respuesta_ia.find('[')
            fin = respuesta_ia.rfind(']') + 1
            partitura = json_lib.loads(respuesta_ia[inicio:fin])
            generar_audio_cuantitativo(partitura, ogg_f)
        except Exception as err:
            print(f"⚠️ Falló el parseo cuantitativo JSON, usando fallback neuronal: {err}")
            respuesta_normal = llamar_ia_externa_o_local(texto_usuario)
            texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta_normal)
            texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()
            generar_audio_con_clonador(texto_limpio, ogg_f)
    else:
        respuesta = llamar_ia_externa_o_local(texto_usuario)
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()
        generar_audio_con_clonador(texto_limpio, ogg_f)

    with open(ogg_f, "rb") as vf:
        caption_txt = "🔬 *(Modo Cuantitativo DSP Paramétrico)*" if es_cuantitativo else "🎙️ *(Locución Neuronal FM)*"
        await update.message.reply_voice(voice=vf, caption=caption_txt)

    if os.path.exists(ogg_f): 
        os.remove(ogg_f)


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
            await update.message.reply_text("Che, no te capté bien el audio.")
            return

        respuesta = llamar_ia_externa_o_local(texto_crudo)
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

        ogg_f = "resp.ogg"
        generar_audio_con_clonador(texto_limpio, ogg_f)

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"🗣️ Entendido: {texto_crudo}")

        if os.path.exists(ogg_f): os.remove(ogg_f)


def main():
    if not TOKEN:
        print("❌ ERROR: Falta TELEGRAM_BOT_TOKEN.")
        return

    print("🧹 Limpiando webhooks...")
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except Exception as e:
        print(f"⚠️ Aviso webhook: {e}")

    print("🚀 Iniciando Bot con doble motor (Neuronal FM + Cuantitativo DSP)...")
    
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
