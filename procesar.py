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
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from faster_whisper import WhisperModel
from gtts import gTTS

# Importación segura de Google GenAI
try:
    from google import genai
    GENAI_DISPONIBLE = True
    print("✅ [INIT]: Google GenAI disponible.")
except ImportError:
    GENAI_DISPONIBLE = False
    print("⚠️ [INIT]: Google GenAI NO disponible.")

# Importación segura de Coqui XTTS para clonación neuronal
XTTS_DISPONIBLE = False
try:
    from TTS.api import TTS
    XTTS_DISPONIBLE = True
    print("✅ [INIT]: Coqui XTTS disponible.")
except ImportError:
    print("⚠️ [INIT]: Coqui XTTS no instalado. Se usará fallback paramétrico.")

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
_xtts_instance = None

def obtener_xtts():
    global _xtts_instance
    if not XTTS_DISPONIBLE:
        return None
    if _xtts_instance is None:
        try:
            print("🧠 Cargando modelo Coqui XTTS v2 (esto puede tardar unos segundos)...")
            _xtts_instance = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
        except Exception as e:
            print(f"⚠️ Error al inicializar XTTS: {e}")
            return None
    return _xtts_instance


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


def sincronizar_con_github(mensaje_commit="🤖 Sincronización evolutiva y de código"):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        token_git = os.environ.get("GITHUB_TOKEN")
        if token_git:
            subprocess.run(["git", "remote", "set-url", "origin", f"https://{token_git}@github.com/LeandroViv/Bot.git"], check=True)
        subprocess.run(["git", "add", "procesar.py", "perillas_voz.json", "prosodia_cadencia.json", "historial_induccion.json", "historial_refinamiento.json", "conversaciones.txt"], check=True)
        resultado = subprocess.run(["git", "commit", "-m", mensaje_commit], capture_output=True, text=True)
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Código sincronizado con GitHub.")
    except Exception as e:
        print(f"⚠️ Aviso git: {e}")


def guardar_en_txt(rol, texto):
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")


def registrar_correccion_inductiva(audio_path, error_whisper, correccion_real):
    historial = cargar_json_seguro(REGISTRO_INDUCCION, {})
    historial[error_whisper.lower().strip()] = {
        "correcto": correccion_real.strip(),
        "audio_muestra": audio_path
    }
    guardar_json_seguro(REGISTRO_INDUCCION, historial, "🧠 Inducción actualizada")


def registrar_refinamiento_ia(prompt_usuario, respuesta_generada):
    refinamientos = cargar_json_seguro(REGISTRO_REFINAMIENTO, [])
    refinamientos.append({"entrada_usuario": prompt_usuario, "respuesta_ia": respuesta_generada})
    if len(refinamientos) > 100:
        refinamientos = refinamientos[-100:]
    with open(REGISTRO_REFINAMIENTO, "w", encoding="utf-8") as f:
        json_lib.dump(refinamientos, f, indent=4, ensure_ascii=False)


def cotejar_y_corregir_induccion(texto_crudo):
    historial = cargar_json_seguro(REGISTRO_INDUCCION, {})
    if not historial:
        return texto_crudo
    texto_lower = texto_crudo.lower().strip()
    if texto_lower in historial:
        return historial[texto_lower]["correcto"]
    coincidencias = difflib.get_close_matches(texto_lower, list(historial.keys()), n=1, cutoff=0.70)
    if coincidencias:
        return historial[coincidencias[0]]["correcto"]
    return texto_crudo


