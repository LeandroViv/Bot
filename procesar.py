import asyncio
import json
import os
import re
import subprocess
from bs4 import BeautifulSoup
from ddgs import DDGS
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import whisper
from gtts import gTTS

TXT_FILE = "conversaciones.txt"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Candado global para procesar notas de voz en orden estricto
lock_voz = asyncio.Lock()


def sincronizar_txt_con_github():
    """Hace commit y push automático del conversaciones.txt al repositorio."""
    try:
        subprocess.run(["git", "config", "--global", "user.name", "Leandro Bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@actions.github.com"], check=True)
        
        subprocess.run(["git", "add", TXT_FILE], check=True)
        resultado = subprocess.run(["git", "commit", "-m", "🤖 Actualización automática de conversaciones.txt"], capture_output=True, text=True)
        
        if "nothing to commit" not in resultado.stdout:
            subprocess.run(["git", "push"], check=True)
            print("☁️ conversaciones.txt sincronizado con éxito en GitHub.")
    except Exception as e:
        print(f"⚠️ No se pudo sincronizar el .txt con GitHub: {e}")


def guardar_en_txt(rol, texto):
    """Guarda el historial en un archivo .txt plano y lo sube a GitHub."""
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{rol.upper()}]: {texto}\n---\n")
    
    sincronizar_txt_con_github()


def exportar_dataset_actualizado():
    """Genera/actualiza dataset.jsonl cada vez que hay nuevos datos."""
    try:
        from exportar_dataset import generar_y_subir_dataset
        generar_y_subir_dataset()
    except Exception as e:
        print(f"⚠️ No se pudo exportar el dataset: {e}")


def llamar_ollama(messages, timeout_secs=300):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": "llama3.2",
        "messages": messages,
        # Temperatura bajada al palo (0.1) para prohibir divagues yucas o resúmenes colgados
        "options": {"num_ctx": 16384, "temperature": 0.1},
        "stream": False,
    }
    try:
        res = requests.post(url, json=payload, timeout=timeout_secs)
        if res.status_code == 200:
            contenido = res.json().get("message", {}).get("content", "").strip()
            if contenido:
                return contenido
    except Exception as e:
        print(f"⚠️ Error conectando con Ollama: {e}")
    return ""


def extraer_vocabulario_global_de_txt():
    """Extrae dinámicamente términos, acrónimos y jerga técnica de TODO el historial histórico."""
    if not os.path.exists(TXT_FILE):
        return ""
    
    with open(TXT_FILE, "r", encoding="utf-8") as f:
        historial_entero = f.read()

    if not historial_entero.strip():
        return ""

    prompt = [
        {
            "role": "system",
            "content": (
                "Analizá todo el historial de conversaciones provisto. "
                "Extraé una lista consolidada de palabras clave, términos técnicos, "
                "acrónimos, nombres propios o conceptos recurrentes que definan el universo de temas del usuario.\n"
                "Devolvé SOLAMENTE las palabras separadas por comas, sin explicaciones."
            ),
        },
        {"role": "user", "content": historial_entero},
    ]
    
    resultado = llamar_ollama(prompt, timeout_secs=45)
    return resultado if resultado else ""


def corregir_transcripcion_por_contexto(texto_transcrito):
    """Usa la IA y la memoria global para corregir errores fonéticos de Whisper."""
    if not os.path.exists(TXT_FILE) or not texto_transcrito:
        return texto_transcrito

    with open(TXT_FILE, "r", encoding="utf-8") as f:
        historial_resumido = f.read()[-3000:]

    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un corrector fonético inteligente para transcripciones de voz. "
                "Dado el texto transcribido por voz y el contexto de las charlas previas, "
                "detectá si hay errores de interpretación y dejas coherente el texto. "
                "Devolvé ÚNICAMENTE el texto corregido sin agregar explicaciones ni comillas."
            ),
        },
        {"role": "user", "content": f"Contexto previo:\n{historial_
