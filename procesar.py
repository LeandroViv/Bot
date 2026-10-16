# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / Vibe Coding & Serie Armónica Dinámica en Hz (FFmpeg DSP + Edge-TTS)

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

print("🚀 [INIT]: Inicializando LeandroBot con Motor de Vibe Coding y Serie Armónica Dinámica...", flush=True)

TXT_FILE = "conversaciones.txt"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
PERFIL_DINAMICO = "perfil_personaje.json"

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
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2.0)
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
            return True
    except Exception as ex:
        print(f"⚠️ Aviso conexión Ollama en runner: {ex}", flush=True)
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
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                lineas = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
                return chr(10).join(lineas)
    except Exception as e:
        print(f"⚠️ Aviso búsqueda web: {e}", flush=True)
    return ""

def generar_serie_armonica_dinamica(f0_hz, ganancias=None):
    """Calcula algorítmicamente la serie armónica completa en Hz a partir de la fundamental f0."""
    f0 = max(60, min(450, int(f0_hz)))
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
    """Construye los filtros DSP de FFmpeg en base a la serie armónica y ecualización paramétrica calculada."""
    partes = []
    harmonics = cfg.get("harmonics", [])
    for h in harmonics:
        if h.get("enabled", True) and h.get("gainDb", 0) != 0:
            hz = h.get("hz", 0)
            gain = max(-24.0, min(18.0, float(h.get("gainDb", 0))))
            q = max(0.5, min(6.0, float(h.get("q", 2.0))))
            if 20 < hz < 22000:
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
            tempo = max(0.6, min(1.8, round(1.0 + r_pct / 100.0, 2)))
            if tempo != 1.0:
                partes.append(f"atempo={tempo}")
    except Exception:
        pass

    return ",".join(partes)

