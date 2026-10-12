import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
import urllib.request
import numpy as np
from datetime import datetime

print("🚀 [INIT]: Inicializando sistema híbrido definitivo (Blindaje contra TypeError + Canales separados + Audio optimizado)...")

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

try:
    from transformers import AutoProcessor, BarkModel
    import torch
    import soundfile as sf
    BARK_DISPONIBLE = True
    print("✅ [INIT]: Motor de timbre Bark disponible.")
except ImportError:
    BARK_DISPONIBLE = False
    print("⚠️ [INIT]: Bark no disponible.")

try:
    from google import genai
    GENAI_DISPONIBLE = True
    print("✅ [INIT]: Google GenAI disponible.")
except ImportError:
    GENAI_DISPONIBLE = False
    print("⚠️ [INIT]: Google GenAI NO disponible.")

TXT_FILE = "conversaciones.txt"
REGISTRO_METRICAS = "historial_metricas_voz.json"
MEMORIA_TAREAS = "memoria_tareas.json"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CARPETA_MUESTRAS = "muestras_voz"

os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

if not os.path.exists(TXT_FILE):
    with open(TXT_FILE, "w", encoding="utf-8") as f:
        f.write("--- HISTORIAL DE CONVERSACIONES ---\n")

if not os.path.exists(REGISTRO_METRICAS):
    with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

if not os.path.exists(MEMORIA_TAREAS):
    with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