def buscar_muestra_audio_en_web(query_nombre):
    try:
        query_busqueda = f"{query_nombre} filetype:mp3 OR filetype:wav audio sample"
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query_busqueda)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        print(f"🌐 Buscando muestra web para: {query_nombre}")
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            urls_encontradas = re.findall(r'href="(http[s]?://[^"]+\.(?:mp3|wav))"', res.text, re.I)
            if urls_encontradas:
                link_audio = urls_encontradas[0]
                print(f"🎯 Muestra de audio encontrada en la web: {link_audio}")
                res_audio = requests.get(link_audio, headers=headers, timeout=15)
                if res_audio.status_code == 200:
                    ext = ".wav" if ".wav" in link_audio.lower() else ".mp3"
                    nombre_archivo = f"web_auto_{abs(hash(link_audio))}{ext}"
                    ruta_destino = os.path.join(CARPETA_MUESTRAS, nombre_archivo)
                    with open(ruta_destino, "wb") as f:
                        f.write(res_audio.content)
                    print(f"💾 Muestra descargada y guardada con éxito en: {ruta_destino}")
                    return ruta_destino
    except Exception as e:
        print(f"⚠️ Error descargando muestra web: {e}")
    return None


def obtener_o_construir_muestra_voz(query_nombre):
    ruta_web = buscar_muestra_audio_en_web(query_nombre)
    if ruta_web and os.path.exists(ruta_web):
        return ruta_web

    print(f"⚙️ Muestra web no encontrada. Construyendo muestra sintética de fallback para XTTS...")
    try:
        nombre_archivo = f"sintetica_fallback_{abs(hash(query_nombre))}.wav"
        ruta_sintetica = os.path.join(CARPETA_MUESTRAS, nombre_archivo)
        
        texto_muestra = f"Muestra base de audio generada para clonación neuronal con XTTS para el perfil {query_nombre}."
        mp3_temp = os.path.join(CARPETA_MUESTRAS, "temp_fallback.mp3")
        gTTS(text=texto_muestra, lang="es", tld="com.ar").save(mp3_temp)
        
        subprocess.run(["ffmpeg", "-y", "-i", mp3_temp, "-ar", "24000", "-ac", "1", ruta_sintetica], check=True)
        if os.path.exists(mp3_temp):
            os.remove(mp3_temp)
            
        print(f"💾 Muestra sintética construida en: {ruta_sintetica}")
        return ruta_sintetica
    except Exception as e:
        print(f"⚠️ Error construyendo muestra sintética: {e}")
        return None


def procesar_evolucion_autonoma(prompt_usuario, audio_referencia_path=None):
    global GEMINI_BLOQUEADO_POR_CUOTA
    perillas_actuales = cargar_json_seguro(ARCHIVO_PERILLAS, PERILLAS_DEFAULT)
    prosodia_actual = cargar_json_seguro(ARCHIVO_PROSODIA, PROSODIA_DEFAULT)
    
    if not audio_referencia_path and any(w in prompt_usuario.lower() for w in ["imitá", "imitar", "voz de", "hablá como", "buscá", "buscate", "locutor", "campesino", "actualizá", "xtts"]):
        if any(w in prompt_usuario.lower() for w in ["buscá", "buscate", "imitá", "xtts"]):
            audio_referencia_path = obtener_o_construir_muestra_voz(prompt_usuario)

    prompt_director = (
        "Sos el director acústico y de prosodia paramétrica de este agente.\n"
        f"Perillas actuales: {json_lib.dumps(perillas_actuales)}\n"
        f"Prosodia actual: {json_lib.dumps(prosodia_actual)}\n"
        f"Orden del usuario: '{prompt_usuario}'\n"
        "Si el usuario pide actualizar perillas o tonos, extrae los valores y devuelve un bloque JSON exacto con claves `{\"perillas\": {...}, \"prosodia\": {...}}` entre ```json ... ```. Si no hay pedidos técnicos de audio, responde 'NO_ES_AUDIO'."
    )

    archivo_audio_subido = None
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            if audio_referencia_path and os.path.exists(audio_referencia_path):
                archivo_audio_subido = client.files.upload(file=audio_referencia_path)

            contents_param = [archivo_audio_subido, prompt_director] if archivo_audio_subido else [prompt_director]
            res_p = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=contents_param,
                config=genai.types.GenerateContentConfig(temperature=0.3)
            )
            texto_p = res_p.text.strip()
            if "NO_ES_AUDIO" not in texto_p:
                bloques = re.findall(r"```(?:json)?\s*(.*?)\s*```", texto_p, re.DOTALL)
                if bloques:
                    try:
                        datos = json_lib.loads(bloques[0])
                        if "perillas" in datos:
                            guardar_json_seguro(ARCHIVO_PERILLAS, datos["perillas"], "🎚️ Perillas actualizadas en silencio")
                        if "prosodia" in datos:
                            guardar_json_seguro(ARCHIVO_PROSODIA, datos["prosodia"], "🎙️ Prosodia actualizada en silencio")
                    except:
                        pass
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
        finally:
            if archivo_audio_subido:
                try: client.files.delete(name=archivo_audio_subido.name)
                except: pass

    return None


