import asyncio
json_lib = __import__('json')
import os
import re
import sys
import shutil
import difflib
import subprocess
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from faster_whisper import WhisperModel
from google import genai
from gtts import gTTS

TXT_FILE = "conversaciones.txt"
REGISTRO_INDUCCION = "historial_induccion.json"
REGISTRO_REFINAMIENTO = "historial_refinamiento.json"
ARCHIVO_PERILLAS = "perillas_voz.json"
ARCHIVO_PROSODIA = "prosodia_cadencia.json"
CARPETA_MUESTRAS = "muestras_voz"
CARPETA_ORIGINALES = "originales"
CARPETA_RECURSIVA = "evolucion_recursiva"

# Aseguramos directorios base
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)
os.makedirs(CARPETA_ORIGINALES, exist_ok=True)
os.makedirs(CARPETA_RECURSIVA, exist_ok=True)

# Perillas de voz con serie armónica decimal abierta y dinámica (Persistentes)
PERILLAS_DEFAULT = {
    "pitch_factor": 0.80,        # Gravedad de la voz
    "tempo_factor": 1.20,        # Velocidad base
    "fundamental_hz": 130,       # Frecuencia fundamental base (Hz)
    "serie_armonica": [          # Multiplicadores libres (enteros o decimales) y ganancia en dB
        {"multiplicador": 1.0, "gain_db": 0.0},
        {"multiplicador": 2.0, "gain_db": -3.0},
        {"multiplicador": 3.0, "gain_db": -6.0}
    ],
    "treble_gain": 3.0,          # Brillo / Agudos (dB)
    "treble_freq": 4000,         # Frecuencia de corte para agudos (Hz)
    "bass_gain": 5.0,            # Cuerpo / Graves (dB)
    "bass_freq": 150,            # Frecuencia de corte para graves (Hz)
    "volume_mult": 1.1           # Ganancia general
}

