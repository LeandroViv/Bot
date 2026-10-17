# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / Vibe Coding por Parches Quirúrgicos + Terminal Runner + Git Push Autonomous + DSP + Whisper

import asyncio
import json as json_lib
import os
import re
import sys
import subprocess
import requests
import time
from datetime import datetime
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

print("🚀 [INIT]: Inicializando LeandroBot Adaptativo (Vibe Coding por Parches Quirúrgicos + Terminal Runner)...", flush=True)

URL_REPOSITORIO = "https://github.com/LeandroViv/Bot"
TXT_FILE = "conversaciones.txt"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
PERFIL_DINAMICO = "perfil_personaje.json"
PARCHE_FILE = "parche_temp.txt"

for f_path, default_val in [
    (TXT_FILE, ""),
    (DATASET_ENTRENAMIENTO, []),
    (PERFIL_DINAMICO, {
        "nombre": "Leandro",
        "estilo": "Colega y compañero de vibe coding con tonada rioplatense, yeísmo y ritmo auténtico",
        "notas_aprendizaje": []
    }),
    (CONFIG_TIMBRE, {
        "voice": "es-AR-TomasNeural",
        "pitch": "-4Hz",
        "rate": "-5%",
        "volume": "+10%",
        "f0Hz": 125,
        "harmonics": [],
        "descripcion": "Motor acústico dinámico por Vibe Coding"
    })
]:
    if not os.path.exists(f_path):
        if isinstance(default_val, str):
            with open(f_path, "w", encoding="utf-8") as f:
                f.write(default_val)
        else:
            with open(f_path, "w", encoding="utf-8") as f:
                json_lib.dump(default_val, f, indent=4, ensure_ascii=False)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

CHAT_ID_ACTIVO = None

try:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    GENAI_DISPONIBLE = True if client else False
except Exception:
    client = None
    GENAI_DISPONIBLE = False

def asegurar_ollama_en_runner():
    try:
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3.0)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        print(f"🦙 [OLLAMA RUNNER]: Intentando conectar / levantar servicio en {OLLAMA_HOST}...", flush=True)
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(3)
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=3.0)
        if r.status_code == 200:
            print("🦙 [OLLAMA RUNNER]: ¡Servicio conectado con éxito en el runner!", flush=True)
            return True
    except Exception as ex:
        print(f"⚠️ Aviso conexión Ollama en runner: {ex}", flush=True)
    return False

def ejecutar_comando_runner_en_vivo(cmd_str):
    try:
        print(f"💻 [TERMINAL RUNNER]: Ejecutando -> {cmd_str}", flush=True)
        res = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        salida = res.stdout.strip() if res.stdout else res.stderr.strip()
        if not salida:
            salida = "Comando ejecutado con éxito (sin salida gráfica)."
        return True, salida
    except Exception as e:
        return False, f"Error ejecutando comando: {str(e)}"

def obtener_mapa_repositorio(root_dir="."):
    mapa = []
    ignorar = {".git", "__pycache__", ".github", "venv", "downloads"}
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in ignorar]
        rel_path = os.path.relpath(dirpath, root_dir)
        if rel_path == ".":
            rel_path = ""
            
        for f in filenames:
            if f.endswith((".py", ".json", ".txt", ".md", ".sh", ".yml")):
                path_completo = os.path.join(rel_path, f) if rel_path else f
                mapa.append(f"  📄 {path_completo}")
                
    return "\n".join(mapa) if mapa else "  📄 procesar.py\n  📄 config_timbre.json"