def llamar_ia_externa_o_local(prompt_usuario, audio_ref=None):
    global GEMINI_BLOQUEADO_POR_CUOTA
    procesar_evolucion_autonoma(prompt_usuario, audio_referencia_path=audio_ref)

    system_prompt = "Sos Leandro hablando con un colega por Telegram. Porteño, directo, sin introducciones de robot, usando 'vos' y 'che', con cadencia conversacional natural y fraseada."
    respuesta = ""

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
            print(f"⚠️ Gemini falló, intentando Ollama: {e}")

    if not respuesta:
        print("🦙 Intentando conectar con Ollama local...")
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
            res_local = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=10)
            if res_local.status_code == 200:
                respuesta = res_local.json().get("message", {}).get("content", "").strip()
        except:
            pass

    if not respuesta:
        respuesta = "Che, me quedé sin conexión, tirámela de nuevo."
    else:
        registrar_refinamiento_ia(prompt_usuario, respuesta)
    return respuesta


def responder_usuario(orden, audio_ref=None):
    if not orden or not orden.strip():
        return "Che, no te entendí nada."
    respuesta = llamar_ia_externa_o_local(orden, audio_ref=audio_ref)
    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con reporte XTTS y reconexión.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    texto_usuario = update.message.text
    print(f"📩 Texto recibido: {texto_usuario}")
    
    if ULTIMO_AUDIO_PENDIENTE["path"] and texto_usuario.lower().startswith(("corregir:", "corrección:")):
        registrar_correccion_inductiva(ULTIMO_AUDIO_PENDIENTE["path"], ULTIMO_AUDIO_PENDIENTE["crudo"], re.sub(r'^(corregir:|corrección:)\s*', '', texto_usuario, flags=re.I))
        ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}
        await update.message.reply_text("Listo, inducción guardada.")
        return

    ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}
    quiere_voz = any(w in texto_usuario.lower() for w in ["imitá", "imitar", "voz", "audio", "hablá", "explicame", "buscáte", "buscate", "muestra", "locutor", "campesino", "actualizá", "chiste", "xtts"])

    if quiere_voz:
        await update.message.chat.send_action(action="record_voice")
        audio_ref = None
        if any(w in texto_usuario.lower() for w in ["imitá", "buscá", "buscate", "xtts"]):
            audio_ref = obtener_o_construir_muestra_voz(texto_usuario)
            
        respuesta = responder_usuario(texto_usuario, audio_ref=audio_ref)
        
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

        ogg_f = "resp.ogg"
        xtts_generado = False

        if audio_ref and os.path.exists(audio_ref):
            xtts_engine = obtener_xtts()
            if xtts_engine:
                try:
                    print(f"🧬 [XTTS]: Intentando clonar voz con referencia: {audio_ref}")
                    wav_xtts = "resp_xtts.wav"
                    xtts_engine.tts_to_file(
                        text=texto_limpio,
                        speaker_wav=audio_ref,
                        language="es",
                        file_path=wav_xtts
                    )
                    subprocess.run(["ffmpeg", "-y", "-i", wav_xtts, "-c:a", "libopus", "-b:a", "48k", "-ar", "24000", ogg_f], check=True)
                    if os.path.exists(wav_xtts): os.remove(wav_xtts)
                    xtts_generado = True
                    print("✅ [XTTS]: ¡Éxito! Audio clonado neuronalmente con XTTS.")
                except Exception as e:
                    print(f"⚠️ [XTTS] Falló la clonación neuronal ({e}). Cambiando a FFmpeg paramétrico...")

        if not xtts_generado:
            print("🎚️ [AVISO]: XTTS no disponible o falló. Renderizando con gTTS + FFmpeg paramétrico...")
            mp3_f, wav_f = "resp.mp3", "resp.wav"
            gTTS(text=texto_limpio, lang="es", tld="com.ar").save(mp3_f)
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

            subprocess.run(["ffmpeg", "-y", "-i", wav_f, "-filter:a", ",".join(filtros), "-c:a", "libopus", "-b:a", "48k", "-ar", "24000", ogg_f], check=True)
            if os.path.exists(wav_f): os.remove(wav_f)

        with open(ogg_f, "rb") as vf:
            if xtts_generado:
                caption_txt = "🧬 *(XTTS: Clonación neuronal exitosa)*"
            else:
                caption_txt = "⚠️ *(XTTS no disponible/falló -> Usé FFmpeg paramétrico)*"
            await update.message.reply_voice(voice=vf, caption=caption_txt)

        if os.path.exists(ogg_f): os.remove(ogg_f)
    else:
        await update.message.chat.send_action(action="typing")
        respuesta = responder_usuario(texto_usuario)
        await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    async with lock_voz:
        print("🎤 Procesando audio entrante...")
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        path_in = os.path.join(CARPETA_MUESTRAS, f"audio_{update.message.message_id}.ogg")
        await file.download_to_drive(path_in)

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_in, beam_size=5, language="es")
        texto_crudo = " ".join([s.text for s in segments]).strip()
        
        ULTIMO_AUDIO_PENDIENTE = {"path": path_in, "crudo": texto_crudo}
        texto_rec = cotejar_y_corregir_induccion(texto_crudo)

        if not texto_rec:
            await update.message.reply_text("Che, no te capté bien.")
            return

        respuesta = responder_usuario(texto_rec, audio_ref=path_in)
        texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
        texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

        ogg_f = "resp.ogg"
        xtts_generado = False

        xtts_engine = obtener_xtts()
        if xtts_engine and os.path.exists(path_in):
            try:
                wav_xtts = "resp_xtts.wav"
                xtts_engine.tts_to_file(
                    text=texto_limpio,
                    speaker_wav=path_in,
                    language="es",
                    file_path=wav_xtts
                )
                subprocess.run(["ffmpeg", "-y", "-i", wav_xtts, "-c:a", "libopus", "-b:a", "48k", "-ar", "24000", ogg_f], check=True)
                if os.path.exists(wav_xtts): os.remove(wav_xtts)
                xtts_generado = True
            except:
                pass

        if not xtts_generado:
            mp3_f, wav_f = "resp.mp3", "resp.wav"
            gTTS(text=texto_limpio, lang="es", tld="com.ar").save(mp3_f)
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

            subprocess.run(["ffmpeg", "-y", "-i", wav_f, "-filter:a", ",".join(filtros), "-c:a", "libopus", "-b:a", "48k", "-ar", "24000", ogg_f], check=True)
            if os.path.exists(wav_f): os.remove(wav_f)

        with open(ogg_f, "rb") as vf:
            if xtts_generado:
                caption_txt = f"-Interpretado: {texto_crudo}\n🧬 *(XTTS Clonación exitosa)*"
            else:
                caption_txt = f"-Interpretado: {texto_crudo}\n⚠️ *(XTTS no disponible -> FFmpeg paramétrico)*"
            await update.message.reply_voice(voice=vf, caption=caption_txt)

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

    print("🚀 Iniciando Bot con reporte XTTS y reconexión automática...")
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))

    while True:
        try:
            print("🔄 [POLLING]: Conectando y escuchando eventos...")
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            print(f"⚠️ Red de Telegram interrumpida ({e}). Reconectando en 5 segundos...")
            time.sleep(5)


if __name__ == "__main__":
    main()