# Perfil de prosodia y cadencia inductiva por muestras y arquetipos
PROSODIA_DEFAULT = {
    "modo_imitacion": "activo",
    "patron_pausas": "natural_humano",
    "factor_ritmo_variable": 1.0,
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
            if isinstance(contenido_inicial, dict) or isinstance(contenido_inicial, list):
                json_lib.dump(contenido_inicial, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
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
            print("☁️ Código y perillas sincronizados con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ Aviso de git (no crítico): {e}")


def guardar_en_txt(rol, texto):
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")


def registrar_correccion_inductiva(audio_path, error_whisper, correccion_real):
    historial = cargar_json_seguro(REGISTRO_INDUCCION, {})
    historial[error_whisper.lower().strip()] = {
        "correcto": correccion_real.strip(),
        "audio_muestra": audio_path
    }
    guardar_json_seguro(REGISTRO_INDUCCION, historial, "🧠 Inducción de texto actualizada")


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


def buscar_en_web_duckduckgo(query):
    try:
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            from html.parser import HTMLParser
            class DDGParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.extract = False
                    self.results = []
                def handle_starttag(self, tag, attrs):
                    if tag == 'a' and any(attr[0] == 'class' and 'result__snippet' in attr[1] for attr in attrs):
                        self.extract = True
                def handle_data(self, data):
                    if self.extract:
                        self.results.append(data)
                        self.extract = False
            parser = DDGParser()
            parser.feed(res.text)
            return " | ".join(parser.results[:3]) if parser.results else "Sin resultados detallados en web."
    except Exception as e:
        print(f"⚠️ Error en búsqueda web: {e}")
    return ""


def procesar_evolucion_autonoma(prompt_usuario, archivo_objetivo="procesar.py", audio_referencia_path=None):
    global GEMINI_BLOQUEADO_POR_CUOTA
    
    perillas_actuales = cargar_json_seguro(ARCHIVO_PERILLAS, PERILLAS_DEFAULT)
    prosodia_actual = cargar_json_seguro(ARCHIVO_PROSODIA, PROSODIA_DEFAULT)
    
    # 1. Intentamos prioritariamente con Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        print(f"🧠 [Gemini Vibe Coding & Serie Armónica]: Analizando -> '{prompt_usuario}'")
        archivo_audio_subido = None
        try:
            if audio_referencia_path and os.path.exists(audio_referencia_path):
                archivo_audio_subido = client.files.upload(file=audio_referencia_path)

            prompt_perillas = "\n".join([
                "Sos el ingeniero acústico y director de prosodia de este agente autónomo.",
                f"Perillas cuantitativas y serie armónica actual (JSON): {json_lib.dumps(perillas_actuales)}",
                f"Parámetros de prosodia actuales (JSON): {json_lib.dumps(prosodia_actual)}",
                f"La orden de tu colega es: '{prompt_usuario}'.",
                "INSTRUCCIONES:",
                "1. Si el pedido afecta al audio, voz, fundamental Hz, serie armónica (enteros/decimales) o prosodia, actualizalos.",
                "2. Si NO es sobre audio, respondé exactamente 'NO_ES_AUDIO'.",
                "3. Devolvé OBLIGATORIAMENTE un bloque JSON con dos claves: `{\"perillas\": {...}, \"prosodia\": {...}}` entre ```json ... ``` y nada más."
            ])

            contents_param = [archivo_audio_subido, prompt_perillas] if archivo_audio_subido else [prompt_perillas]
            res_p = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=contents_param,
                config=genai.types.GenerateContentConfig(temperature=0.4)
            )
            texto_p = res_p.text.strip()
            
            if "NO_ES_AUDIO" not in texto_p:
                bloques_json = re.findall(r"```(?:json)?\s*(.*?)\s*```", texto_p, re.DOTALL)
                if bloques_json:
                    datos_nuevos = json_lib.loads(bloques_json[0])
                    if "perillas" in datos_nuevos:
                        guardar_json_seguro(ARCHIVO_PERILLAS, datos_nuevos["perillas"], "🎚️ Perillas actualizadas por Gemini")
                    if "prosodia" in datos_nuevos:
                        guardar_json_seguro(ARCHIVO_PROSODIA, datos_nuevos["prosodia"], "🎙️ Prosodia actualizada por Gemini")
                    return "Listo, che. Calibré perillas y prosodia por Gemini."
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print("⚠️ Cuota Gemini 429. Activando bypass local con web y muestras.")
                GEMINI_BLOQUEADO_POR_CUOTA = True
            else:
                print(f"⚠️ Aviso en análisis Gemini: {e}")
        finally:
            if archivo_audio_subido:
                try:
                    client.files.delete(name=archivo_audio_subido.name)
                except:
                    pass

    # 2. Fallback / Motor local Ollama (Llama 3.2) con búsqueda web y muestras
    print(f"🦙 [Motor Local Llama con Web & Muestras]: Analizando solicitud -> '{prompt_usuario}'")
    info_web = ""
    if any(k in prompt_usuario.lower() for k in ["busca", "imitá", "como", "estilo", "orador", "periodista", "persona", "arquetipo"]):
        info_web = buscar_en_web_duckduckgo(prompt_usuario)

    system_local = (
        "Sos el ingeniero de sonido, acústica y prosodia de este agente autónomo.\n"
        f"Perillas actuales JSON: {json_lib.dumps(perillas_actuales)}\n"
        f"Prosodia actual JSON: {json_lib.dumps(prosodia_actual)}\n"
        f"Contexto de búsqueda web sobre la muestra o arquetipo pedido: {info_web}\n"
        "INSTRUCCIONES:\n"
        "1. Si la orden es sobre audio, voz, timbre, armónicos o imitación de muestras/arquetipos/personas, adaptá inteligentemente los valores numéricos y la serie armónica (con multiplicadores decimales).\n"
        "2. Devolvé OBLIGATORIAMENTE un JSON válido con perillas y prosodia en este formato exacto:\n"
        "```json\n{\"perillas\": {...}, \"prosodia\": {...}}\n```\n"
        "Si NO es sobre audio, respondé exactamente la palabra 'NO_ES_AUDIO'."
    )

    payload = {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": system_local},
            {"role": "user", "content": prompt_usuario}
        ],
        "options": {"num_ctx": 16384, "temperature": 0.3},
        "stream": False,
    }
    try:
        res = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=300)
        if res.status_code == 200:
            texto_local = res.json().get("message", {}).get("content", "").strip()
            if "NO_ES_AUDIO" not in texto_local:
                bloques_json = re.findall(r"```(?:json)?\s*(.*?)\s*```", texto_local, re.DOTALL)
                if bloques_json:
                    datos_nuevos = json_lib.loads(bloques_json[0])
                    if "perillas" in datos_nuevos:
                        guardar_json_seguro(ARCHIVO_PERILLAS, datos_nuevos["perillas"], "🎚️ Perillas actualizadas por Llama local con web")
                    if "prosodia" in datos_nuevos:
                        guardar_json_seguro(ARCHIVO_PROSODIA, datos_nuevos["prosodia"], "🎙️ Prosodia actualizada por Llama local")
                    return "Listo, che. Analicé la muestra/arquetipo por web y motor local, ajustando perillas y prosodia."
    except Exception as e:
        print(f"⚠️ Error en motor local para perillas: {e}")

    return None


