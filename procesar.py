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

print("🚀 [INIT]: Inicializando sistema definitivo (Bark con Partitura + Gemini/Llama)...")

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
    print("✅ [INIT]: Motor de timbre Bark cargado.")
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
        print(f"📝 [TXT SYNC]: Mensaje de {remitente} guardado.")
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
        
    print(f"📒 [REGISTRO METRICAS]: Métrica #{nuevo_registro['total_entrenamientos']} guardada.")


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


def generar_respuesta_y_partitura_ia(prompt_usuario):
    global GEMINI_BLOQUEADO_POR_CUOTA
    respuesta_raw = ""
    
    system_prompt = (
        "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo.\n"
        "REGLA FONÉTICA Y LINGÜÍSTICA OBLIGATORIA: Escribí y respondé usando strictly el español rioplatense (porteño), "
        "utilizando el voseo natural ('vós sabés', 'vení', 'fijate', 'escuchá'), lunfardo sutil y la entonación de Buenos Aires.\n"
        "INTELIGENCIA DE CANAL: Analizá el mensaje del usuario y determiná si la respuesta va en 'texto', 'voz' o 'ambos'.\n"
        "ANÁLISIS DE MÉTRICAS OBLIGATORIO: Analizá las métricas registradas para estructurar una 'partitura' ultra precisa.\n\n"
        "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown, solo el JSON crudo):\n"
        "{\n"
        "  \"texto_completo\": \"Tu respuesta hablada o escrita aquí con acentuación porteña\",\n"
        "  \"canal_salida\": \"voz\",\n"
        "  \"partitura\": [\n"
        "    {\"palabra\": \"Che,\", \"duracion_ms\": 120, \"intensidad_db\": -1.0},\n"
        "    {\"palabra\": \"escuchá\", \"duracion_ms\": 250, \"intensidad_db\": 0.0}\n"
        "  ]\n"
        "}"
    )
    
    # 1. Prioridad Absoluta: Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA and os.path.exists(REGISTRO_METRICAS):
        for intento in range(2):
            try:
                print("🤖 [IA GEMINI]: Generando respuesta con Gemini...")
                adjunto_metricas = client.files.upload(file=REGISTRO_METRICAS)
                res = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[adjunto_metricas, f"Mensaje del oyente: \"{prompt_usuario}\""],
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json"
                    )
                )
                if res and res.text:
                    respuesta_raw = str(res.text).strip()
                    print("✅ [IA GEMINI]: Éxito.")
                    break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    GEMINI_BLOQUEADO_POR_CUOTA = True
                    print("⚠️ [IA GEMINI]: Cuota agotada. Pasando a fallback de Llama...")
                    break
                time.sleep(2)

    # 2. Fallback Estricto: Llama local (Ollama)
    if not respuesta_raw or GEMINI_BLOQUEADO_POR_CUOTA:
        print(f"🦙 [IA LLAMA FALLBACK]: Conectando a Ollama en {OLLAMA_HOST}...")
        
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_usuario}
            ],
            "format": "json",
            "options": {"num_ctx": 4096, "temperature": 0.7},
            "stream": False,
        }
        try:
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            res_local = requests.post(url_llama, json=payload, timeout=90)
            if res_local.status_code == 200:
                respuesta_raw = str(res_local.json().get("message", {}).get("content", "")).strip()
                print("✅ [IA LLAMA FALLBACK]: Respuesta obtenida con éxito.")
        except Exception as ex_local:
            print(f"⚠️ Error en Llama local: {ex_local}")

    if not isinstance(respuesta_raw, str):
        respuesta_raw = str(respuesta_raw or "")

    respuesta_raw = re.sub(r'^```json\s*', '', respuesta_raw, flags=re.IGNORECASE)
    respuesta_raw = re.sub(r'^```\s*', '', respuesta_raw)
    respuesta_raw = re.sub(r'\s*```$', '', respuesta_raw).strip()

    try:
        datos = json_lib.loads(respuesta_raw)
        texto = datos.get("texto_completo", "Che, todo bien por acá.")
        canal_salida = datos.get("canal_salida", "voz").lower()
        partitura = datos.get("partitura", [])
        if not partitura:
            partitura = [{"palabra": w, "duracion_ms": 200, "intensidad_db": 0.0} for w in texto.split()]
        return texto, canal_salida, partitura
    except Exception as e:
        print(f"⚠️ Error parseando JSON: {e}. Respuesta cruda: {respuesta_raw}")
        texto_fb = "Che, te capté perfecto, sintonizamos en un toque."
        return texto_fb, "ambos", [{"palabra": w, "duracion_ms": 200, "intensidad_db": 0.0} for w in texto_fb.split()]