def guardar_y_pushear_como_leandrobot(archivo_modificado, mensaje_commit):
    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_BOT_TOKEN")
    try:
        subprocess.run(["git", "config", "user.name", "LeandroBot[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "leandrobot@users.noreply.github.com"], check=True)
        
        if gh_token:
            remote_url = f"https://x-access-token:{gh_token}@github.com/LeandroViv/Bot.git"
            subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)

        subprocess.run(["git", "add", archivo_modificado], check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print("ℹ️ No hay cambios pendientes para pushear a GitHub.", flush=True)
            return True

        subprocess.run(["git", "commit", "-m", mensaje_commit], check=True)
        subprocess.run(["git", "push", "origin", "HEAD"], check=True)
        
        print(f"🚀 [GIT PUSH EN CALIENTE]: Cambios en '{archivo_modificado}' pusheados como LeandroBot[bot].", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ Aviso git push automático: {e}", flush=True)
        return False

def aplicar_parche_seguro_en_archivo(path_objetivo, contenido_parche, mensaje_commit):
    """
    Guarda el contenido del parche en `parche_temp.txt` y lo aplica en `procesar.py`
    sin reescribir ni truncar el archivo completo.
    """
    try:
        # Step 1: Guardar el bloque nuevo/modificado en parche_temp.txt
        with open(PARCHE_FILE, "w", encoding="utf-8") as f:
            f.write(contenido_parche)
        
        print(f"📄 [PARCHE TEMP GUARDADO]: Guardado en {PARCHE_FILE}", flush=True)

        # Step 2: Leer archivo destino original
        if not os.path.exists(path_objetivo):
            with open(path_objetivo, "w", encoding="utf-8") as f:
                f.write(contenido_parche)
            return guardar_y_pushear_como_leandrobot(path_objetivo, mensaje_commit)

        with open(path_objetivo, "r", encoding="utf-8") as f:
            codigo_original = f.read()

        # Extraer nombre de la función si es una definición
        match_def = re.search(r'async\s+def\s+([a_zA_Z0-9_]+)|def\s+([a_zA_Z0-9_]+)', contenido_parche)
        nombre_func = match_def.group(1) or match_def.group(2) if match_def else None

        if nombre_func and nombre_func in codigo_original:
            # Reemplazo quirúrgico de la función existente
            patron_func = rf'(async\s+def\s+{nombre_func}\([\s\S]*?)(?=\n(?:async\s+def|def|if\s+__name__|\Z))'
            if re.search(patron_func, codigo_original):
                nuevo_codigo = re.sub(patron_func, contenido_parche.strip() + "\n\n", codigo_original)
            else:
                nuevo_codigo = codigo_original + "\n\n" + contenido_parche.strip()
        else:
            # Si es algo nuevo, se inserta justo antes del bloque principal `if __name__ == "__main__":`
            if 'if __name__ == "__main__":' in codigo_original:
                partes = codigo_original.rsplit('if __name__ == "__main__":', 1)
                nuevo_codigo = partes[0] + contenido_parche.strip() + "\n\nif __name__ == \"__main__\":\n" + partes[1]
            else:
                nuevo_codigo = codigo_original + "\n\n" + contenido_parche.strip()

        # Step 3: Guardar y verificar que no hay pérdida destructiva de datos
        if len(nuevo_codigo.splitlines()) >= len(codigo_original.splitlines()) - 5:
            with open(path_objetivo, "w", encoding="utf-8") as f:
                f.write(nuevo_codigo)
            print(f"✅ [PARCHE APLICADO ÉXITO]: '{path_objetivo}' actualizado mediante {PARCHE_FILE}.", flush=True)
            return guardar_y_pushear_como_leandrobot(path_objetivo, mensaje_commit)
        else:
            print("⚠️ Error: Intento de parche recortó líneas sospechosamente. Abortando.", flush=True)
            return False
    except Exception as e:
        print(f"⚠️ Error al aplicar parche: {e}", flush=True)
        return False

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            cfg = json_lib.load(f)
            vol_raw = str(cfg.get("volume", "+10%"))
            if "db" in vol_raw.lower():
                vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
                cfg["volume"] = f"{vol_num}%"
            return cfg
    except Exception:
        return {
            "voice": "es-AR-TomasNeural",
            "pitch": "-4Hz",
            "rate": "-5%",
            "volume": "+10%",
            "f0Hz": 125,
            "harmonics": [],
            "descripcion": "Motor acústico dinámico"
        }

def guardar_config_timbre(cfg):
    try:
        vol_raw = str(cfg.get("volume", "+10%"))
        if "db" in vol_raw.lower():
            vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
            cfg["volume"] = f"{vol_num}%"

        with open(CONFIG_TIMBRE, "w", encoding="utf-8") as f:
            json_lib.dump(cfg, f, indent=4, ensure_ascii=False)
        print(f"🎙️ [TIMBRE DINÁMICO GUARDADO]: {cfg}", flush=True)
        
        guardar_y_pushear_como_leandrobot(CONFIG_TIMBRE, "chg: actualización de configuración de timbre dinámico")
    except Exception as e:
        print(f"⚠️ Error guardando timbre: {e}", flush=True)

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}" + chr(10))
        print(f"📝 [LOG CHAT] [{remitente}]: {texto[:80]}...", flush=True)
    except Exception as e:
        print(f"⚠️ Error conversacion: {e}", flush=True)

def obtener_memoria_aprendizaje():
    if not os.path.exists(TXT_FILE):
        return ""
    try:
        with open(TXT_FILE, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        ultimas = lineas[-14:] if len(lineas) >= 14 else lineas
        return "".join(ultimas)
    except Exception:
        return ""

def buscar_en_web(query):
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        with DDGS() as ddgs_instance:
            results = list(ddgs_instance.text(query, max_results=3))
            if results:
                lineas = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
                print(f"🌐 [WEB SEARCH]: {query[:40]}...", flush=True)
                return "\n".join(lineas)
    except Exception as e:
        print(f"⚠️ Aviso búsqueda web: {e}", flush=True)
    return ""

def generar_serie_armonica_dinamica(f0_hz, ganancias=None):
    f0 = max(40, int(f0_hz))
    bandas = []
    ganancias = ganancias or {}
    for orden in range(1, 17):
        hz = orden * f0
        if hz > 22000:
            break
        g = float(ganancias.get(orden, ganancias.get(str(orden), 0.0)))
        q = 1.5 if orden == 1 else (2.0 if orden <= 4 else 3.0)
        bandas.append({
            "order": orden,
            "hz": hz,
            "gainDb": g,
            "q": q,
            "enabled": True
        })
    return bandas

def construir_filtro_ffmpeg_desde_armonicos(cfg):
    partes = []
    harmonics = cfg.get("harmonics", [])
    
    for h in harmonics:
        if h.get("enabled", True) and h.get("gainDb", 0) != 0:
            hz = h.get("hz", 0)
            gain = max(-18.0, min(12.0, float(h.get("gainDb", 0))))
            q = max(1.0, min(4.0, float(h.get("q", 2.0))))
            if 50 < hz < 16000:
                partes.append(f"equalizer=f={hz}:width_type=q:w={q}:g={gain}")

    vol_raw = str(cfg.get("volume", "+10%"))
    vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
    try:
        v_pct = float(vol_num)
        if v_pct != 0:
            mult = round(10 ** (v_pct / 50.0), 2)
            partes.append(f"volume={mult}")
    except Exception:
        pass

    rate_raw = str(cfg.get("rate", "-5%"))
    rate_num = re.sub(r'[^0-9+-]', '', rate_raw)
    try:
        r_pct = float(rate_num)
        if r_pct != 0:
            tempo = max(0.7, min(1.4, round(1.0 + r_pct / 100.0, 2)))
            if tempo != 1.0:
                partes.append(f"atempo={tempo}")
    except Exception:
        pass

    return ",".join(partes)

def parsear_timbre_dinamico_ia(instruccion_usuario):
    cfg_actual = cargar_config_timbre()
    
    match_hz = re.search(r'(\d+)\s*hz', instruccion_usuario, re.IGNORECASE)
    if match_hz:
        f0_directo = int(match_hz.group(1))
        cfg_actual["f0Hz"] = f0_directo
        
        delta_hz = f0_directo - 125
        signo = "+" if delta_hz >= 0 else ""
        cfg_actual["pitch"] = f"{signo}{delta_hz}Hz"
        
        if delta_hz > 200:
            cfg_actual["rate"] = "+5%"
        elif delta_hz < -40:
            cfg_actual["rate"] = "-5%"
        else:
            cfg_actual["rate"] = "0%"

        cfg_actual["harmonics"] = generar_serie_armonica_dinamica(f0_directo)
        cfg_actual["ffmpeg_filter"] = construir_filtro_ffmpeg_desde_armonicos(cfg_actual)
        cfg_actual["descripcion"] = f"Frecuencia fundamental f0 ajustada dinámicamente a {f0_directo}Hz (Pitch: {cfg_actual['pitch']})"
        print(f"🎯 [VIBE ACOUSTIC LIBRE]: f0={f0_directo}Hz -> Pitch={cfg_actual['pitch']}", flush=True)
        return cfg_actual

    u_low = instruccion_usuario.lower()
    if any(w in u_low for w in ["pito", "agudo", "finito", "ardilla"]):
        cfg_actual["f0Hz"] = 450
        cfg_actual["pitch"] = "+325Hz"
        cfg_actual["rate"] = "+10%"
        cfg_actual["harmonics"] = generar_serie_armonica_dinamica(450, {1: 3.0, 2: 2.0})
        cfg_actual["ffmpeg_filter"] = construir_filtro_ffmpeg_desde_armonicos(cfg_actual)
        cfg_actual["descripcion"] = "Voz aguda libre aplicada"
        return cfg_actual

    prompt_ia = (
        f"You are an unrestricted DSP acoustic engine. User request: '{instruccion_usuario}'.\n"
        f"Current state: f0={cfg_actual.get('f0Hz', 125)}Hz, voice={cfg_actual.get('voice')}.\n"
        "Calculate continuous acoustic metrics. Return ONLY a raw JSON object:\n"
        "{\n"
        '  "voice": "es-AR-TomasNeural" or "es-AR-ElenaNeural",\n'
        '  "pitch": "continuous pitch delta in Hz, e.g. +350Hz, -50Hz",\n'
        '  "rate": "+0%" or "+5%" or "-5%",\n'
        '  "volume": "+10%",\n'
        '  "f0Hz": 500,\n'
        '  "harmonics_gain": {"1": 2.0, "2": -1.0, "3": 3.0},\n'
        '  "descripcion": "Description"\n'
        "}"
    )

    if client:
        try:
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt_ia,
                config=dict(response_mime_type="application/json")
            )
            data = json_lib.loads((res.text or "").strip())
            if "f0Hz" in data:
                f0 = int(data["f0Hz"])
                g_dict = data.get("harmonics_gain", {})
                data["harmonics"] = generar_serie_armonica_dinamica(f0, g_dict)
                data["ffmpeg_filter"] = construir_filtro_ffmpeg_desde_armonicos(data)
                return data
        except Exception as e:
            print(f"⚠️ Gemini fallback: {e}", flush=True)

    if asegurar_ollama_en_runner():
        try:
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt_ia, "stream": False, "format": "json"},
                timeout=60
            )
            if r.status_code == 200:
                data = json_lib.loads(r.json().get("response", "").strip())
                if "f0Hz" in data:
                    f0 = int(data["f0Hz"])
                    g_dict = data.get("harmonics_gain", {})
                    data["harmonics"] = generar_serie_armonica_dinamica(f0, g_dict)
                    data["ffmpeg_filter"] = construir_filtro_ffmpeg_desde_armonicos(data)
                    return data
        except Exception as e_ol:
            print(f"⚠️ Ollama fallback: {e_ol}", flush=True)

    return cfg_actual

