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
import google.generativeai as genai
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

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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
# GESTIÓN DE HISTORIALES Y AUTOGENERACIÓN MULTI-ARCHIVO
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


def intentar_autogenerar_codigo(prompt_usuario):
    """Genera un archivo alternativo de código en base al pedido, sin pisar el original."""
    print("🛠️ [Autogeneración de archivo alternativo detectada]: Analizando solicitud...")

    archivos_en_repo = [f for f in os.listdir(".") if os.path.isfile(f)]
    archivo_base = "procesar.py"

    for arch in archivos_en_repo:
        if arch.lower() in prompt_usuario.lower():
            archivo_base = arch
            break

    print(f"📂 Archivo base de referencia: {archivo_base}")

    contenido_actual = ""
    if os.path.exists(archivo_base):
        with open(archivo_base, "r", encoding="utf-8") as f:
            contenido_actual = f.read()

    # Generamos un nombre alternativo para no pisar el original (ej: procesar_modificado.py)
    nombre, ext = os.path.splitext(archivo_base)
    archivo_objetivo = f"{nombre}_modificado{ext}"

    extension = ext.lstrip('.')
    lang_tag = extension if extension else "python"

    prompt_codigo = (
        f"ESTÁS AUTORIZADO Y ES TU OBLIGACIÓN. Sos un motor experto de programación en este repositorio.\n"
        f"Tu colega te pide que crees una versión modificada del archivo '{archivo_base}' basada en esta directiva: '{prompt_usuario}'.\n"
        f"CONTENIDO ACTUAL DE {archivo_base}:\n```{lang_tag}\n{contenido_actual}\n```\n\n"
        f"REGLA CRÍTICA: Escribí el código completo adaptado y DEVUELVE ÚNICAMENTE EL CÓDIGO NUEVO encerrado "
        f"en bloques markdown ```{lang_tag} ... ```. No pongas excusas ni explicaciones fuera del bloque."
    )

    try:
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        res = model.generate_content(prompt_codigo)
        texto_generado = res.text.strip()
        
        match = re.search(r"```(?:\w+)?\s*(.*?)\s*```", texto_generado, re.DOTALL)
        if match:
            nuevo_contenido = match.group(1)
            # Guardamos en el archivo alternativo, dejando el original intacto
            with open(archivo_objetivo, "w", encoding="utf-8") as f:
                f.write(nuevo_contenido)
            print(f"✅ [Generación Exitosa]: Archivo alternativo creado -> {archivo_objetivo}")
            
            try:
                sincronizar_con_github(f"🛠️ Creación de archivo alternativo {archivo_objetivo} por IA")
                return f"Che, te armé y subí un archivo alternativo llamado '{archivo_objetivo}' con los cambios para que lo revises sin tocar el original."
            except Exception as git_err:
                return f"Che, creé el archivo local '{archivo_objetivo}', pero falló el push a GitHub: {git_err}"
        else:
            return None
            
    except Exception as e:
        print(f"⚠️ Error en autogeneración de código alternativo: {e}")
        
    return None


def llamar_ia_externa_o_local(prompt_usuario):
    respuesta_codigo = intentar_autogenerar_codigo(prompt_usuario)
    if respuesta_codigo:
        return respuesta_codigo

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram.\n"
        "REGLAS ABSOLUTAS:\n"
        "1. CERO INTRODUCCIONES DE ROBOT: Prohibido arrancar con 'Entiendo que', 'Claro que sí', ni explicaciones técnicas.\n"
        "2. CONTEXTO DE CHARLA ABSOLUTO: Tenés adjunto el historial completo de conversaciones. Analizalo para mantener coherencia total.\n"
        "3. TONO PORTEÑO NATURAL: Hablá al pie, directo, usando 'vos', 'che', 'fijate'.\n"
        "4. BREVEDAD: Al hueso, sin vueltas."
    )

    respuesta_final = ""
    if GEMINI_API_KEY:
        try:
            archivo_adjunto = None
            if os.path.exists(TXT_FILE) and os.path.getsize(TXT_FILE) > 0:
                archivo_adjunto = genai.upload_file(TXT_FILE, mime_type="text/plain")

            model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=system_prompt)
            
            contenido_request = [archivo_adjunto, f"Mi colega me dice:\n\"{prompt_usuario}\"\n\nRespondé de forma directa."] if archivo_adjunto else f"Mi colega me dice:\n\"{prompt_usuario}\"\n\nRespondé de forma directa."
            
            response = model.generate_content(contenido_request)
            if response and response.text:
                respuesta_final = response.text.strip()
                
            if archivo_adjunto:
                try:
                    genai.delete_file(archivo_adjunto.name)
                except:
                    pass
        except Exception as e:
            print(f"⚠️ Gemini con archivo adjunto falló: {e}")

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
    await update.message.reply_text("¡Buenas che! Bot activo con contexto de archivo adjunto y autogeneración segura de archivos alternativos.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ULTIMO_AUDIO_PENDIENTE
    texto_usuario = update.message.text
    print(f"📩 Mensaje recibido: {texto_usuario}")
    
    if ULTIMO_AUDIO_PENDIENTE["path"] and ULTIMO_AUDIO_PENDIENTE["crudo"]:
        audio_p = ULTIMO_AUDIO_PENDIENTE["path"]
        crudo_p = ULTIMO_AUDIO_PENDIENTE["crudo"]
        
        registrar_correccion_inductiva(audio_p, crudo_p, texto_usuario)
        ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}
        
        await update.message.reply_text("Listo, che. Inducción guardada y asociada al archivo .ogg físico.")
        return

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
                f"-Lo que dije: (Respondé con la corrección si difiere)\n"
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
                    export_ex = None
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

    print("🚀 Iniciando bot con adjunto de conversaciones.txt y autogeneración segura...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