def sintetizar_con_partitura_de_ia(texto, partitura, ogg_salida="resp.ogg"):
    sample_rate = 24000
    audio_final = None

    if BARK_DISPONIBLE:
        try:
            print("🎙️ [BARK PRO]: Inicializando motor y aplicando parámetros de partitura...")
            processor = AutoProcessor.from_pretrained("suno/bark-small")
            model = BarkModel.from_pretrained("suno/bark-small")
            device = "cpu"
            model = model.to(device)

            texto_limpio = texto.strip()[:300]
            inputs = processor(f"[es] {texto_limpio}", voice_preset="v2/es_speaker_2").to(device)
            
            intensidades = [item.get("intensidad_db", 0.0) for item in partitura]
            promedio_db = sum(intensidades) / len(intensidades) if intensidades else 0.0
            temp_generacion = float(np.clip(0.7 + (promedio_db * 0.05), 0.5, 0.95))
            
            with torch.no_grad():
                tokens_audio = model.generate(
                    **inputs,
                    max_new_tokens=256,
                    temperature=temp_generacion
                )
            
            audio_bark = tokens_audio.cpu().numpy().squeeze()
            if len(audio_bark) > 5000:
                audio_final = audio_bark
                print("✅ [BARK PRO]: Audio generado con éxito.")
        except Exception as e:
            print(f"⚠️ Error en síntesis con Bark: {e}")

    if audio_final is None or len(audio_final) == 0:
        print("⚠️ [SÍNTESIS]: Usando modulador armónico de respaldo.")
        t = np.linspace(0, 3, sample_rate * 3, endpoint=False)
        audio_final = (0.5 * np.sin(2 * np.pi * 140 * t)).astype(np.float32)

    if len(audio_final.shape) > 1:
        audio_final = np.mean(audio_final, axis=1)

    max_val = np.max(np.abs(audio_final))
    if max_val > 0:
        audio_final = audio_final / max_val

    audio_dinamico = np.array([], dtype=np.float32)
    total_muestras = len(audio_final)
    paso_base = max(1, total_muestras // max(1, len(partitura)))

    for i, item in enumerate(partitura):
        duracion_ms = max(100, min(int(item.get("duracion_ms", 200)), 600))
        intensidad_db = max(min(float(item.get("intensidad_db", 0.0)), 2.0), -3.0)
        mult_vol = 10 ** (intensidad_db / 20.0)

        muestras_bloque = int(sample_rate * (duracion_ms / 1000.0))
        start_idx = min(i * paso_base, max(0, total_muestras - muestras_bloque))
        end_idx = min(start_idx + muestras_bloque, total_muestras)
        
        fragmento = audio_final[start_idx:end_idx].copy()
        if len(fragmento) == 0:
            fragmento = audio_final[:muestras_bloque].copy()

        fade_samples = int(sample_rate * 0.01)
        if len(fragmento) > fade_samples * 2:
            ventana_in = np.hanning(fade_samples * 2)[:fade_samples]
            ventana_out = np.hanning(fade_samples * 2)[fade_samples:]
            fragmento[:fade_samples] *= ventana_in
            fragmento[-fade_samples:] *= ventana_out

        audio_dinamico = np.concatenate((audio_dinamico, fragmento * mult_vol))

    if len(audio_dinamico) < sample_rate * 0.5:
        audio_dinamico = audio_final

    try:
        proceso_ffmpeg = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "-",
            "-filter:a", "highpass=f=90,lowpass=f=7500,volume=1.3",
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
            ogg_salida
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        proceso_ffmpeg.communicate(input=audio_dinamico.astype(np.float32).tobytes())
        print(f"🎉 [SÍNTESIS OGG]: Audio con Bark y partitura exportado a {ogg_salida}")
    except Exception as e:
        print(f"⚠️ Error al empaquetar Ogg con Bark: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con Bark parametrizado y soporte Gemini/Llama.")


async def corregir_transcripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Che, respondé al mensaje para corregir.")
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
                subprocess.run(["git", "commit", "-m", f"✏️ Corrección: {texto_corregido[:30]}..."], check=True)
                subprocess.run(["git", "push"], check=True)
            except Exception as e_git:
                print(f"⚠️ Error git: {e_git}")

            await update.message.reply_text(
                f"✅ ¡Aprendido!\n❌ *Whisper:* \"{texto_anterior}\"\n✅ *Real:* \"{texto_corregido}\"",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("No encontré registros.")
    except Exception as e:
        print(f"⚠️ Error: {e}")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    registrar_conversacion("Usuario", texto_usuario)

    if "durante el día" in texto_usuario.lower() or "escribime" in texto_usuario.lower() or "recordá" in texto_usuario.lower():
        registrar_tarea_pendiente(texto_usuario)

    texto_limpio, canal_salida, partitura = generar_respuesta_y_partitura_ia(texto_usuario)
    registrar_conversacion("LeandroBot", texto_limpio)
    registrar_entrenamiento_chat(texto_usuario, texto_limpio)

    if canal_salida in ["texto", "ambos"]:
        await update.message.reply_text(texto_limpio)
    
    if canal_salida in ["voz", "ambos"]:
        ogg_f = "resp.ogg"
        sintetizar_con_partitura_de_ia(texto_limpio, partitura, ogg_f)
        with open(ogg_f, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(ogg_f): os.remove(ogg_f)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock_voz:
        await update.message.chat.send_action(action="record_voice")
        file = await update.message.voice.get_file()
        
        path_ogg = os.path.join(CARPETA_MUESTRAS, f"audio_usuario_{update.message.message_id}.ogg")
        await file.download_to_drive(path_ogg)

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path_ogg, beam_size=5, language="es", word_timestamps=True)
        
        texto_crudo = ""
        partitura_real = []

        sr_wav = 22050
        try:
            cmd_dec = ["ffmpeg", "-y", "-i", path_ogg, "-f", "f32le", "-ar", str(sr_wav), "-ac", "1", "-"]
            res_dec = subprocess.run(cmd_dec, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
            data_wav = np.frombuffer(res_dec.stdout, dtype=np.float32)
        except Exception:
            data_wav = np.array([], dtype=np.float32)

        rms_total = np.sqrt(np.mean(data_wav**2)) if len(data_wav) > 0 else 0

        for segment in segments:
            texto_crudo += segment.text + " "
            if hasattr(segment, 'words') and segment.words:
                for w_info in segment.words:
                    palabra = w_info.word.strip()
                    inicio_ms = int(w_info.start * 1000)
                    fin_ms = int(w_info.end * 1000)
                    duracion_ms = max(50, fin_ms - inicio_ms)
                    
                    intensidad_db = 0.0
                    if len(data_wav) > 0 and rms_total > 0:
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

        silencios_o_ruido = ["", "you", "acias", ".", "-", "hmm", "ehh"]
        if not texto_crudo or texto_crudo.lower() in silencios_o_ruido or len(texto_crudo) < 2:
            await update.message.reply_text("Che, el audio salió incomprensible. ¿Me lo repetís?")
            return

        if not partitura_real:
            partitura_real = [{"palabra": w, "duracion_ms": 200, "intensidad_db": 0.0} for w in texto_crudo.split()]

        registrar_conversacion("Usuario", texto_crudo)

        if "durante el día" in texto_crudo.lower() or "escribime" in texto_crudo.lower() or "recordá" in texto_crudo.lower():
            registrar_tarea_pendiente(texto_crudo)

        registrar_entrenamiento_json(path_ogg, texto_crudo, partitura_real)

        texto_limpio, canal_salida, partitura_respuesta = generar_respuesta_y_partitura_ia(texto_crudo)
        registrar_conversacion("LeandroBot", texto_limpio)
        registrar_entrenamiento_chat(texto_crudo, texto_limpio)

        try:
            subprocess.run(["git", "config", "--global", "user.name", "Bot de Telegram"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "bot@github.action"], check=True)
            subprocess.run(["git", "add", CARPETA_MUESTRAS, REGISTRO_METRICAS, MEMORIA_TAREAS, TXT_FILE, DATASET_ENTRENAMIENTO], check=True)
            subprocess.run(["git", "commit", "-m", f"🧠 Auto-entrenamiento: {update.message.message_id}"], check=True)
            subprocess.run(["git", "push"], check=True)
        except Exception as git_err:
            print(f"⚠️ Git push omitido: {git_err}")

        if canal_salida in ["texto", "ambos"]:
            await update.message.reply_text(f"💬 *Respuesta por escrito:*\n\n{texto_limpio}", parse_mode="Markdown")

        if canal_salida in ["voz", "ambos"]:
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

    print("🚀 Iniciando Bot Híbrido (Bark Parametrizado + Gemini/Llama)...")
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
            print(f"⚠️ Reconectando en 5 segundos... ({e})")
            time.sleep(5)


if __name__ == "__main__":
    main()