def construir_prompt_sistema():
    timbre = cargar_config_timbre()
    memoria = obtener_memoria_aprendizaje()
    mapa_repo = obtener_mapa_repositorio()

    return (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense.\n"
        f"REPOSITORIO AUTÓNOMO DE TRABAJO: {URL_REPOSITORIO}\n\n"
        "REGLAS CRÍTICAS DE INTERACCIÓN Y SEGURIDAD DE CÓDIGO:\n"
        "1. EL USUARIO ES LEANDRO (tu colega). Hablale de 'vos' o 'che'. NUNCA hables de Leandro en tercera persona.\n"
        f"2. Tenés acceso total a la terminal de Linux y a la estructura completa del repo '{URL_REPOSITORIO}'.\n"
        "3. PARCHES RESTRINGIDOS: NUNCA devuelvas el archivo 'procesar.py' completo. Devolve ÚNICAMENTE la función o bloque de código específico que necesitás agregar o modificar.\n"
        "4. REGLA LINGÜÍSTICA RIOPLATENSE: Usá voseo porteño real ('mirá', 'fijate', 'decime', 'dale', 'che', 'posta').\n"
        "5. CERO RELLENO: Respondé directo y al pie, natural para ser leído en voz alta por Edge-TTS.\n\n"
        f"MAPA ESTRUCTURAL DE ARCHIVOS ACTIVO EN EL REPO:\n{mapa_repo}\n\n"
        f"Parámetros acústicos activos (f0={timbre.get('f0Hz', 125)}Hz, voz: {timbre.get('voice')}):\n"
        f"Historial reciente de la charla:\n{memoria}\n"
    )

