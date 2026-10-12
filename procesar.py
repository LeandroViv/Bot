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

print("🚀 [INIT]: Inicializando sistema híbrido definitivo con síntesis directa Ogg y métricas...")

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
        
    print(f"📒 [REGISTRO METRICAS]: Métrica #{nuevo_registro['total_entrenamientos']} guardada en JSON.")


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
        "REGLA FONÉTICA Y LINGÜÍSTICA OBLIGATORIA: Escribí y respondé usando estrictamente el español rioplatense (porteño), "
        "utilizando el voseo natural ('vós sabés', 'vení', 'fijate', 'escuchá'), lunfardo sutil y la entonación de Buenos Aires.\n"
        "INTELIGENCIA DE CANAL: Analizá el mensaje del usuario y determiná si la respuesta va en 'texto', 'voz' o 'ambos'.\n"
        "ANÁLISIS DE MÉTRICAS OBLIGATORIO: Analizá las métricas del historial para estructurar una 'partitura' ultra precisa.\n\n"
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
    
    if client and not GEMINI_BLOQUEADO_POR_CUOTA and os.path.exists(REGISTRO_METRICAS):
        for intento in range(2):
            try:
                print("🤖 [IA]: Enviando prompt junto con el archivo de métricas de voz a Gemini...")
                adjunto_metricas = client.files.upload(file=REGISTRO_METRICAS)
                res = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=[adjunto_metricas, f"Mensaje del oyente: \"{prompt_usuario}\""],
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json"
                    )
                )
                if res and res.text:
                    respuesta_raw = str(res.text).strip()
                    print("✅ [IA CONECTADA]: Gemini respondió con éxito.")
                    break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    GEMINI_BLOQUEADO_POR_CUOTA = True
                    break
                time.sleep(2)

    if not respuesta_raw or GEMINI_BLOQUEADO_POR_CUOTA:
        print(f"🦙 [IA LOCAL]: Usando Llama local (Ollama) con timeout extendido de 120s...")
        
        res_metricas_resumen = ""
        if os.path.exists(REGISTRO_METRICAS):
            try:
                with open(REGISTRO_METRICAS, "r", encoding="utf-8") as f:
                    m_data = json_lib.load(f)
                    res_metricas_resumen = json_lib.dumps(m_data[-5:], ensure_ascii=False)
            except Exception:
                pass

        prompt_con_contexto = f"Métricas recientes:\n{res_metricas_resumen}\nMensaje actual: {prompt_usuario}"
        
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_con_contexto}
            ],
            "format": "json",
            "options": {"num_ctx": 8192, "temperature": 0.7},
            "stream": False,
        }
        try:
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            res_local = requests.post(url_llama, json=payload, timeout=120)
            if res_local.status_code == 200:
                respuesta_raw = str(res_local.json().get("message", {}).get("content", "")).strip()
                print("✅ [IA LOCAL]: Llama respondió correctamente.")
        except Exception as ex_local:
            print(f"⚠️ Error Llama local: {ex_local}")

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
    wav_temp_timbre = "temp_timbre_bark.wav"
    sample_rate = 24000
    timbre_ok = False

    if BARK_DISPONIBLE:
        try:
            processor = AutoProcessor.from_pretrained("suno/bark-small")
            model = BarkModel.from_pretrained("suno/bark-small")
            device = "cpu"
            model = model.to(device)

            texto_corto = texto.strip()[:250]
            inputs = processor(f"[es] {texto_corto}", voice_preset="v2/es_speaker_2").to(device)
            
            with torch.no_grad():
                audio_bark = model.generate(**inputs, max_new_tokens=256)
            
            audio_bark = audio_bark.cpu().numpy().squeeze()
            if len(audio_bark) > 5000:
                sf.write(wav_temp_timbre, audio_bark, sample_rate)
                timbre_ok = os.path.exists(wav_temp_timbre)
        except Exception as e:
            print(f"⚠️ Error timbre Bark: {e}")

    if not timbre_ok:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=180:duration=2", wav_temp_timbre], check=True)

    try:
        data_timbre, sr = sf.read(wav_temp_timbre)
        if len(data_timbre.shape) > 1:
            data_timbre = np.mean(data_timbre, axis=1)

        max_val = np.max(np.abs(data_timbre))
        if max_val > 0:
            data_timbre = data_timbre / max_val

        if not partitura:
            partitura = [{"palabra": w, "duracion_ms": 200, "intensidad_db": 0.0} for w in texto.split()]

        audio_dinamico = np.array([], dtype=np.float32)
        total_muestras_audio = len(data_timbre)
        paso_base = max(1, total_muestras_audio // max(1, len(partitura)))

        for i, item in enumerate(partitura):
            duracion_ms = max(100, min(int(item.get("duracion_ms", 200)), 600))
            intensidad_db = max(min(float(item.get("intensidad_db", 0.0)), 2.0), -3.0)
            mult_vol = 10 ** (intensidad_db / 20.0)

            muestras_bloque = int(sr * (duracion_ms / 1000.0))
            start_idx = min(i * paso_base, max(0, total_muestras_audio - muestras_bloque))
            end_idx = min(start_idx + muestras_bloque, total_muestras_audio)
            
            fragmento = data_timbre[start_idx:end_idx]
            if len(fragmento) == 0:
                fragmento = data_timbre[:muestras_bloque]

            fade_samples = int(sr * 0.008)
            if len(fragmento) > fade_samples * 2:
                fragmento[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples)
                fragmento[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples)

            audio_dinamico = np.concatenate((audio_dinamico, fragmento * mult_vol))

        if len(audio_dinamico) < sr * 0.5:
            audio_dinamico = data_timbre

        # Síntesis directa a Ogg/Opus sin archivos WAV intermedios
        proceso_ffmpeg = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
            ogg_salida
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        proceso_ffmpeg.communicate(input=audio_dinamico.astype(np.float32).tobytes())
    except Exception as e:
        print(f"⚠️ Error en síntesis directa Ogg: {e}")
        subprocess.run(["ffmpeg", "-y", "-i", wav_temp_timbre, "-c:a", "libopus", ogg_salida], check=True)

    if os.path.exists(wav_temp_timbre):
        os.remove(wav_temp_timbre)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con métricas y síntesis directa.")


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

            await update.message.reply_text(f"✅ ¡Aprendido!\n❌ *Whisper:* \"{texto_anterior}\"\n✅ *Real