def parsear_timbre_dinamico_ia(descripcion_natural):
    """Usa vibe coding por IA para interpretar la descripción y calcular f0, ritmo, volumen y armónicos exactos en Hz."""
    prompt_ia = (
        f"Sos un ingeniero de sonido experto en DSP y síntesis de voz. El usuario solicita este perfil acústico: '{descripcion_natural}'.\n"
        "Calculá de forma dinámica y devolvé UNICAMENTE un objeto JSON válido (sin markdown) con esta estructura exacta:\n"
        "{\n"
        '  "voice": "es-AR-TomasNeural" o "es-AR-ElenaNeural",\n'
        '  "pitch": "valor en Hz o semitonos para edge-tts (ej: -4Hz)",\n'
        '  "rate": "porcentaje de ritmo (ej: -5%)",\n'
        '  "volume": "porcentaje de volumen (ej: +10%)",\n'
        '  "f0Hz": 125,\n'
        '  "harmonics_gain": {"1": 2.5, "2": -1.0, "3": 4.0},\n'
        '  "descripcion": "Descripción detallada del timbre"\n'
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
            print(f"⚠️ Aviso parser IA timbre: {e}", flush=True)

    # Generación algorítmica de respaldo si no responde la API
    f0_def = 115 if any(w in descripcion_natural.lower() for w in ["grave", "ronco", "nocturno"]) else 125
    harmonics_def = generar_serie_armonica_dinamica(f0_def, {1: 3.0, 2: 1.5})
    fallback_cfg = {
        "voice": "es-AR-TomasNeural",
        "pitch": "-4Hz",
        "rate": "-5%",
        "volume": "+10%",
        "f0Hz": f0_def,
        "harmonics": harmonics_def,
        "descripcion": descripcion_natural
    }
    fallback_cfg["ffmpeg_filter"] = construir_filtro_ffmpeg_desde_armonicos(fallback_cfg)
    return fallback_cfg

def construir_prompt_sistema():
    timbre = cargar_config_timbre()
    memoria = obtener_memoria_aprendizaje()

    return (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense.\n"
        "INSTRUCCIONES CLAVE:\n"
        "1. NO SOS UN ROBOT NI TENÉS RESPUESTAS PREFABRICADAS: Adaptá tu estilo aprendiendo de la conversación del usuario.\n"
        "2. REGLA LINGÜÍSTICA RIOPLATENSE: Hablá con voseo porteño real, yeísmo rehilado, e imperativos agudos acentuados: "
        "'mirá', 'vení', 'decime', 'escuchá', 'pasame', 'hacé', 'fijate', 'poné', 'dale', 'posta', 'che'.\n"
        "3. RITMO Y CADENCIA ORAL: Escribí usando comas y puntos suspensivos para dar respiración y ritmo natural al leerse en voz alta.\n"
        "4. VIBE CODING: Si te piden programar, corregir, modificar o crear código de cualquier tipo, respondé con código limpio, "
        "bien explicado y listo para usar en producción.\n"
        "5. SIN SPAM: Respondé únicamente a lo que te pide el usuario, sin automatizar mensajes ni relleno innecesario.\n\n"
        f"Parámetros acústicos dinámicos activos (f0={timbre.get('f0Hz', 125)}Hz, timbre: '{timbre.get('descripcion', 'Dinámico')}'):\n"
        f"Historial de charlas previas con el usuario (aprendizaje continuo):\n{memoria}\n"
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
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/chat",
                json={"model": OLLAMA_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": p}]},
                timeout=30
            )
            if r.status_code == 200:
                texto = r.json().get("message", {}).get("content", "").strip()
                if texto:
                    return texto
        except Exception as e_ollama:
            print(f"⚠️ Aviso Ollama runner chat: {e_ollama}", flush=True)

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
    if "db" in vol_raw.lower():
        vol_num = re.sub(r'[^0-9+-]', '', vol_raw)
        volume = f"{vol_num}%"
    else:
        volume = vol_raw

    texto_oral = preparar_texto_para_voz(texto)
    if not texto_oral:
        texto_oral = "Sintonizamos en un toque, che."

    try:
        import edge_tts
        print(f"🎙️ [EDGE-TTS + DSP]: Sintetizando (f0={cfg.get('f0Hz', 125)}Hz, vol={volume}, rate={rate})...", flush=True)
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

        # Aplicar el filtro dinámico de serie armónica en Hz y ecualización con FFmpeg
        filtro_af = cfg.get("ffmpeg_filter") or construir_filtro_ffmpeg_desde_armonicos(cfg)
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

        if os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 200:
            try: os.remove(mp3_tmp)
            except Exception: pass
            print(f"📻 [FFMPEG DSP]: Serie armónica en Hz aplicada con éxito en '{ogg_salida}'", flush=True)
            return True, ogg_salida

        return True, mp3_tmp
    except Exception as e:
        print(f"⚠️ Error sintetizando con edge-tts y DSP: {e}", flush=True)
        return False, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text(
            "¡Qué hacés che! Acá Leandro. Motor de Vibe Coding y Serie Armónica en Hz activo.\n\n"
            "• /timbre <descripción>: Modificá en tiempo real el pitch, ritmo, volumen y la serie armónica en Hz por lenguaje natural.\n"
            "• /codigo <tarea>: Escribo o modifico código de forma autónoma."
        )

async def cambiar_timbre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    desc = " ".join(context.args).strip() if context.args else ""
    if not desc:
        cfg = cargar_config_timbre()
        harm_res = ", ".join([f"H{h['order']}@{h['hz']}Hz({h['gainDb']}dB)" for h in cfg.get("harmonics", [])[:5]])
        await update.message.reply_text(
            f"🎙️ Timbre dinámico actual: '{cfg.get('descripcion', 'Estándar')}'\n"
            f"• Frecuencia fundamental f0: {cfg.get('f0Hz', 125)} Hz\n"
            f"• Ritmo: {cfg.get('rate')} | Volumen: {cfg.get('volume')}\n"
            f"• Armónicos principales: {harm_res}...\n\n"
            "Cámbialo con: /timbre <descripción acústica>"
        )
        return

    await update.message.reply_text(f"🔧 Recalculando serie armónica y DSP por vibe coding para: '{desc}'...")
    nuevo_cfg = parsear_timbre_dinamico_ia(desc)
    guardar_config_timbre(nuevo_cfg)

    frase_test = f"Mirá che, acá aplicando la nueva serie armónica y ecualización que me pediste. ¿Cómo suena?"
    ogg_test = f"timbre_{int(time.time())}.ogg"
    ok, path_a = await sintetizar_voz_edge_tts(frase_test, ogg_test)
    if ok and path_a and os.path.exists(path_a):
        with open(path_a, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"✅ Timbre dinámico aplicado: '{desc}'")
        try: os.remove(path_a)
        except Exception: pass
    else:
        await update.message.reply_text("✅ Parámetros acústicos actualizados correctamente.")

async def manejar_vibe_coding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    instruccion = " ".join(context.args).strip() if context.args else ""
    if not instruccion:
        await update.message.reply_text("Decime qué querés programar o modificar, che.")
        return

    await update.message.reply_text(f"💻 Analizando vibe coding para: '{instruccion}'...")
    resp_codigo = generar_texto_ia(f"VIBE CODING: {instruccion}. Generá la solución o modificación de código completa y limpia.")
    await update.message.reply_text(resp_codigo)

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id
    u_text = update.message.text or update.message.caption or "[Audio/Nota de voz]"
    registrar_conversacion("Usuario", u_text)

    if any(k in u_text.lower() for k in ["cambiá la voz", "cambia la voz", "cambiá el timbre", "cambia el timbre", "poné la voz", "pone la voz"]):
        desc_limpia = re.sub(r'(cambi[aá]s+(las+voz|els+timbre)|pon[eé]s+las+voz)s*(a|en|como)?', '', u_text, flags=re.IGNORECASE).strip()
        if len(desc_limpia) > 4:
            nuevo_t = parsear_timbre_dinamico_ia(desc_limpia)
            guardar_config_timbre(nuevo_t)
            resp = f"¡De una che! Ya recalibré la acústica para que suene '{desc_limpia}'."
            registrar_conversacion("LeandroBot", resp)
            await update.message.reply_text(resp)
            ogg_f = f"resp_{int(time.time())}.ogg"
            ok, path_a = await sintetizar_voz_edge_tts(resp, ogg_f)
            if ok and path_a and os.path.exists(path_a):
                with open(path_a, "rb") as vf:
                    await update.message.reply_voice(voice=vf, caption="📻 Timbre recalculado")
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

    print("🚀 [INIT]: Arrancando polling con motor acústico dinámico...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("timbre", cambiar_timbre))
    app.add_handler(CommandHandler("codigo", manejar_vibe_coding))
    app.add_handler(CommandHandler("vibe", manejar_vibe_coding))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, manejar_mensaje))

    print("🔄 [POLLING]: Bot escuchando en Telegram...", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