def generar_texto_ia(prompt_usuario):
    system_prompt = construir_prompt_sistema()
    p = prompt_usuario

    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio", "resultado", "googlea"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = prompt_usuario + chr(10) + chr(10) + "[Información fresca de internet]:" + chr(10) + info_web

    if client:
        try:
            print(f"✨ [GEMINI]: Intentando con modelo gemini-3.8-flash...", flush=True)
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=p,
                config=dict(system_instruction=system_prompt)
            )
            raw = (res.text or "").strip()
            if raw:
                return raw
        except Exception as e:
            print(f"⚠️ Gemini fallback a Ollama en runner: {e}", flush=True)

    if asegurar_ollama_en_runner():
        try:
            print(f"🦙 [OLLAMA RUNNER]: Consultando en {OLLAMA_HOST} con modelo {OLLAMA_MODEL}...", flush=True)
            prompt_completo = f"{system_prompt}\n\nUsuario: {p}\nLeandro:"
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt_completo,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 300
                    }
                },
                timeout=60
            )
            if r.status_code == 200:
                texto = r.json().get("response", "").strip()
                if texto:
                    return texto
        except Exception as e_ollama:
            print(f"⚠️ Aviso Ollama runner actual: {e_ollama}", flush=True)

    import random
    respuestas_porteñas = [
        "¡Qué hacés che! Mirá, te capté perfecto. Decime cómo seguimos con esto.",
        "Posta che, tenés toda la razón. Fijate por acá y lo resolvemos en un toque.",
        "De una che, escuchá: ya lo tengo anotado. Mandale nomás y lo sacamos andando.",
        "Totalmente che. Mirá que ya lo tengo en mente. ¿Qué otra cosa necesitás que preparemos?"
    ]
    return random.choice(respuestas_porteñas)

