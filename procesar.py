"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo y completo (Gemini TTS + Edge-TTS + Whisper + Ollama): procesar.py
"""

import asyncio
json_lib = __import__('json')
import os
import re
import sys
import subprocess
import requests
import time
from datetime import datetime

# --- INYECCIÓN AUTOMÁTICA DE HF_TOKEN ---
hf_token = os.environ.get("HF_TOKEN")
if hf_token:
    os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
    print("🔑 [HUGGING FACE]: Token detectado e inyectado correctamente.")
# ----------------------------------------

print("🚀 [INIT]: Inicializando LeandroBot en GitHub Actions...", flush=True)

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
import edge_tts

TXT_FILE = "conversaciones.txt"
MEMORIA_TAREAS = "memoria_tareas.json"
CARPETA_MUESTRAS = "muestras_voz"
os.makedirs(CARPETA_MUESTRAS, exist_ok=True)

if not os.path.exists(MEMORIA_TAREAS):
    with open(MEMORIA_TAREAS, "w", encoding="utf-8") as f:
        json_lib.dump([], f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# Leemos el CHAT_ID directamente desde los Secrets de GitHub
ENV_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHAT_ID_ACTIVO = int(ENV_CHAT_ID) if ENV_CHAT_ID and ENV_CHAT_ID.strip().isdigit() else None

if CHAT_ID_ACTIVO:
    print(f"🎯 [SECRETS]: CHAT_ID cargado exitosamente: {CHAT_ID_ACTIVO}")
else:
    print("⚠️ [SECRETS]: TELEGRAM_CHAT_ID no encontrado en secretos. Se capturará con el primer mensaje.")

lock_voz = asyncio.Lock()
GEMINI_BLOQUEADO_POR_CUOTA = False

client = None
try:
    from google import genai
    if GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ [GEMINI]: Cliente GenAI inicializado correctamente.")
except Exception as e:
    print(f"⚠️ [GEMINI ERROR]: {e}")

SYSTEM_PROMPT = (
    "Sos Leandro, locutor nocturno de radio FM y colega por Telegram. Porteño, cálido y directo.\n"
    "REGLA FONÉTICA Y LINGÜÍSTICA OBLIGATORIA: Escribí y respondé usando estrictamente el español rioplatense (porteño), "
    "utilizando el voseo natural ('che', 'vós sabés', 'vení', 'fijate', 'escuchá', 'sintonizamos en un toque', 'posta'), "
    "lunfardo sutil y la entonación de Buenos Aires.\n"
    "INTELIGENCIA AUTÓNOMA: Iniciás charlas por propia cuenta, compartís pensamientos nocturnos y chequeás tareas pendientes.\n"
    "Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown):\n"
    "{\n"
    '  "texto_completo": "Tu respuesta hablada o escrita con acentuación porteña",\n'
    '  "canal_salida": "ambos"\n'
    "}"
)

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}\n")
    except Exception as e:
        print(f"⚠️ Error conversacion: {e}")

def generar_texto_ia(prompt_usuario, es_proactivo=False):
    global GEMINI_BLOQUEADO_POR_CUOTA
    p = prompt_usuario
    if es_proactivo:
        p = f"Iniciá vos la conversación con tu colega en Telegram por iniciativa propia sobre este motivo: {prompt_usuario}."

    respuesta = ""

    # 1. Gemini
    if client and not GEMINI_BLOQUEADO_POR_CUOTA:
        try:
            print("🤖 [IA GEMINI]: Generando respuesta...", flush=True)
            res = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=p,
                config=dict(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
            )
            raw = (res.text or "").strip()
            if raw:
                raw = re.sub(r'^```json\s*', '', raw, flags=re.IGNORECASE)
                raw = re.sub(r'^```\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw).strip()
                data = json_lib.loads(raw)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    respuesta = str(texto).strip()
                    print("✅ [IA GEMINI]: Éxito.")
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                GEMINI_BLOQUEADO_POR_CUOTA = True
            print(f"⚠️ Gemini falló, conmutando a Llama: {e}")

    # 2. Fallback a Llama (Ollama local)
    if not respuesta:
        print(f"🦙 [IA LLAMA]: Conectando a Ollama en {OLLAMA_HOST}...", flush=True)
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": p}
            ],
            "format": "json",
            "options": {"num_ctx": 4096, "temperature": 0.7},
            "stream": False,
        }
        try:
            url_llama = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
            res_local = requests.post(url_llama, json=payload, timeout=15)
            if res_local.status_code == 200:
                content_str = res_local.json().get("message", {}).get("content", "{}")
                content_str = re.sub(r'^```json\s*', '', content_str, flags=re.IGNORECASE)
                content_str = re.sub(r'^```\s*', '', content_str)
                content_str = re.sub(r'\s*```$', '', content_str).strip()
                data = json_lib.loads(content_str)
                texto = data.get("texto_completo")
                if texto and str(texto).strip():
                    respuesta = str(texto).strip()
                    print("✅ [IA LLAMA]: Éxito.")
        except Exception as ex_local:
            print(f"⚠️ Error en Llama local: {ex_local}")

    # 3. Comodín de radio FM
    if not respuesta or not str(respuesta).strip():
        print("⚠️ [RADIO FM]: Usando comodín de respaldo local.")
        import random
        respuestas_radio = [
            "¡Buenas che! Acá Leandro en el éter. Te capté perfecto. Sintonizamos en un toque.",
            "Qué hacés che, de una. Anotado acá en la consola de la radio.",
            "Totalmente de acuerdo, che. Me quedo con eso en mente para la próxima salida al aire."
        ]
        respuesta = random.choice(respuestas_radio)

    return respuesta

# ==========================================
# SISTEMA DE VOCES: GEMINI TTS + EDGE-TTS
# ==========================================
VOZ_ESTILO_PERSONALIZADO = os.environ.get(
    "VOZ_ESTILO",
    "Locutor nocturno de radio FM porteño, hombre de 42 años, tono barítono cálido, pausado, acústica de cabina de radio y voseo de Buenos Aires"
)
VOZ_BASE_NOMBRE = os.environ.get("VOZ_BASE", "Charon")
EDGE_VOICE = os.environ.get("EDGE_VOICE", "es-AR-TomasNeural")
EDGE_PITCH = os.environ.get("EDGE_PITCH", "-4Hz")
EDGE_RATE = os.environ.get("EDGE_RATE", "-5%")

def sintetizar_voz_gemini(texto, ogg_salida="resp.ogg"):
    if not client:
        return False
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"role": "user", "parts": [{"text": texto, "speechMetadata": {"style": VOZ_ESTILO_PERSONALIZADO}}] }],
            config=dict(
                response_modalities=["AUDIO"],
                speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name
