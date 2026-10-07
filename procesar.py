import asyncio
json_lib = __import__('json')
import os
import re
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
CARPETA_MUESTRAS = "muestras_voz"

# Aseguramos directorios y archivos base
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)
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

# Inicialización con el cliente oficial google.genai
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

lock_voz = asyncio.Lock()
ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}


def sincronizar_con_github(mensaje_commit="🤖 Sincronización evolutiva y de código"):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        
        subprocess.run(["git", "add", "."], check=True)
        
        resultado = subprocess.run(["git", "commit", "-m", mensaje_commit], capture_output=True, text=True)
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ Sincronizado y pusheado con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ Aviso de git (no crítico): {e}")


def guardar_en_txt(rol, texto):
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")
    sincronizar_con_github()


# ==========================================
# GESTIÓN DE HISTORIALES Y EVOLUCIÓN AUTÓNOMA
# ==========================================
def cargar_json(path, tipo_defecto):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json_lib.load(f)
            except:
                return tipo_defecto
    return tipo_defecto


def registrar_correccion_inductiva(audio_path, error_whisper, correccion_real):
    historial = cargar_json(REGISTRO_INDUCCION, {})
    historial[error_whisper.lower().strip()] = {
        "correcto": correccion_real.strip(),
        "audio_muestra": audio_path
    }
    with open(REGISTRO_INDUCCION, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)
    print(f"🧠 [Inducción Registrada]: '{error_whisper}' -> '{correccion_real}'")
    sincronizar_con_github()


def registrar_refinamiento_ia(prompt_usuario, respuesta_generada):
    refinamientos = cargar_json(REGISTRO_REFINAMIENTO, [])
    registro_nuevo = {
        "entrada_usuario": prompt_usuario,
        "respuesta_ia": respuesta_generada,
        "estado": "refinado_por_api"
    }
    refinamientos.append(registro_nuevo)
    if len(refinamientos) > 100:
        refinamientos = refinamientos[-100:]
        
    with open(REGISTRO_REFINAMIENTO, "w", encoding="utf-8") as f:
        json_lib.dump(refinamientos, f, indent=4, ensure_ascii=False)
    print("💡 [Refinamiento IA Registrado]")
    sincronizar_con_github()


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


def procesar_evolucion_codigo(prompt_usuario, archivo_base="procesar.py"):
    """
    Detecta de forma flexible si le pedís modificar código, lee el archivo actual, 
    se lo envía a Gemini (3.5-flash) y sube el resultado al repo.
    """
    prompt_lower = prompt_usuario.lower()
    tiene_intencion = any(k in prompt_lower for k in ["modificar", "modif", "cambiar", "cambiam", "actualiz"]) and any(k in prompt_lower for k in ["codigo", "código", "script", "tts", "funcion", "función"])
    
    if not tiene_intencion:
        return None

    print("🛠️ [Autonomía Activada]: Detectada orden de modificar código en la conversación.")

    contenido_actual = ""
    if os.path.exists(archivo_base):
        with open(archivo_base, "r", encoding="utf-8") as f:
            contenido_actual = f.read()
    else:
        return f"Che, no encontré el archivo base '{archivo_base}' en el repositorio."

    nombre, ext = os.path.splitext(archivo_base)
    archivo_objetivo = f"{nombre}_modificado{ext}"

    prompt_ia = (
        f"Sos un motor experto de programación autónomo.\n"
        f"Tu objetivo es modificar el archivo '{archivo_base}' basándote en esta solicitud: '{prompt_usuario}'.\n"
        f"CONTENIDO ACTUAL DEL ARCHIVO:\n```python\n{contenido_actual}\n```\n\n"
        f"REGLA CRÍTICA: Devolvé ÚNICAMENTE el código completo corregido/modificado encerrado "
        f"en un bloque markdown ```python ... ```. Sin explicaciones ni texto por fuera."
    )

    try:
        if not client:
            return "Che, el cliente de Gemini no está inicializado."

        res = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt_ia,
        )
        texto_generado = res.text.strip()
        
        match = re.search(r"```(?:python)?\s*(.*?)\s*```", texto_generado, re.DOTALL)
        if match:
            nuevo_contenido = match.group(1)
        else:
            nuevo_contenido = texto_generado

        if len(nuevo_contenido) < 100:
            return "Che, la IA devolvió un código demasiado corto o vacío, aborté la modificación."

        with open(archivo_objetivo, "w", encoding="utf-8") as f:
            f.write(nuevo_contenido)
        print(f"✅ Archivo corregido guardado localmente: {archivo_objetivo}")

        sincronizar_con_github(f"🤖 Evolución autónoma: modificación de {archivo_base} generada por IA")

        return f"Listo, che. Analicé el archivo, apliqué la modificación y ya subí el archivo '{archivo_objetivo}' al repositorio."

    except Exception as e:
        print(f"⚠️ Error en la evolución de código: {e}")
        return f"Che, falló el proceso de modificación autónoma: {e}"


