# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot / Tomás: Vibe Coding & Timbre Dinámico Edge-TTS + Logs Visibles

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

print("🚀 [INIT]: Inicializando Bot Adaptativo (Vibe Coding + Timbre es-AR-Tomas + Ollama + Logs Activos)...", flush=True)

TXT_FILE = "conversaciones.txt"
DATASET_ENTRENAMIENTO = "dataset_entrenamiento_chat.json"
CONFIG_TIMBRE = "config_timbre.json"
PERFIL_DINAMICO = "perfil_personaje.json"

for f_path, default_val in [
    (TXT_FILE, ""),
    (DATASET_ENTRENAMIENTO, []),
    (PERFIL_DINAMICO, {
        "nombre": "Tomás",
        "estilo": "Colega y compañero de vibe coding con tonada rioplatense, voz cálida de radio y ritmo auténtico",
        "notas_aprendizaje": []
    }),
    (CONFIG_TIMBRE, {
        "voice": "es-AR-TomasNeural",
        "pitch": "-4Hz",
        "rate": "-5%",
        "volume": "+0%",
        "descripcion": "Tomás: Locutor nocturno porteño con barítono cálido, pausado y presencia de radio"
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

def asegurar_ollama_levantado():
    """Verifica si Ollama está respondiendo; si no, intenta levantarlo en background automáticamente."""
    try:
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=1.5)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        print("🦙 [OLLAMA AUTO-START]: Iniciando servidor ollama serve en background...", flush=True)
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(2)
        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception as ex:
        print(f"⚠️ Aviso comprobación Ollama: {ex}", flush=True)
        return False

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            return json_lib.load(f)
    except Exception:
        return {
            "voice": "es-AR-TomasNeural",
            "pitch": "-4Hz",
            "rate": "-5%",
            "volume": "+0%",
            "descripcion": "Tomás: Locutor porteño cálido"
        }

def guardar_config_timbre(cfg):
    try:
        with open(CONFIG_TIMBRE, "w", encoding="utf-8") as f:
            json_lib.dump(cfg, f, indent=4, ensure_ascii=False)
        print(f"🎙️ [TIMBRE GUARDADO]: {cfg}", flush=True)
    except Exception as e:
        print(f"⚠️ Error guardando timbre: {e}", flush=True)

def cargar_perfil_personaje():
    try:
        with open(PERFIL_DINAMICO, "r", encoding="utf-8") as f:
            return json_lib.load(f)
    except Exception:
        return {
            "nombre": "Tomás",
            "estilo": "Colega y compañero de vibe coding con tonada rioplatense"
        }

def guardar_perfil_personaje(nombre, estilo):
    try:
        data = {
            "nombre": nombre,
            "estilo": estilo,
            "actualizado": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(PERFIL_DINAMICO, "w", encoding="utf-8") as f:
            json_lib.dump(data, f, indent=4, ensure_ascii=False)
        print(f"👤 [PERSONAJE GUARDADO]: {nombre} - {estilo}", flush=True)
    except Exception as e:
        print(f"⚠️ Error guardando personaje: {e}", flush=True)

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
                print(f"🌐 [WEB SEARCH]: {query}", flush=True)
                return chr(10).join(lineas)
    except Exception as e:
        print(f"⚠️ Aviso búsqueda web: {e}", flush=True)
    return ""

def generar_serie_armonica_py(f0_hz, ganancias=None):
    f0 = max(60, min(450, int(f0_hz)))
    bandas = []
    ganancias = ganancias or {}
    for orden in range(1, 17):
        hz = orden * f0
        if hz > 22000:
            break
        g = float(ganancias.get(orden, 0))
        q = 1.5 if orden == 1 else (2.0 if orden <= 4 else 3.0)
        bandas.append({
            "order": orden,
            "hz": hz,
            "gainDb": g,
            "q": q,
            "enabled": True
        })
    return bandas

def construir_filtro_ffmpeg_armonicos(cfg):
    partes = []
    harmonics = cfg.get("harmonics", [])
    for h in harmonics:
        if h.get("enabled", True) and h.get("gainDb", 0) != 0:
            hz = h.get("hz", 0)
            gain = max(-24.0, min(18.0, float(h.get("gainDb", 0))))
            q = max(0.5, min(6.0, float(h.get("q", 2.0))))
            if 20 < hz < 22000:
                partes.append(f"equalizer=f={hz}:width_type=q:w={q}:g={gain}")

    vol_db = cfg.get("volume_gain_db", 0)
    if vol_db != 0:
        multiplier = round(10 ** (vol_db / 20.0), 2)
        partes.append(f"volume={multiplier}")

    rate_pct = cfg.get("rate_pct", 0)
    if rate_pct != 0:
        tempo = max(0.6, min(1.8, round(1.0 + rate_pct / 100.0, 2)))
        if tempo != 1.0:
            partes.append(f"atempo={tempo}")

    return ",".join(partes)

def parsear_timbre_con_lenguaje_natural(descripcion_natural):
    desc_l = descripcion_natural.lower().strip()
    es_elena = any(w in desc_l for w in ["elena", "mujer", "femenin", "chica", "locutora"])
    if any(w in desc_l for w in ["tomas", "tomás", "varon", "barítono", "baritono"]):
        es_elena = False

    voz_target = "es-AR-ElenaNeural" if es_elena else "es-AR-TomasNeural"
    persona_nombre = "Elena" if es_elena else "Tomás"
    f0_hz = 210 if es_elena else 125

    f0_m = re.search(r'\b(?:f0|fundamental)\s*[:=]?\s*(\d+)', desc_l)
    if f0_m:
        f0_hz = int(f0_m.group(1))
    else:
        if any(w in desc_l for w in ["muy grave", "bien grave", "cavernoso", "ronco"]):
            f0_hz = 185 if es_elena else 105
        elif any(w in desc_l for w in ["grave", "profundo", "nocturno"]):
            f0_hz = 195 if es_elena else 115
        elif any(w in desc_l for w in ["muy agudo", "chillón"]):
            f0_hz = 250 if es_elena else 160
        elif any(w in desc_l for w in ["agudo", "brillante", "cristal"]):
            f0_hz = 230 if es_elena else 140

    ganancias = {}
    h_matches = re.findall(r'\bh(\d{1,2})\s*[:=]?\s*([+-]?\d+(?:\.\d+)?)\s*(?:db)?', desc_l)
    for ord_s, g_s in h_matches:
        o = int(ord_s)
        if 1 <= o <= 16:
            ganancias[o] = float(g_s)

    bandas = generar_serie_armonica_py(f0_hz, ganancias)

    rate_pct = 0
    rm = re.search(r'\b(?:ritmo|velocidad|rate)\s*[:=]?\s*([+-]?\d+)\s*%?', desc_l)
    if rm:
        rate_pct = max(-35, min(50, int(rm.group(1))))

    vol_db = 0
    vm = re.search(r'\b(?:volumen|vol|ganancia)\s*[:=]?\s*([+-]?\d+)\s*(?:db)?', desc_l)
    if vm:
        vol_db = max(-15, min(15, int(vm.group(1))))

    delta_f0 = f0_hz - 210 if es_elena else f0_hz - 125
    edge_pitch = f"{delta_f0:+d}Hz" if delta_f0 != 0 else "0Hz"
    edge_rate = f"{rate_pct:+d}%" if rate_pct != 0 else "0%"
    edge_vol = f"{vol_db * 10:+d}%" if vol_db != 0 else "+0%"

    cfg_armonico = {
        "voice": voz_target,
        "personaName": persona_nombre,
        "f0Hz": f0_hz,
        "harmonics": bandas,
        "pitch": edge_pitch,
        "rate": edge_rate,
        "volume": edge_vol,
        "rate_pct": rate_pct,
        "volume_gain_db": vol_db,
        "descripcion": descripcion_natural.strip() or f"{persona_nombre}: Serie armónica f0={f0_hz}Hz",
        "breathPauses": "sin pausas" not in desc_l
    }
    cfg_armonico["ffmpeg_filter"] = construir_filtro_ffmpeg_armonicos(cfg_armonico)
    return cfg_armonico

def construir_prompt_sistema():
    timbre = cargar_config_timbre()
    memoria = obtener_memoria_aprendizaje()
    perfil = cargar_perfil_personaje()
    nombre_agente = perfil.get("nombre", "Tomás")
    estilo_agente = perfil.get("estilo", "Colega locutor y compañero de vibe coding con tonada rioplatense")

    return (
        f"Sos {nombre_agente}: {estilo_agente}.\n"
        "INSTRUCCIONES CLAVE:\n"
        "1. NO SOS UN ROBOT NI TENÉS RESPUESTAS PREFABRICADAS: Adaptá tu estilo aprendiendo de la conversación del usuario.\n"
        "2. REGLA LINGÜÍSTICA RIOPLATENSE: Hablá con voseo porteño real, yeísmo rehilado, e imperativos agudos acentuados: "
        "'mirá', 'vení', 'decime', 'escuchá', 'pasame', 'hacé', 'fijate', 'poné', 'dale', 'posta', 'che'.\n"
        "3. RITMO Y CADENCIA ORAL: Escribí usando comas y puntos suspensivos para dar respiración y ritmo natural al leerse en voz alta.\n"
        "4. VIBE CODING: Si te piden programar, corregir, modificar o crear código de cualquier tipo, respondé con código limpio, "
        "bien explicado y listo para usar en producción.\n"
        "5. SIN SPAM: Respondé únicamente a lo que te pide el usuario, sin automatizar mensajes ni relleno innecesario.\n\n"
        f"Timbre de voz activo solicitado: '{timbre.get('descripcion', 'Natural')}' (Voz: {timbre.get('voice', 'es-AR-TomasNeural')})\n\n"
        f"Historial de charlas previas con el usuario (aprendizaje continuo):\n{memoria}\n"
    )

def generar_texto_ia(prompt_usuario):
    """Genera respuesta priorizando Ollama local y haciendo fallback fluido a Gemini."""
    system_prompt = construir_prompt_sistema()
    p = prompt_usuario

    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio", "resultado", "googlea"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = prompt_usuario + chr(10) + chr(10) + "[Información fresca de internet]:" + chr(10) + info_web

    # Prioridad 1: Ollama local (evita bloqueos de nube 503/404)
    if asegurar_ollama_levantado():
        try:
            print(f"🦙 [OLLAMA]: Consultando a {OLLAMA_HOST} con modelo {OLLAMA_MODEL}...", flush=True)
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/chat",
                json={"model": OLLAMA_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": p}]},
                timeout=20
            )
            if r.status_code == 200:
                texto = r.json().get("message", {}).get("content", "").strip()
                if texto:
                    print(f"🦙 [OLLAMA CHAT]: ¡Éxito!", flush=True)
                    return texto
        except Exception as e_ollama:
            print(f"⚠️ Aviso Ollama chat: {e_ollama}", flush=True)

    # Prioridad 2: Gemini en cascada
    if client:
        modelos_a_probar = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        for mod in modelos_a_probar:
            try:
                print(f"✨ [GEMINI]: Intentando con modelo {mod}...", flush=True)
                res = client.models.generate_content(
                    model=mod,
                    contents=p,
                    config=dict(system_instruction=system_prompt)
                )
                raw = (res.text or "").strip()
                if raw:
                    print(f"✨ [GEMINI {mod}]: ¡Éxito!", flush=True)
                    return raw
            except Exception as e_mod:
                print(f"⚠️ Gemini {mod} aviso: {e_mod}", flush=True)
                continue

    # Fallback rioplatense por defecto
    import random
    respuestas_porteñas = [
        "¡Qué hacés che! Te escucho firme. Decime qué encaramos hoy con el código o de qué charlamos.",
        "Posta che, acá estoy en la consola. Decime cómo seguimos con esto y lo sacamos andando.",
        "De una che, escuchá: acá sintonizado con Tomás. ¿Qué necesitás que preparemos?"
    ]
    resp_fallback = random.choice(respuestas_porteñas)
    print(f"🤖 [FALLBACK LOCAL]: {resp_fallback}", flush=True)
    return resp_fallback

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
    volume = cfg.get("volume", "+0%")

    texto_oral = preparar_texto_para_voz(texto)
    if not texto_oral:
        texto_oral = "Sintonizamos en un toque, che."

    try:
        import edge_tts
        print(f"🎙️ [EDGE-TTS]: Generando audio con timbre '{cfg.get('descripcion', '')}' ({voice}, {pitch}, {rate}, vol={volume})...", flush=True)
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

        filtro_af = cfg.get("ffmpeg_filter") or construir_filtro_ffmpeg_armonicos(cfg)
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
        if not (os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 200):
            subprocess.run([
                "ffmpeg", "-y", "-i", mp3_tmp,
                "-ar", "48000", "-ac", "1",
                "-c:a", "libopus", "-b:a", "48k",
                "-application", "voip",
                ogg_salida
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 200:
            try: os.remove(mp3_tmp)
            except Exception: pass
            print(f"📻 [FFMPEG DSP]: Audio generado con éxito en '{ogg_salida}'", flush=True)
            return True, ogg_salida

        return True, mp3_tmp
    except Exception as e:
        print(f"⚠️ Error sintetizando con edge-tts: {e}", flush=True)
        return False, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        nombre = cargar_perfil_personaje().get("nombre", "Tomás")
        print(f"🚀 [START COMANDO]: Chat ID {CHAT_ID_ACTIVO} activado.", flush=True)
        await update.message.reply_text(
            f"¡Qué hacés che! Acá {nombre}. Estoy listo para charlar, hacer vibe coding o esculpir mi voz con armónicos y FFmpeg."
        )

async def activar_tomas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🎙️ [COMANDO /tomas]: Activando voz de Tomás...", flush=True)
    cfg = parsear_timbre_con_lenguaje_natural("voz de Tomás barítono porteño cálido de radio f0=125")
    guardar_config_timbre(cfg)
    guardar_perfil_personaje("Tomás", "Colega locutor y compañero de vibe coding")

    resp = "¡Qué hacés Leandro che! De una, acá Tomás al micrófono. Ya activé mi voz es-AR-Tomas al 100%."
    registrar_conversacion("Tomás", resp)
    await update.message.reply_text(resp)

    ogg_f = f"tomas_{int(time.time())}.ogg"
    ok, path_a = await sintetizar_voz_edge_tts(resp, ogg_f)
    if ok and path_a and os.path.exists(path_a):
        with open(path_a, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption="📻 Tomás (es-AR-TomasNeural)")
        try: os.remove(path_a)
        except Exception: pass

async def activar_elena_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🎙️ [COMANDO /elena]: Activando voz de Elena...", flush=True)
    cfg = parsear_timbre_con_lenguaje_natural("voz de Elena femenina rioplatense clara y expresiva f0=210")
    guardar_config_timbre(cfg)
    guardar_perfil_personaje("Elena", "Colega locutora porteña")

    resp = "¡Qué hacés Leandro! Acá Elena al micrófono. Ya quedé activada en es-AR-Elena al 100%."
    registrar_conversacion("Elena", resp)
    await update.message.reply_text(resp)

    ogg_f = f"elena_{int(time.time())}.ogg"
    ok, path_a = await sintetizar_voz_edge_tts(resp, ogg_f)
    if ok and path_a and os.path.exists(path_a):
        with open(path_a, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption="📻 Elena (es-AR-ElenaNeural)")
        try: os.remove(path_a)
        except Exception: pass

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id

    u_text = update.message.text or update.message.caption or ""

    if update.message.voice or update.message.audio:
        print("📥 [MENSAJE RECIBIDO]: Audio/Nota de voz detectada.", flush=True)
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
                print(f"🎙️ [WHISPER TRANSCRIPCIÓN]: {u_text}", flush=True)
            except Exception as ex_wh:
                print(f"⚠️ Aviso Whisper local: {ex_wh}", flush=True)

            try: os.remove(tmp_ogg)
            except Exception: pass
        except Exception as ex_dl:
            print(f"⚠️ Error procesando audio: {ex_dl}", flush=True)

    if not u_text:
        u_text = "¡Qué hacés che! Decime cómo andás y qué programamos hoy."

    registrar_conversacion("Usuario", u_text)
    u_lower = u_text.lower().strip()

    # Detección de comandos rápidos por texto
    if any(p in u_lower for p in ["sos elena", "voz elena", "cambia a elena", "cambiá a elena"]):
        await activar_elena_cmd(update, context)
        return

    if any(p in u_lower for p in ["sos tomas", "voz tomas", "cambia a tomas", "cambiá a tomas"]):
        await activar_tomas_cmd(update, context)
        return

    nombre_act = cargar_perfil_personaje().get("nombre", "Tomás")
    resp = generar_texto_ia(u_text)
    if not resp or not str(resp).strip():
        resp = f"Te capté perfecto che, acá {nombre_act} firme."

    registrar_conversacion(nombre_act, resp)
    await update.message.reply_text(resp)
    print(f"📤 [MENSAJE ENVIADO TEXTO]: {resp[:80]}...", flush=True)

    # Enviar nota de voz automática
    ogg_f = f"resp_{int(time.time())}.ogg"
    exito, archivo_audio = await sintetizar_voz_edge_tts(resp, ogg_f)
    if exito and archivo_audio and os.path.exists(archivo_audio):
        try:
            with open(archivo_audio, "rb") as vf:
                await update.message.reply_voice(voice=vf, caption=f"📻 {nombre_act}")
            print(f"📤 [NOTA DE VOZ ENVIADA]: {nombre_act}", flush=True)
        except Exception as ex_send:
            print(f"⚠️ Error enviando audio: {ex_send}", flush=True)
        try: os.remove(archivo_audio)
        except Exception: pass

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta la variable TELEGRAM_BOT_TOKEN.", flush=True)
        return

    print("🚀 [INIT]: Arrancando polling de Telegram con logs detallados...", flush=True)
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tomas", activar_tomas_cmd))
    app.add_handler(CommandHandler("elena", activar_elena_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, manejar_mensaje))

    print("🔄 [POLLING ACTIVO]: Bot escuchando mensajes...", flush=True)
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