def llamar_ia_externa_o_local(prompt_usuario, audio_ref=None):
    global GEMINI_BLOQUEADO_POR_CUOTA
    respuesta_evolucion = procesar_evolucion_autonoma(prompt_usuario, audio_referencia_path=audio_ref)
    if respuesta_evolucion:
        return respuesta_evolucion

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram.\n"
        "REGLAS ABSOLUTAS:\n"
        "1. CERO INTRODUCCIONES DE ROBOT: Prohibido arrancar con 'Entiendo que', ni explicaciones técnicas.\n"
        "2. CERO REPETICIONES AUTOMÁTICAS: No uses latiguillos vacíos ni repitas frases hechas.\n"
        "3. TONO PORTEÑO NATURAL: Hablá al pie, directo, usando 'vos', 'che', 'fijate'.\n"
        "4. BREVEDAD: Al hueso, sin vueltas."
    )

    respuesta_final = ""
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            archivo_historial = None
            if os.path.exists(TXT_FILE) and os.path.getsize(TXT_FILE) > 0:
                archivo_historial = client.files.upload(file=TXT_FILE)

            contents_param = [archivo_historial, f"Historial adjunto.\nMi colega dice: \"{prompt_usuario}\"\nRespondé de forma directa."] if archivo_historial else f"Mi colega dice: \"{prompt_usuario}\"\nRespondé de forma directa."

            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=contents_param,
                config=genai.types.GenerateContentConfig(system_instruction=system_prompt)
            )
            if response and response.text:
                respuesta_final = response.text.strip()
            if archivo_historial:
                try:
                    client.files.delete(name=archivo_historial.name)
                except:
                    pass
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print("⚠️ Cuota Gemini 429 en chat. Cambiando a Llama local con Web.")
                GEMINI_BLOQUEADO_POR_CUOTA = True

    # Fallback o uso directo de Llama local con búsqueda web integrada
    if not respuesta_final:
        info_web = buscar_en_web_duckduckgo(prompt_usuario)
        prompt_con_web = f"{prompt_usuario}\n[Información web de referencia: {info_web}]" if info_web else prompt_usuario
        
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_con_web}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.3},
            "stream": False,
        }
        try:
            res = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=300)
            if res.status_code == 200:
                respuesta_final = res.json().get("message", {}).get("content", "").strip()
        except:
            pass

    if not respuesta_final:
        respuesta_final = "Che, me quedé sin conexión, tirámela de nuevo."
    else:
        registrar_refinamiento_ia(prompt_usuario, respuesta_final)

    return respuesta_final