if not os.path.exists(DATASET_ENTRENAMIENTO):
    with open(DATASET_ENTRENAMIENTO, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

client = genai.Client(api_key=GEMINI_API_KEY) if (GENAI_DISPONIBLE and GEMINI_API_KEY) else None
GEMINI_BLOQUEADO_POR_CUOTA = False
lock_voz = asyncio.Lock()


def registrar_conversacion(remitente, texto):
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {remitente}: {texto}\n")
            f.flush()
            os.fsync(f.fileno())
        print(f"📝 [TXT SYNC]: Mensaje de {remitente} guardado al instante.")
    except Exception as e:
        print(f"⚠️ Error escribiendo en conversaciones.txt: {e}")


def registrar_entrenamiento_chat(texto_usuario, texto_bot):
    try:
        with open(DATASET_ENTRENAMIENTO, "r", encoding="utf-8") as f:
            dataset = json_lib.load(f)
    except Exception:
        dataset = []

    nuevo_par = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "usuario": texto_usuario,
        "bot": texto_bot,
        "id_entrenamiento": len(dataset) + 1
    }
    dataset.append(nuevo_par)

    with open(DATASET_ENTRENAMIENTO, "w", encoding="utf-8") as f:
        json_lib.dump(dataset, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    print(f"🧠 [DATASET ENTRENAMIENTO]: Par #{nuevo_par['id_entrenamiento']} guardado en JSON.")


def registrar_entrenamiento_json(path_audio, texto_transcrito, partitura_aplicada, tipo="voz_usuario"):
    try:
        with open(REGISTRO_METRICAS, "r", encoding="utf-8") as f:
            historial = json_lib.load(f)
    except Exception:
        historial = []

    nuevo_registro = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tipo": tipo,
        "archivo": path_audio,
        "texto": texto_transcrito,
        "partitura_metrica": partitura_aplicada,
        "total_entrenamientos": len(historial) + 1
    }
    historial.append(nuevo_registro)
    
    with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
        json_lib.dump(historial, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        
    print(f"📒 [REGISTRO JSON CONTINUO]: Entrenamiento #{nuevo_registro['total_entrenamientos']} guardado con éxito.")


def registrar_tarea_pendiente(instruccion):
    try:
        with open(MEMORIA_TAREAS, "r", encoding="utf-8") as f:
            tareas = json_lib.load(f)
    except Exception:
        tareas = []
    
    tareas.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instruccion": instruccion,
        "pendiente": True
    })
    
    with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
        json_lib.dump(tareas, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    print(f"📝 [MEMORIA DE TAREAS]: Instrucción guardada: '{instruccion}'")


def generar_respuesta_y_partitura_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    respuesta_raw = ""
    
    system_prompt = (
        "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo.\n"
        "REGLA FONÉTICA Y LINGÜÍSTICA OBLIGATORIA: Escribí y respondé usando estrictamente el español rioplatense (porteño), "
        "utilizando el voseo natural ('vós sabés', 'vení', 'fijate', 'escuchá'), lunfardo sutil y la grafía o fonética "
        "que refleje la entonación de Buenos Aires (énfasis en imperativos agudos y cadencia porteña).\n"
        "INSTRUCCIÓN DE APRENDIZAJE CRÍTICA: Tenés adjuntos 'conversaciones.txt', 'dataset_entrenamiento_chat.json' y 'historial_metricas_voz.json'. "
        "Analizá detalladamente las interacciones previas para responder con el mismo tono y contexto exacto.\n\n"
        "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown tipo ```json, solo el JSON crudo):\n"
        "{\n"
        "  \"texto_completo\": \"Tu respuesta hablada aquí con acentuación porteña\",\n"
        "  \"partitura\": [\n"
        "    {\"palabra\": \"Che,\", \"duracion_ms\": 120, \"intensidad_db\": -1.0},\n"
        "    {\"palabra\": \"escuchá\", \"duracion_ms\": 250, \"intensidad_db\": 0.0}\n"
        "  ]\n"
        "}"
    )
    
    if client and not GEMINI_BLOQUEADO_POR_CUOTA and os.path.exists(REGISTRO_METRICAS):
        for intento in range(2):
            try:
                print("🤖 [IA]: Intentando conectar con Gemini analizando historial y dataset...")
                adjunto_metricas = client.files.upload(file=REGISTRO_METRICAS)
                adjunto_conversaciones = client.files.upload(file=TXT_FILE) if os.path.exists(TXT_FILE) else None
                adjunto_dataset = client.files.upload(file=DATASET_ENTRENAMIENTO) if os.path.exists(DATASET_ENTRENAMIENTO) else None
                
                contents_payload = [adjunto_metricas]
                if adjunto_conversaciones:
                    contents_payload.append(adjunto_conversaciones)
                if adjunto_dataset:
                    contents_payload.append(adjunto_dataset)
                contents_payload.append(f"Mensaje del oyente: \"{prompt_usuario}\"")

                res = client.models.generate_content(
                    model="gemini-3.8-flash",  # Modelo actualizado para evitar 404
                    contents=contents_payload,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json"
                    )
                )
                if res and res.text:
                    respuesta_raw = str(res.text).strip()
                    print("✅ [IA CONECTADA]: ¡Gemini respondió con éxito!")
                    break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    GEMINI_BLOQUEADO_POR_CUOTA = True
                    print("⚠️ [CUOTA EXCEDIDA]: Gemini bloqueado, derivando a Llama local...")
                    break
                elif "503" in str(e) and intento == 0:
                    print("⚠️ [503 UNAVAILABLE]: Reintentando en 2 segundos...")
                    time.sleep(2)
                else:
                    print(f"⚠️ Error con Gemini: {e}")
                    break

    if not respuesta_raw or GEMINI_BLOQUEADO_POR_CUOTA:
        print(f"🦙 [IA CONECTADA]: Intentando usar Llama local (Ollama) en {OLLAMA_HOST}...")
        
        historial_reciente = ""
        if os.path.exists(TXT_FILE):
            try:
                with open(TXT_FILE, "r", encoding="utf-8") as f:
                    lineas = f.readlines()
                    historial_reciente = "".join(lineas[-15:])
            except Exception:
                pass

        prompt_con_historial = f"Historial reciente:\n{historial_reciente}\nMensaje actual: {prompt_usuario}"
        
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_con_historial}
            ],
            "options": {"num_ctx": 16384, "temperature": 0.7},
            "stream": False,
        }
        try:
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            res_local = requests.post(url_llama, json=payload, timeout=30)
            if res_local.status_code == 200:
                respuesta_raw = str(res_local.json().get("message", {}).get("content", "")).strip()
        except Exception as ex_local:
            print(f"⚠️ Aviso: Llama local no disponible en el runner ({ex_local}).")

    if not isinstance(respuesta_raw, str):
        respuesta_raw = str(respuesta_raw or "")

    respuesta_raw = re.sub(r'^```json\s*', '', respuesta_raw, flags=re.IGNORECASE)
    respuesta_raw = re.sub(r'^```\s*', '', respuesta_raw)
    respuesta_raw = re.sub(r'\s*```$', '', respuesta_raw).strip()

    try:
        datos = json_lib.loads(respuesta_raw)
        texto = datos.get("texto_completo", "Che, todo bien por acá.")
        partitura = datos.get("partitura", [])
        if not partitura:
            raise ValueError("Partitura vacía")
        return texto, partitura
    except Exception as parse_err:
        print(f"⚠️ Error parseando JSON de la IA ({parse_err}). Respuesta cruda fue: {respuesta_raw}")
        if prompt_usuario and len(prompt_usuario) > 3:
            texto_fallback = f"Che, estuve analizando lo que tiraste sobre '{prompt_usuario[:30]}...', sintonizamos en un rato."
        else:
            texto_fallback = "Che, te capté perfectamente, acá estamos al firme con la frecuencia."
            
        partitura_fallback = [{"palabra": w, "duracion_ms": 180, "intensidad_db": -0.5} for w in texto_fallback.split()]
        return texto_fallback, partitura_fallback


