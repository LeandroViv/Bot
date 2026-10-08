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
        f"CONTENIDO ACTUAL DEL ARCHIVO:\n