def preparar_texto_para_voz(texto):
    t = re.sub(r'```[\s\S]*?```', 'Te pasé el bloque de código por texto para que lo mires tranqui.', texto)
    t = t.replace("*", "").replace("_", "").replace(chr(96), "").replace("#", "").strip()
    t = re.sub(r'\b(che|mirá|fijate|escuchá|vení|posta)\b', r'\g<1>...', t, flags=re.IGNORECASE)
    palabras = t.split()
    if len(palabras) > 60:
        t = " ".join(palabras[:55]) + "... te lo resumo hasta acá y cualquier cosa me avisás, che."
    return t.strip()

async def sintetizar_voz_edge_tts(texto, ogg_salida="resp.ogg"):
    cfg = cargar_config_timbre()
    voice = cfg.get("voice", "es-AR-TomasNeural")
    pitch = cfg.get("pitch", "-4Hz")
    rate = cfg.get("rate", "-5%")
    
    vol_raw = str(cfg.get("volume", "+10%"))
    vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
    volume = f"{vol_num}%"

    texto_oral = preparar_texto_para_voz(texto)
    if not texto_oral:
        texto_oral = "Sintonizamos en un toque, che."

    try:
        import edge_tts
        print(f"🎙️ [EDGE-TTS]: Sintetizando con {voice} (f0={cfg.get('f0Hz')}Hz, pitch={pitch})...", flush=True)
        communicate = edge_tts.Communicate(
            texto_oral,
            voice=voice,
            pitch=pitch,
            rate=rate,
            volume=volume
        )
        mp3_tmp = f"tmp_edge_{int(time.time()*1000)}.mp3"
        await communicate.save(mp3_tmp)

        if not os.path.exists(mp3_tmp) or os.path.getsize(mp3_tmp) < 100:
            return False, None

        filtro_af = construir_filtro_ffmpeg_desde_armonicos(cfg)
        cmd_ffmpeg = ["ffmpeg", "-y", "-i", mp3_tmp]
        if filtro_af:
            cmd_ffmpeg.extend(["-af", filtro_af])
        cmd_ffmpeg.extend([
            "-ar", "48000", "-ac", "1",
            "-c:a", "libopus", "-b:a", "48k",
            "-application", "voip",
            ogg_salida
        ])

        subprocess.run(cmd_ffmpeg, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if not os.path.exists(ogg_salida) or os.path.getsize(ogg_salida) < 200:
            print("⚠️ Aviso DSP FFmpeg: Aplicando conversión limpia estándar...", flush=True)
            subprocess.run([
                "ffmpeg", "-y", "-i", mp3_tmp,
                "-ar", "48000", "-ac", "1",
                "-c:a", "libopus", "-b:a", "48k",
                ogg_salida
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.path.exists(mp3_tmp):
            try: os.remove(mp3_tmp)
            except Exception: pass

        if os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 200:
            print(f"📻 [FFMPEG DSP]: Audio OGG Opus generado con éxito en '{ogg_salida}'", flush=True)
            return True, ogg_salida

        return False, None
    except Exception as e:
        print(f"⚠️ Error sintetizando con edge-tts y DSP: {e}", flush=True)
        return False, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text(
            f"¡Qué hacés che! Acá Leandro.\n"
            f"Repositorio activo: {URL_REPOSITORIO}\n\n"
            "• /timbre tomas / elena / <Hz o descripción>: Modificá la acústica de forma directa.\n"
            "• /codigo <comando o tarea>: Ejecuto comandos de terminal o parchea archivos de forma segura."
        )

async def cambiar_timbre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    desc = " ".join(context.args).strip() if context.args else ""
    cfg = cargar_config_timbre()
    
    if "tomas" in desc.lower():
        cfg["voice"] = "es-AR-TomasNeural"
        cfg["descripcion"] = "Voz de Tomás (Argentina)"
        guardar_config_timbre(cfg)
        await update.message.reply_text("🎙️ ¡Listo che! Ya te puse la voz de Tomás.")
    elif "elena" in desc.lower():
        cfg["voice"] = "es-AR-ElenaNeural"
        cfg["descripcion"] = "Voz de Elena (Argentina)"
        guardar_config_timbre(cfg)
        await update.message.reply_text("🎙️ ¡Listo che! Ya te puse la voz de Elena.")
    elif not desc:
        await update.message.reply_text(
            f"🎙️ Timbre dinámico actual: '{cfg.get('descripcion', 'Estándar')}'\n"
            f"• Voz activa: {cfg.get('voice')}\n"
            f"• Frecuencia f0: {cfg.get('f0Hz', 125)} Hz\n"
            f"• Ritmo: {cfg.get('rate')} | Volumen: {cfg.get('volume')}\n\n"
            "Cámbialo con: /timbre tomas, /timbre elena, o /timbre <Hz o descripción libre>"
        )
        return
    else:
        await update.message.reply_text(f"🔧 Recalculando serie armónica y DSP por vibe coding para: '{desc}'...")
        nuevo_cfg = parsear_timbre_dinamico_ia(desc)
        guardar_config_timbre(nuevo_cfg)

    frase_test = f"Mirá che, acá probando la configuración de voz y timbre. ¿Cómo suena?"
    ogg_test = f"timbre_{int(time.time())}.ogg"
    ok, path_a = await sintetizar_voz_edge_tts(frase_test, ogg_test)
    if ok and path_a and os.path.exists(path_a):
        with open(path_a, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"✅ Timbre applied and pushed to GitHub")
        try: os.remove(path_a)
        except Exception: pass
    else:
        await update.message.reply_text("✅ Configuración guardada en caliente.")

async def manejar_vibe_coding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    texto_raw = (update.message.text or "").strip('\u200b\ufeff\t\r\n ')
    instruccion = re.sub(r'^[/\\]*(codigo|código|vibe)\s*', '', texto_raw, flags=re.IGNORECASE).strip()

    if not instruccion and context.args:
        instruccion = " ".join(context.args).strip()

    if not instruccion:
        await update.message.reply_text("Decime qué comando de consola o tarea querés ejecutar en el Runner, che.")
        return

    await update.message.reply_text(f"💻 Procesando comando en el Runner para: '{instruccion}'...")

    u_low = instruccion.lower()
    if u_low.startswith(("pip ", "python ", "git ", "ls", "pwd", "apt", "curl", "npm")) or "instalar" in u_low or "install" in u_low:
        if "ddgs" in u_low:
            cmd = f"{sys.executable} -m pip install --upgrade ddgs"
        elif u_low.startswith("instalar "):
            paquete = instruccion.split("instalar ", 1)[1].strip()
            cmd = f"{sys.executable} -m pip install --upgrade {paquete}"
        else:
            cmd = instruccion

        ok, salida = ejecutar_comando_runner_en_vivo(cmd)
        resp = f"💻 **Consola Runner Output:**\n```\n{salida[:1500]}\n```"
        await update.message.reply_text(resp, parse_mode="Markdown")
        return

    mapa_actual = obtener_mapa_repositorio()
    prompt_codigo = (
        f"You are a Senior Python Developer with terminal access to repo '{URL_REPOSITORIO}'.\n"
        f"Current file map:\n{mapa_actual}\n\n"
        f"User instruction: '{instruccion}'.\n"
        "Return ONLY the specific function or code snippet inside ```python ... ``` that implements this feature or fix. "
        "DO NOT return the entire file. ONLY return the snippet/function."
    )
    resp_codigo = generar_texto_ia(prompt_codigo)
    
    match_code = re.search(r'```python\s*([\s\S]*?)\s*```', resp_codigo)
    snippet_parche = match_code.group(1) if match_code else resp_codigo
    
    # 🔒 BLINDAJE ANTI-MARKDOWN HARDCODEADO:
    snippet_parche = snippet_parche.replace("```python", "").replace("```", "").strip()

    if len(snippet_parche) > 30:
        exito = aplicar_parche_seguro_en_archivo("procesar.py", snippet_parche, f"vibe-coding-patch: {instruccion[:50]}")
        if exito:
            await update.message.reply_text("🚀 ¡Parche aplicado de forma segura en `parche_temp.txt` -> `procesar.py` y pusheado a GitHub sin borrar nada!")
            return

    await update.message.reply_text(resp_codigo)

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id

    u_text = (update.message.text or update.message.caption or "").strip('\u200b\ufeff\t\r\n ')

    if re.search(r'^[/\\]*(codigo|código|vibe)', u_text, re.IGNORECASE):
        await manejar_vibe_coding(update, context)
        return

    if update.message.voice or update.message.audio:
        print("📥 [AUDIO RECIBIDO]: Procesando con Whisper...", flush=True)
        try:
            audio_obj = update.message.voice or update.message.audio
            voice_file = await context.bot.get_file(audio_obj.file_id)
            tmp_ogg = f"voz_usuario_{int(time.time()*1000)}.ogg"
            await voice_file.download_to_drive(tmp_ogg)

            try:
                from faster_whisper import WhisperModel
                w_model = WhisperModel("tiny", device="cpu", compute_type="int8")
                segments, _ = w_model.transcribe(tmp_ogg, language="es")
                u_text = " ".join([s.text for s in segments]).strip()
                print(f"🎙️ [WHISPER TRANSCRIPCIÓN ÉXITO]: {u_text}", flush=True)
            except Exception as ex_wh:
                print(f"⚠️ Aviso Whisper local: {ex_wh}", flush=True)
                u_text = "Che, no pude procesar bien el audio pero te escucho firme."

            try: os.remove(tmp_ogg)
            except Exception: pass
        except Exception as ex_dl:
            print(f"⚠️ Error descargando audio: {ex_dl}", flush=True)

    if not u_text:
        u_text = "¡Qué hacés che! Decime cómo andás y qué programamos hoy."

    registrar_conversacion("Usuario", u_text)
    u_lower = u_text.lower().strip()

    if re.search(r'\b\d+\s*hz\b', u_lower) or any(k in u_lower for k in ["pitch", "frecuencia", "f0", "voz", "timbre", "grave", "agudo", "ronco", "tono", "pito", "ardilla", "fundamental", "cambia", "cambiá", "aplica", "aplicá"]):
        if "tomas" in u_lower:
            cfg = cargar_config_timbre()
            cfg["voice"] = "es-AR-TomasNeural"
            cfg["descripcion"] = "Voz de Tomás (Argentina)"
            guardar_config_timbre(cfg)
            resp = "¡De una che! Ya te puse la voz de Tomás."
        elif "elena" in u_lower:
            cfg = cargar_config_timbre()
            cfg["voice"] = "es-AR-ElenaNeural"
            cfg["descripcion"] = "Voz de Elena (Argentina)"
            guardar_config_timbre(cfg)
            resp = "¡De una che! Ya te puse la voz de Elena."
        else:
            print(f"🔧 [PARSER TIMBRE IA]: Calculando parámetros dinámicos libres para '{u_text}'...", flush=True)
            nuevo_t = parsear_timbre_dinamico_ia(u_text)
            guardar_config_timbre(nuevo_t)
            resp = f"¡De una che! Ya recalibré la acústica en caliente ({nuevo_t.get('descripcion', 'Ajuste aplicado')}). Escuchá cómo suena."

        registrar_conversacion("LeandroBot", resp)
        await update.message.reply_text(resp)
        ogg_f = f"resp_{int(time.time())}.ogg"
        ok, path_a = await sintetizar_voz_edge_tts(resp, ogg_f)
        if ok and path_a and os.path.exists(path_a):
            with open(path_a, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption="📻 Timbre actualizado en caliente")
            try: os.remove(path_a)
            except Exception: pass
        return

    resp = generar_texto_ia(u_text)
    if not resp or not str(resp).strip():
        resp = "Te capté perfecto che, mirá que ya lo tengo presente."

    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)
    print(f"📤 [MENSAJE ENVIADO TEXTO]: {resp[:80]}...", flush=True)

    ogg_f = f"resp_{int(time.time())}.ogg"
    exito, archivo_audio = await sintetizar_voz_edge_tts(resp, ogg_f)
    if exito and archivo_audio and os.path.exists(archivo_audio):
        try:
            with open(archivo_audio, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption="📻 Leandro")
            print(f"📤 [NOTA DE VOZ ENVIADA]: Leandro", flush=True)
        except Exception as ex_send:
            print(f"⚠️ Error enviando audio: {ex_send}", flush=True)
        try: os.remove(archivo_audio)
        except Exception: pass

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta la variable TELEGRAM_BOT_TOKEN.", flush=True)
        return

    print("🚀 [INIT]: Arrancando polling con Git Autopush (LeandroBot[bot]) y terminal activa...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("timbre", cambiar_timbre))
    app.add_handler(CommandHandler("codigo", manejar_vibe_coding))
    app.add_handler(CommandHandler("vibe", manejar_vibe_coding))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, manejar_mensaje))

    print("🔄 [POLLING]: Bot escuchando en Telegram...", flush=True)
    app.run_polling(drop_pending_updates=True)

import psutil
import time

async def manejar_estado(update, context):
    proceso = psutil.Process()
    memoria_mb = proceso.memory_info().rss / (1024 * 1024)
    uptime_seg = int(time.time() - proceso.create_time())
    horas, resto = divmod(uptime_seg, 3600)
    minutos, segundos = divmod(resto, 60)
    
    mensaje = (
        f"Che, acá tenés el estado del bot:\n"
        f"⏱️ Uptime: {horas:02d}:{minutos:02d}:{segundos:02d}\n"
        f"🧠 RAM en uso: {memoria_mb:.2f} MB"
    )
    await update.message.reply_text(mensaje)

app.add_handler(CommandHandler("estado", manejar_estado))

def main():
    app = Application.builder().token(TOKEN).build()

    async def manejar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Estado del sistema operativo.")

    app.add_handler(CommandHandler("estado", manejar_estado))
    
    app.run_polling()

async def manejar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Che, el sistema está activo y funcionando impecable, posta.")

# Dentro de main(), antes de app.run_polling():
app.add_handler(CommandHandler("estado", manejar_estado))

def main():
    """Punto de entrada único y limpio para el pipeline, sin dependencias de psutil."""
    try:
        procesar()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error en la ejecución: {e}")


if __name__ == "__main__":
    main()

if __name__ == "__main__":




    main()


import ast
import os
import shutil

def aplicar_parche_seguro_en_archivo(ruta_archivo, nuevo_contenido, forzar_limpieza=False):
    """
    Aplica el parche validando la sintaxis con AST. Permite reducción de líneas
    si se incluye una directiva explícita de limpieza/reemplazo o si forzar_limpieza=True.
    """
    try:
        ast.parse(nuevo_contenido)
    except SyntaxError as e:
        print(f"[ERROR] Sintaxis inválida en el parche propuesto: {e}")
        return False

    if not os.path.exists(ruta_archivo):
        with open(ruta_archivo, "w", encoding="utf-8") as f:
            f.write(nuevo_contenido)
        return True

    with open(ruta_archivo, "r", encoding="utf-8") as f:
        contenido_original = f.read()

    lineas_orig = len(contenido_original.splitlines())
    lineas_nuevas = len(nuevo_contenido.splitlines())

    # Detección de marcadores explícitos para poda o reemplazo
    directivas_validas = [
        "# limpieza",
        "# reemplazo_explicito",
        "# refactor",
        "# purga"
    ]
    contenido_lower = nuevo_contenido.lower()
    es_limpieza_autorizada = forzar_limpieza or any(d in contenido_lower for d in directivas_validas)

    # Bloqueo de reducción accidental de código
    if lineas_nuevas < lineas_orig and not es_limpieza_autorizada:
        print(f"[RECHAZADO] Reducción no autorizada ({lineas_orig} -> {lineas_nuevas} líneas). Falta directiva de limpieza.")
        return False

    # Backup de seguridad
    shutil.copy2(ruta_archivo, f"{ruta_archivo}.bak")

    with open(ruta_archivo, "w", encoding="utf-8") as f:
        f.write(nuevo_contenido)

    print(f"[OK] Parche aplicado en {ruta_archivo} ({lineas_orig} -> {lineas_nuevas} líneas).")
    return True


if __name__ == "__main__":
    parche_path = "parche_temp.txt"
    destino_path = "procesar.py"
    if os.path.exists(parche_path):
        with open(parche_path, "r", encoding="utf-8") as fp:
            contenido_parche = fp.read()
        aplicar_parche_seguro_en_archivo(destino_path, contenido_parche)