def llamar_ia_externa_o_local(prompt_usuario):
    # 1. Chequeo prioritario de evolución de código
    respuesta_evolucion = procesar_evolucion_codigo(prompt_usuario)
    if respuesta_evolucion:
        return respuesta_evolucion

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram.\n"
        "REGLAS ABSOLUTAS:\n"
        "1. CERO INTRODUCCIONES DE ROBOT: Prohibido arrancar con 'Entiendo que', ni explicaciones técnicas.\n"
        "2. CERO REPETICIONES AUTOMÁTICAS: No uses latiguillos vacíos ni repitas '¿qué onda?' si te tiran una orden o comentario puntual.\n"
        "3. TONO PORTEÑO NATURAL: Hablá al pie, directo, usando 'vos', 'che', 'fijate'.\n"
        "4. BREVEDAD: Al hueso, sin vueltas."
    )

    # 2. Decisión inteligente: interpretar directo con la API y solo adjuntar el TXT si el mensaje requiere contexto histórico
    necesita_historial = any(k in prompt_usuario.lower() for k in ["anterior", "acordás", "historial", "charla", "conversación", "visto", "habíamos"])

    respuesta_final = ""
    if client:
        try:
            archivo_subido = None
            if necesita_historial and os.path.exists(TXT_FILE) and os.path.getsize(TXT_FILE) > 0:
                print("📁 [Contexto]: Adjuntando historial de conversaciones porque fue requerido.")
                archivo_subido = client.files.upload(file=TXT_FILE)

            contents_param = [archivo_subido, f"Mi colega me dice:\n\"{prompt_usuario}\"\n\nRespondé de forma directa."] if archivo_subido else f"Mi colega me dice:\n\"{prompt_usuario}\"\n\nRespondé de forma directa."

            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=contents_param,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt
                )
            )
            if response and response.text:
                respuesta_final = response.text.strip()
                
            if archivo_subido:
                try:
                    client.files.delete(name=archivo_subido.name)
                except:
                    pass
        except Exception as e:
            print(f"⚠️ Gemini falló: {e}")

    # Fallback local con Ollama si la API de Gemini no responde
    if not respuesta_final:
        url = "http://127.0.0.1:11434/api/chat"
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.2},
            "stream": False,
        }
        try:
            res = requests.post(url, json=payload, timeout=300)
            if res.status_code == 200:
                respuesta_final = res.json().get("message", {}).get("content", "").strip()
        except:
            pass

    if not respuesta_final:
        respuesta_final = "Che, me quedé sin conexión, tirámela de nuevo."
    else:
        registrar_refinamiento_ia(prompt_usuario, respuesta_final)

    return respuesta_final


def responder_usuario(orden):
    if not orden or not orden.strip():
        return "Che, no te entendí nada, tirámela de nuevo."
    respuesta = llamar_ia_externa_o_local(orden)
    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    return respuesta


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con modelo gemini-3.5-flash y evolución autónoma optimizada.")


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
        
        await update.message.reply_text("Listo, che. Inducción guardada y asociada al archivo .ogg físico.")
        return

    if ULTIMO_AUDIO_PENDIENTE["path"]:
        ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}

    await update.message.chat.send_action(action="typing")
    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    async with lock_voz:
        print("🎤 Procesando audio...")
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
            print(f"🎙️ Audio guardado físicamente en: {audio_path}")

            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path, beam_size=5, language="es")
            texto_crudo = " ".join([segment.text for segment in segments]).strip()
            
            print(f"🗣️ Whisper crudo: {texto_crudo}")

            ULTIMO_AUDIO_PENDIENTE["path"] = audio_path
            ULTIMO_AUDIO_PENDIENTE["crudo"] = texto_crudo

            texto_reconocido = cotejar_y_corregir_induccion(texto_crudo)

            if not texto_reconocido:
                await update.message.reply_text("Che, no te capté bien el audio, ¿me lo repetís?")
                return

            respuesta = responder_usuario(texto_reconocido)

            texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', respuesta)
            texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio).strip()

            tts = gTTS(text=texto_limpio, lang="es", tld="com.ar")
            tts.save(ruta_respuesta_mp3)

            subprocess.run([
                "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                "-filter:a", "atempo=1.03,dynaudnorm=f=150:g=15",
                "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
                ruta_respuesta_ogg
            ], check=True)

            caption_estructurado = (
                f"-Lo que interpretaste: {texto_crudo}\n"
                f"-Lo que dije: (Respondé con 'corregir: [texto]' si difiere)\n"
                f"*(Procesado: \"{texto_reconocido}\")*"
            )

            with open(ruta_respuesta_ogg, "rb") as voice_file:
                await update.message.reply_voice(
                    voice=voice_file, 
                    caption=caption_estructurado
                )

            print("✅ Nota de voz procesada con éxito.")

        except Exception as e:
            print(f"⚠️ Error en audio: {e}")
            await update.message.reply_text("Che, se me armó un lío procesando el audio.")

        finally:
            for archivo in [ruta_respuesta_mp3, ruta_respuesta_ogg]:
                if os.path.exists(archivo):
                    try:
                        os.remove(archivo)
                    except:
                        pass


def main():
    if not TOKEN:
        print("❌ ERROR: Falta token.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
        print("🧹 Webhook limpio.")
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")

    print("🚀 Iniciando bot con gemini-3.5-flash y lógica optimizada...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
