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
        "REGLA FONÉTICA Y LINGÜÍSTICA OBLIGATORIA: Escribí y respondé usando estrictamente el español rioplatense (porteño), "
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

    if len(audio_final.shape) > 1
