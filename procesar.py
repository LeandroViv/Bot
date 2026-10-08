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
CARPETA_MUESTRAS = "muestras_voz"
CARPETA_ORIGINALES = "originales"
CARPETA_RECURSIVA = "evolucion_recursiva"

# Aseguramos directorios base
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)
os.makedirs(CARPETA_ORIGINALES, exist_ok=True)
os.makedirs(CARPETA_RECURSIVA, exist_ok=True)

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

lock_voz = asyncio.Lock()
ULTIMO_AUDIO_PENDIENTE = {"path": None, "crudo": None}


def inicializar_directorios_control(archivo_actual="procesar.py"):
    """
    1. 'originales/': Guarda el snapshot inalterable base (se hace una sola vez).
    2. 'evolucion_recursiva/': Espeja y actualiza la versión viva actual de la raíz.
    """
    try:
        path_original = os.path.join(CARPETA_ORIGINALES, archivo_actual)
        if os.path.exists(archivo_actual) and not os.path.exists(path_original):
            shutil.copy(archivo_actual, path_original)
            print(f"🛡️ [Directorio Originales]: Snapshot base sellado en {path_original}")

        path_recursivo = os.path.join(CARPETA_RECURSIVA, archivo_actual)
        if os.path.exists(archivo_actual):
            shutil.copy(archivo_actual, path_recursivo)
            print(f"🔄 [Directorio Recursivo]: Respaldo actualizado desde la raíz.")
    except Exception as e:
        print(f"⚠️ Error en control de directorios: {e}")


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


def procesar_evolucion_autonoma(prompt_usuario, archivo_objetivo="procesar.py"):
    """
    Vibe coding directo sobre la raíz con recarga en caliente.
    """
    if not client:
        return None

    print(f"🧠 [Vibe Coding Directo en Raíz]: Analizando contexto profundo para -> {archivo_objetivo}")

    if not os.path.exists(archivo_objetivo):
        return None

    archivo_subido_ia = None
    archivo_historial_ia = None
    try:
        archivo_subido_ia = client.files.upload(file=archivo_objetivo)
        
        if os.path.exists(TXT_FILE) and os.path.getsize(TXT_FILE) > 0:
            archivo_historial_ia = client.files.upload(file=TXT_FILE)

        prompt_ia = (
            "Sos el núcleo de un agente autónomo de vibe coding con memoria contextual profunda.\n"
            "Se adjunta el código fuente actual de la raíz y el historial completo.\n"
            f"La orden actual de tu colega es: '{prompt_usuario}'.\n"
            "INSTRUCCIONES CRÍTICAS:\n"
            "1. Analizá todo el historial hacia atrás para comprender los ajustes de voz, tono, ritmo o perillas pedidos.\n"
            "2. Si la orden implica modificar código, devolvé OBLIGATORIAMENTE el bloque de código completo modificado dentro de ```python ... ```.\n"
            "3. Modificá y sobrescribí UNICAMENTE el archivo principal en la raíz (procesar.py). Prohibido crear archivos paralelos.\n"
            "4. Asegurate de que los parámetros de FFmpeg o lógica de voz sean dinámicos y adaptables según los pedidos.\n"
            "5. Si es solo charla, respondé al hueso en tono porteño natural."
        )

        contents_param = [archivo_subido_ia, archivo_historial_ia, prompt_ia] if archivo_historial_ia else [archivo_subido_ia, prompt_ia]

        res = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=contents_param,
            config=genai.types.GenerateContentConfig(
                temperature=0.3
            )
        )
        
        texto_generado = res.text.strip()
        bloques_codigo = re.findall(r"```(?:python|json|env|yaml)?\s*(.*?)\s*```", texto_generado, re.DOTALL)
        
        if bloques_codigo:
            nuevo_contenido = "\n".join(bloques_codigo)
            if len(nuevo_contenido) > 50:
                with open(archivo_objetivo, "w", encoding="utf-8") as f:
                    f.write(nuevo_contenido)
                
                inicializar_directorios_control(archivo_objetivo)
                sincronizar_con_github(f"🤖 Vibe coding autónomo: actualización directa en raíz de {archivo_objetivo}")
                
                print("🔄 [Vibe Coding]: Reiniciando proceso en caliente para aplicar los cambios al instante...")
                os.execv(sys.executable, ['python'] + sys.argv)
                
                return f"Listo, che. Actualicé la raíz y me reinicié en caliente."

        return texto_generado

    except Exception as e:
        print(f"⚠️ Error en vibe coding directo: {e}")
        return None
        
    finally:
        for arch in [archivo_subido_ia, archivo_historial_ia]:
            if arch:
                try:
                    client.files.delete(name=arch.name)
                except:
                    pass


def llamar_ia_externa_o_local(prompt_usuario):
    respuesta_evolucion = procesar_evolucion_autonoma(prompt_usuario)
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
    if client:
        try:
            archivo_historial = None
            if os.path.exists(TXT_FILE) and os.path.getsize(TXT_FILE) > 0:
                archivo_historial = client.files.upload(file=TXT_FILE)

            contents_param = [archivo_historial, f"Historial completo de nuestra charla adjunto.\nMi colega me dice:\n\"{prompt_usuario}\"\n\nRespondé de forma directa considerando todo el contexto."] if archivo_historial else f"Mi colega me dice:\n\"{prompt_usuario}\"\n\nRespondé de forma directa."

            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=contents_param,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt
                )
            )
            if response and response.text:
                respuesta_final = response.text.strip()
                
            if archivo_historial:
                try:
                    client.files.delete(name=archivo_historial.name)
                except:
                    pass
        except Exception as e:
            print(f"⚠️ Gemini falló: {e}")

    if not respuesta_final:
        url = "http://127.0.0.1:11434/api/chat"
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.3},
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
    await update.message.reply_text("¡Buenas che! Bot activo con vibe coding directo, recarga en caliente y perillas de voz totalmente dinámicas.")


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

            # Perillas de voz abiertas y completamente dinámicas según el vibe de la charla
            prompt_lower = texto_reconocido.lower()
            
            # Factores base totalmente adaptables
            pitch_factor = 0.80  
            tempo_factor = 1.02  

            if any(k in prompt_lower for k in ["más grave", "mas grave", "voz grave", "grave", "profunda"]):
                pitch_factor = 0.65
            elif any(k in prompt_lower for k in ["más agudo", "mas agudo", "agudo"]):
                pitch_factor = 0.95

            if any(k in prompt_lower for k in ["más rápido", "mas rápido", "rápido", "acelerado", "ritmo"]):
                tempo_factor = 1.20
            elif any(k in prompt_lower for k in ["más lento", "mas lento", "lento", "pausado"]):
                tempo_factor = 0.90

            print(f"🎚️ [FFmpeg Dinámico Abierto]: Pitch -> {pitch_factor} | Tempo -> {tempo_factor}")

            subprocess.run([
                "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                "-filter:a", f"atempo={tempo_factor},asetrate=24000*{pitch_factor},dynaudnorm=f=150:g=15",
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
    inicializar_directorios_control("procesar.py")

    if not TOKEN:
        print("❌ ERROR: Falta token.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
        print("🧹 Webhook limpio.")
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")

    print("🚀 Iniciando bot con Vibe Coding directo, recarga en caliente y perillas dinámicas...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