def responder_usuario(orden, audio_ref=None):
    if not orden or not orden.strip():
        return "Che, no te entendí nada, tirámela de nuevo."
    respuesta = llamar_ia_externa_o_local(orden, audio_ref=audio_ref)
    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con prioridad en Gemini, bypass 429 y motor local potenciado (Web + Muestras + Serie armónica decimal).")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    texto_usuario = update.message.text
    print(f"📩 Mensaje recibido: {texto_usuario}")
    
    if ULTIMO_AUDIO_PENDIENTE["path"] and ULTIMO_AUDIO_PENDIENTE["crudo"] and texto_usuario.lower().startswith(("corregir:", "corrección:")):
        audio_p = ULTIMO_AUDIO_PENDIENTE["path"]
        crudo_p = ULTIMO_AUDIO_PENDIENTE["crudo"]
        correccion_real = re.sub(r'^(corregir:|corrección:)\s*', '', texto_usuario, flags=re.I).strip()
        registrar_correccion_inductiva(audio_p, crudo_p, correccion_real)
        ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}
        await update.message.reply_text("Listo, che. Inducción guardada.")
        return

    if ULTIMO_AUDIO_PENDIENTE["path"]:
        ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}

    await update.message.chat.send_action(action="typing")
    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    async with lock_voz:
        print("🎤 Procesando audio, web y serie armónica...")
        await update.message.chat.send_action(action="record_voice")

        message_id = update.message.message_id
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""

        try:
            archivo_telegram = await update.message.voice.get_file()
            audio_filename = f"audio_{message_id}.ogg"
            audio_path = os.path.join(CARPETA_MUESTRAS, audio_filename)
            await archivo_telegram.download_to_drive(audio_path)

            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path, beam_size=5, language="es")
            texto_crudo = " ".join([segment.text for segment in segments]).strip()
            
            ULTIMO_AUDIO_PENDIENTE["path"] = audio_path
            ULTIMO_AUDIO_PENDIENTE["crudo"] = texto_crudo

            texto_reconocido = cotejar_y_corregir_induccion(texto_crudo)

            if not texto_reconocido:
                await update.message.reply_text("Che, no te capté bien el audio, ¿me lo repetís?")
                return

            respuesta = responder_usuario(texto_reconocido, audio_ref=audio_path)

            texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
            texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

            tts = gTTS(text=texto_limpio, lang="es", tld="com.ar")
            tts.save(ruta_respuesta_mp3)

            p = cargar_json_seguro(ARCHIVO_PERILLAS, PERILLAS_DEFAULT)
            prosodia = cargar_json_seguro(ARCHIVO_PROSODIA, PROSODIA_DEFAULT)
            
            pitch_factor = float(p.get("pitch_factor", 0.80))
            tempo_base = float(p.get("tempo_factor", 1.20))
            tempo_factor = tempo_base * float(prosodia.get("factor_ritmo_variable", 1.0))
            
            fund = float(p.get("fundamental_hz", 130))
            serie_armonica = p.get("serie_armonica", [])
            
            treble_gain = float(p.get("treble_gain", 3.0))
            treble_freq = float(p.get("treble_freq", 4000))
            bass_gain = float(p.get("bass_gain", 5.0))
            bass_freq = float(p.get("bass_freq", 150))
            volume_mult = float(p.get("volume_mult", 1.1))

            filtros_lista = [
                f"atempo={max(0.5, min(2.0, tempo_factor))}",
                f"asetrate=24000*{max(0.4, min(2.0, pitch_factor))}"
            ]

            # Parser ultra robusto (diccionarios, listas, tuplas o números)
            for item in serie_armonica:
                try:
                    mult = 1.0
                    db = 0.0
                    
                    if isinstance(item, dict):
                        mult = float(item.get("multiplicador", item.get("mult", 1.0)))
                        db = float(item.get("gain_db", item.get("gain", item.get("db", 0.0))))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        mult = float(item[0])
                        db = float(item[1])
                    elif isinstance(item, (int, float)):
                        mult = float(item)
                        db = 0.0

                    freq_armonica = fund * mult
                    if 20.0 <= freq_armonica <= 11000.0:
                        w_val = max(15, int(freq_armonica * 0.08))
                        filtros_lista.append(f"equalizer=f={freq_armonica:.2f}:t=h:w={w_val}:g={db}")
                except Exception as ex_arm:
                    print(f"⚠️ Armónico ignorado por formato inválido: {ex_arm}")

            filtros_lista.extend([
                f"equalizer=f={treble_freq}:t=h:w=200:g={treble_gain}",
                f"equalizer=f={bass_freq}:t=h:w=100:g={bass_gain}",
                f"volume={volume_mult}",
                "dynaudnorm=f=150:g=15"
            ])

            filtro_audio = ",".join(filtros_lista)

            try:
                subprocess.run([
                    "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                    "-filter:a", filtro_audio,
                    "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
                    ruta_respuesta_ogg
                ], check=True)
            except:
                subprocess.run([
                    "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                    "-filter:a", f"atempo={tempo_factor},volume={volume_mult}",
                    "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
                    ruta_respuesta_ogg
                ], check=True)

            caption_est = f"-Interpretado: {texto_crudo}\n*(Procesado con serie armónica dinámica robusta)*"

            with open(ruta_respuesta_ogg, "rb") as voice_file:
                await update.message.reply_voice(voice=voice_file, caption=caption_est)

            print("✅ Nota de voz procesada con éxito.")

        except Exception as e:
            print(f"⚠️ Error general en audio: {e}")
            await update.message.reply_text("Che, se me armó un lío procesando el audio.")

        finally:
            for archivo in [ruta_respuesta_mp3, ruta_respuesta_ogg]:
                if os.path.exists(archivo):
                    try:
                        os.remove(archivo)
                    except:
                        pass


def main():
    inicializar_directorios_control("procesar.py")

    if not TOKEN:
        print("❌ ERROR: Falta token.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
        print("🧹 Webhook limpio.")
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")

    print("🚀 Iniciando bot con Híbrido Gemini / Llama Local (Web + Muestras + Serie Armónica Robusta)...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