def sintetizar_con_partitura_de_ia(texto, partitura, ogg_salida="resp.ogg"):
    wav_temp_timbre = "temp_timbre_bark.wav"
    wav_temp_final = "temp_dinamica_final.wav"
    sample_rate = 24000

    timbre_ok = False
    if BARK_DISPONIBLE:
        try:
            processor = AutoProcessor.from_pretrained("suno/bark-small")
            model = BarkModel.from_pretrained("suno/bark-small")
            device = "cpu"
            model = model.to(device)

            texto_corto = texto.strip()[:280]
            texto_para_bark = f"[es] {texto_corto}"
            inputs = processor(texto_para_bark, voice_preset="v2/es_speaker_2").to(device)
            
            with torch.no_grad():
                audio_bark = model.generate(**inputs)
            
            audio_bark = audio_bark.cpu().numpy().squeeze()
            if len(audio_bark) > 5000:
                sf.write(wav_temp_timbre, audio_bark, sample_rate)
                timbre_ok = os.path.exists(wav_temp_timbre)
        except Exception as e:
            print(f"⚠️ Error en timbre Bark: {e}")

    if not timbre_ok:
        print("⚠️ [FALLBACK TIMBRE]: Usando tono base seguro.")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=180:duration=3", wav_temp_timbre], check=True)

    try:
        data_timbre, sr = sf.read(wav_temp_timbre)
        if len(data_timbre.shape) > 1:
            data_timbre = np.mean(data_timbre, axis=1)

        max_val = np.max(np.abs(data_timbre))
        if max_val > 0:
            data_timbre = data_timbre / max_val

        audio_dinamico = np.array([], dtype=np.float32)
        if not partitura:
            partitura = [{"palabra": w, "duracion_ms": 200, "intensidad_db": 0.0} for w in texto.split()]

        for item in partitura:
            duracion_ms = item.get("duracion_ms", 200)
            duracion_ms = max(100, min(int(duracion_ms), 450))
            
            intensidad_db = item.get("intensidad_db", 0.0)
            intensidad_db_segura = max(min(float(intensidad_db), 2.0), -3.0)
            mult_vol = 10 ** (intensidad_db_segura / 20.0)

            muestras_bloque = int(sr * (duracion_ms / 1000.0))
            if len(data_timbre) >= muestras_bloque:
                start_idx = np.random.randint(0, len(data_timbre) - muestras_bloque)
                fragmento = data_timbre[start_idx : start_idx + muestras_bloque]
            else:
                fragmento = data_timbre

            audio_dinamico = np.concatenate((audio_dinamico, fragmento * mult_vol))

        if len(audio_dinamico) < sr * 0.5:
            audio_dinamico = data_timbre

        sf.write(wav_temp_final, audio_dinamico, sr)
    except Exception as e:
        print(f"⚠️ Error procesando partitura dinámica: {e}")
        subprocess.run(["cp", wav_temp_timbre, wav_temp_final], check=True)

    filtros = [
        "highpass=f=80",
        "lowpass=f=7600",
        "dynaudnorm=f=150:g=15:p=0.9",
        "volume=1.2"
    ]

    subprocess.run([
        "ffmpeg", "-y", "-i", wav_temp_final,
        "-filter:a", ",".join(filtros),
        "-c:a", "libopus", "-b:a", "64k", "-ar", "48000",
        ogg_salida
    ], check=True)

    for temp_f in [wav_temp_timbre, wav_temp_final]:
        if os.path.exists(temp_f):
            os.remove(temp_f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con canales separados y sincronización instantánea.")


async def corregir_transcripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Che, respondé al mensaje donde te mostré la transcripción para poder corregirlo.")
        return

    texto_corregido = " ".join(context.args).strip()
    if not texto_corregido:
        await update.message.reply_text("Pasame el texto correcto después del comando.")
        return

    try:
        with open(REGISTRO_METRICAS, "r", encoding="utf-8") as f:
            historial = json_lib.load(f)

        if historial:
            ultimo_registro = historial[-1]
            texto_anterior = ultimo_registro.get("texto", "")
            ultimo_registro["texto_whisper_original"] = texto_anterior
            ultimo_registro["texto"] = texto_corregido
            ultimo_registro["corregido_por_usuario"] = True

            with open(REGISTRO_METRICAS, "w", encoding="utf-8") as f:
                json_lib.dump(historial, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            try:
                subprocess.run(["git", "config", "--global", "user.name", "Bot de Telegram"], check=True)
                subprocess.run(["git", "config", "--global", "user.email", "bot@github.action"], check=True)
                subprocess.run(["git", "add", REGISTRO_METRICAS], check=True)
                subprocess.run(["git", "commit", "-m", f"✏️ Corrección registrada: {texto_corregido[:30]}..."], check=True)
                subprocess.run(["git", "push"], check=True)
            except Exception as e_git:
                print(f"⚠️ Error al pushear corrección: {e_git}")

            await update.message.reply_text(f"✅ ¡Entendido y aprendido!\n❌ *Whisper:* \"{texto_anterior}\"\n✅ *Real:* \"{texto_corregido}\"", parse_mode="Markdown")
        else:
            await update.message.reply_text("No encontré registros previos para corregir.")
    except Exception as e:
        print(f"⚠️ Error guardando corrección: {e}")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    registrar_conversacion("Usuario", texto_usuario)

    if "durante el día" in texto_usuario.lower() or "escribime" in texto_usuario.lower() or "recordá" in texto_usuario.lower():
        registrar_tarea_pendiente(texto_usuario)

    texto_limpio, partitura = generar_respuesta_y_partitura_ia(texto_usuario)
    registrar_conversacion("LeandroBot", texto_limpio)
    registrar_entrenamiento_chat(texto_usuario, texto_limpio)

    await update.message.reply_text(texto_limpio)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        
        path_ogg = os.path.join(CARPETA_MUESTRAS, f"audio_usuario_{update.message.message_id}.ogg")
        path_wav = os.path.join(CARPETA_MUESTRAS, f"audio_usuario_{update.message.message_id}.wav")
        
        await file.download_to_drive(path_ogg)

        try:
            subprocess.run(["ffmpeg", "-y", "-i", path_ogg, "-ar", "22050", "-ac", "1", path_wav], check=True)
        except Exception as e:
            print(f"⚠️ Error convirtiendo .ogg a .wav: {e}")

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_ogg, beam_size=5, language="es", word_timestamps=True)
        
        texto_crudo = ""
        partitura_real = []

        data_wav, sr_wav = sf.read(path_wav) if os.path.exists(path_wav) else (None, 22050)
        if data_wav is not None and len(data_wav.shape) > 1:
            data_wav = np.mean(data_wav, axis=1)

        rms_total = np.sqrt(np.mean(data_wav**2)) if (data_wav is not None and len(data_wav) > 0) else 0

        for segment in segments:
            texto_crudo += segment.text + " "
            if hasattr(segment, 'words') and segment.words:
                for w_info in segment.words:
                    palabra = w_info.word.strip()
                    inicio_ms = int(w_info.start * 1000)
                    fin_ms = int(w_info.end * 1000)
                    duracion_ms = max(50, fin_ms - inicio_ms)
                    
                    intensidad_db = 0.0
                    if data_wav is not None and len(data_wav) > 0 and rms_total > 0:
                        idx_ini = int(w_info.start * sr_wav)
                        idx_fin = int(w_info.end * sr_wav)
                        fragmento = data_wav[max(0, idx_ini):min(len(data_wav), idx_fin)]
                        if len(fragmento) > 0:
                            rms = np.sqrt(np.mean(fragmento**2))
                            if rms > 0:
                                relacion = rms / rms_total
                                intensidad_db = round(float(20 * np.log10(max(0.01, relacion))), 2)
                                intensidad_db = max(min(intensidad_db, 3.0), -6.0)

                    partitura_real.append({
                        "palabra": palabra,
                        "duracion_ms": duracion_ms,
                        "intensidad_db": intensidad_db
                    })

        texto_crudo = texto_crudo.strip()

        if not texto_crudo:
            await update.message.reply_text("Che, no te capté bien el audio.")
            return

        if not partitura_real:
            partitura_real = [{"palabra": w, "duracion_ms": 200, "intensidad_db": 0.0} for w in texto_crudo.split()]

        registrar_conversacion("Usuario", texto_crudo)

        if "durante el día" in texto_crudo.lower() or "escribime" in texto_crudo.lower() or "recordá" in texto_crudo.lower():
            registrar_tarea_pendiente(texto_crudo)

        registrar_entrenamiento_json(path_wav if os.path.exists(path_wav) else path_ogg, texto_crudo, partitura_real)

        texto_limpio, partitura_respuesta = generar_respuesta_y_partitura_ia(texto_crudo)
        registrar_conversacion("LeandroBot", texto_limpio)
        registrar_entrenamiento_chat(texto_crudo, texto_limpio)

        try:
            subprocess.run(["git", "config", "--global", "user.name", "Bot de Telegram"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "bot@github.action"], check=True)
            subprocess.run(["git", "add", CARPETA_MUESTRAS, REGISTRO_METRICAS, MEMORIA_TAREAS, TXT_FILE, DATASET_ENTRENAMIENTO], check=True)
            subprocess.run(["git", "commit", "-m", f"🧠 Auto-entrenamiento chat y voz: {update.message.message_id}"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("🚀 [GIT SYNC]: Dataset y métricas sincronizados en GitHub.")
        except Exception as git_err:
            print(f"⚠️ [GIT SYNC]: Push omitido o sin permisos: {git_err}")

        ogg_f = "resp.ogg"
        sintetizar_con_partitura_de_ia(texto_limpio, partitura_respuesta, ogg_f)

        caption_texto = (
            f"🎙️ *Lo que captó Whisper:*\n\"{texto_crudo}\"\n\n"
            f"💡 _Si le pifió, respondé con:_\n`/corregir [texto real]`"
        )

        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=caption_texto, parse_mode="Markdown")

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

    print("🚀 Iniciando Bot Híbrido Definitivo...")
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)
    app = Application.builder().token(TOKEN).request(request_config).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("corregir", corregir_transcripcion))
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
