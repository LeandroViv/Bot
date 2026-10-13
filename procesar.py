"""
Repositorio: https://github.com/LeandroViv/Bot
Script definitivo para GitHub Actions (Gemini TTS + gTTS + DSP Espectral con Rubberband): procesar.py
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
from gtts import gTTS

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

ENV_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHAT_ID_ACTIVO = int(ENV_CHAT_ID) if ENV_CHAT_ID and ENV_CHAT_ID.strip().isdigit() else None

if CHAT_ID_ACTIVO:
    print(f"🎯 [SECRETS]: CHAT_ID cargado exitosamente: {CHAT_ID_ACTIVO}")
else:
    print("⚠️ [SECRETS]: TELEGRAM_CHAT_ID no encontrado en secretos. Se capturará con el primer mensaje.")

lock_voz = asyncio.Lock()
GEMINI_BLOQUEADO_POR_CUOTA = False
MODELO_GEMINI = "gemini-2.0-flash"

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
            print(f"🤖 [IA GEMINI]: Generando respuesta con {MODELO_GEMINI}...", flush=True)
            res = client.models.generate_content(
