# -*- coding: utf-8 -*-
# Repositorio: https://github.com/LeandroViv/Bot
# Script: procesar.py - LeandroBot Vibe Coding & Timbre Dinámico

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

print("🚀 [INIT]: Inicializando LeandroBot Adaptativo (Vibe Coding + Timbre por Prompt + Aprendizaje)...")

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
        "descripcion": "Locutor nocturno porteño con barítono cálido, pausado y presencia de radio"
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

def cargar_config_timbre():
    try:
        with open(CONFIG_TIMBRE, "r", encoding="utf-8") as f:
            return json_lib.load(f)
    except Exception:
        return {
            "voice": "es-AR-TomasNeural",
            "pitch": "-4Hz",
            "rate": "-5%",
            "volume": "+10%",
            "descripcion": "Locutor porteño cálido"
        }

def guardar_config_timbre(cfg):
    try:
        with open(CONFIG_TIMBRE, "w", encoding="utf-8") as f:
            json_lib.dump(cfg, f, indent=4, ensure_ascii=False)
        print(f"🎙️ [TIMBRE GUARDADO]: {cfg}")
    except Exception as e:
        print(f"⚠️ Error guardando timbre: {e}")

def registrar_conversacion(remitente, texto):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {remitente}: {texto}" + chr(10))
    except Exception as e:
        print(f"⚠️ Error conversacion: {e}")

def obtener_memoria_aprendizaje():
    """Lee el historial reciente para que el personaje aprenda del usuario sin estar hardcodeado."""
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
    """Búsqueda web local y gratuita para GitHub Actions (sin API keys)."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                lineas = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
                return chr(10).join(lineas)
    except Exception as e:
        print(f"⚠️ Aviso búsqueda web: {e}")
    return ""

def parsear_timbre_con_lenguaje_natural(descripcion_natural):
    """Traduce cualquier descripción en lenguaje natural a parámetros de Edge-TTS usando IA."""
    prompt_ia = (
        f"Sos un director de sonido y acústica. El usuario quiere calibrar el timbre de voz con esta descripción: '{descripcion_natural}'.\n"
        "Configurá los parámetros exactos de Edge-TTS:\n"
        "- voice: 'es-AR-TomasNeural' (hombre porteño) o 'es-AR-ElenaNeural' (mujer porteña) o 'es-UY-MateoNeural' (uruguayo)\n"
        "- pitch: entre -12Hz (muy grave/ronco) y +10Hz (agudo/joven). Ejemplo: '-6Hz', '-2Hz', '+4Hz'\n"
        "- rate: entre -20% (muy pausado/nocturno) y +20% (muy rápido). Ejemplo: '-8%', '-3%', '+5%'\n"
        "- volume: entre -15% y +15%. Ejemplo: '+10%'\n\n"
        "Respondé ÚNICAMENTE con este JSON válido (sin código markdown):\n"
        "{\n"
        '  "voice": "es-AR-TomasNeural",\n'
        '  "pitch": "-6Hz",\n'
        '  "rate": "-6%",\n'
        '  "volume": "+10%",\n'
        f'  "descripcion": "{descripcion_natural}"\n'
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
            if "voice" in data:
                return data
        except Exception:
            pass

    # Heurística de respaldo si no hay conexión a IA
    b_pitch = "-6Hz" if any(w in descripcion_natural.lower() for w in ["grave", "ronco", "nocturno", "pesado", "maduro"]) else "-2Hz"
    b_rate = "-8%" if any(w in descripcion_natural.lower() for w in ["lento", "pausado", "tranquilo", "calmo"]) else "+5%" if "rápido" in descripcion_natural.lower() else "-3%"
    return {
        "voice": "es-AR-TomasNeural",
        "pitch": b_pitch,
        "rate": b_rate,
        "volume": "+10%",
        "descripcion": descripcion_natural
    }

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
        f"Timbre de voz activo solicitado: '{timbre.get('descripcion', 'Natural')}'\n\n"
        f"Historial de charlas previas con el usuario (aprendizaje continuo):\n{memoria}\n"
    )

def generar_texto_ia(prompt_usuario):
    """Genera la respuesta dinámica usando Gemini con fallback a Llama y búsqueda web."""
    system_prompt = construir_prompt_sistema()
    p = prompt_usuario

    # Búsqueda web automática si se pide información reciente o actualidad
    if any(k in prompt_usuario.lower() for k in ["noticia", "busca", "qué pasó", "hoy", "clima", "partido", "precio", "resultado", "googlea"]):
        info_web = buscar_en_web(prompt_usuario)
        if info_web:
            p = prompt_usuario + chr(10) + chr(10) + "[Información fresca de internet]:" + chr(10) + info_web

    # Prioridad 1: Gemini 3.8 Flash
    if client:
        try:
            res = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=p,
                config=dict(system_instruction=system_prompt)
            )
            raw = (res.text or "").strip()
            if raw:
                return raw
        except Exception as e:
            print(f"⚠️ Gemini fallback a Ollama: {e}")

    # Prioridad 2: Ollama local (si está disponible)
    try:
        r = requests.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": p}]},
            timeout=25
        )
        if r.status_code == 200:
            texto = r.json().get("message", {}).get("content", "").strip()
            if texto:
                print(f"🦙 [OLLAMA FALLBACK]: Respuesta generada exitosamente con modelo {OLLAMA_MODEL} en {OLLAMA_HOST}")
                return texto
    except Exception as e_ollama:
        try:
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": f"{system_prompt}\n\n{p}"},
                timeout=25
            )
            if r.status_code == 200:
                texto = r.json().get("response", "").strip()
                if texto:
                    print(f"🦙 [OLLAMA GENERATE]: Respuesta generada exitosamente con {OLLAMA_MODEL}")
                    return texto
        except Exception:
            pass

    # Fallback conversacional rioplatense garantizado
    import random
    respuestas_porteñas = [
        "¡Qué hacés che! Mirá, te capté perfecto. Decime cómo seguimos con esto.",
        "Posta che, tenés toda la razón. Fijate por acá y lo resolvemos en un toque.",
        "De una che, escuchá: ya lo tengo anotado. Mandale nomás y lo sacamos andando.",
        "Totalmente che. Mirá que ya lo tengo en mente. ¿Qué otra cosa necesitás que preparemos?"
    ]
    return random.choice(respuestas_porteñas)

def preparar_texto_para_voz(texto):
    """Optimiza el texto para que Edge-TTS suene con cadencia humana, pausas de respiración y sin leer símbolos."""
    # Quitar bloques de código largos para notas de voz
    t = re.sub(r'```[\s\S]*?```', 'Te pasé el bloque de código por texto para que lo mires tranqui.', texto)
    # Quitar caracteres markdown
    t = t.replace("*", "").replace("_", "").replace(chr(96), "").replace("#", "").strip()
    # Agregar pausas naturales tras interjecciones
    t = re.sub(r'\b(che|mirá|fijate|escuchá|vení|posta)\b', r'\g<1>...', t, flags=re.IGNORECASE)
    # Acortar si es excesivamente largo para nota de voz
    palabras = t.split()
    if len(palabras) > 60:
        t = " ".join(palabras[:55]) + "... te lo resumo hasta acá y cualquier cosa me avisás, che."
    return t.strip()

async def sintetizar_voz_edge_tts(texto, ogg_salida="resp.ogg"):
    """Sintetiza la voz usando Edge-TTS con el timbre calibrado dinámicamente por lenguaje natural."""
    cfg = cargar_config_timbre()
    voice = cfg.get("voice", "es-AR-TomasNeural")
    pitch = cfg.get("pitch", "-4Hz")
    rate = cfg.get("rate", "-5%")
    volume = cfg.get("volume", "+10%")

    texto_oral = preparar_texto_para_voz(texto)
    if not texto_oral:
        texto_oral = "Sintonizamos en un toque, che."

    try:
        import edge_tts
        print(f"🎙️ [EDGE-TTS]: Generando audio con timbre '{cfg.get('descripcion', '')}' ({voice}, {pitch}, {rate})...")
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

        # Convertir a OGG Opus nativo 48kHz mono (estricto para notas de voz de Telegram sin silencio)
        proc = subprocess.run([
            "ffmpeg", "-y", "-i", mp3_tmp,
            "-ar", "48000", "-ac", "1",
            "-c:a", "libopus", "-b:a", "48k",
            "-application", "voip",
            ogg_salida
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if os.path.exists(ogg_salida) and os.path.getsize(ogg_salida) > 200:
            try: os.remove(mp3_tmp)
            except Exception: pass
            return True, ogg_salida

        # Fallback a MP3 si ffmpeg falló
        return True, mp3_tmp
    except Exception as e:
        print(f"⚠️ Error sintetizando con edge-tts: {e}")
        return False, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID_ACTIVO
    if update.message:
        CHAT_ID_ACTIVO = update.message.chat_id
        await update.message.reply_text(
            "¡Qué hacés che! Acá Leandro. Estoy listo para charlar, hacer vibe coding de lo que me pidas o cambiar el código.\n\n"
            "Comandos útiles:\n"
            "• /timbre <descripción>: Cambiá el tono de mi voz con lenguaje natural (ej: /timbre voz más ronca y pausada de noche)\n"
            "• /codigo <tarea>: Escribo o modifico cualquier parte del código a tu gusto\n"
            "• /ollama <mensaje>: Testea el fallback local de Ollama directamente\n"
            "• O simplemente hablame de lo que quieras por texto o nota de voz!"
        )

async def cambiar_timbre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    desc = " ".join(context.args).strip() if context.args else ""
    if not desc:
        cfg = cargar_config_timbre()
        await update.message.reply_text(
            f"🎙️ Timbre actual: '{cfg.get('descripcion', 'Estándar')}'\n"
            f"Parámetros: Voz {cfg.get('voice')}, Pitch {cfg.get('pitch')}, Rate {cfg.get('rate')}, Vol {cfg.get('volume')}.\n\n"
            "Para cambiarlo, escribí: /timbre <como querés que suene>\n"
            "Ejemplo: /timbre voz bien grave, ronca y pausada de trasnoche"
        )
        return

    await update.message.reply_text(f"🔧 Calibrando timbre acústico a: '{desc}'...")
    nuevo_timbre = parsear_timbre_con_lenguaje_natural(desc)
    guardar_config_timbre(nuevo_timbre)

    # Mandar muestra de audio con el nuevo timbre
    frase_test = f"Mirá che, así suena mi nuevo timbre con la calibración que me pediste. ¿Te va cómo quedó?"
    ogg_test = f"timbre_{int(time.time())}.ogg"
    ok, path_a = await sintetizar_voz_edge_tts(frase_test, ogg_test)
    if ok and path_a and os.path.exists(path_a):
        with open(path_a, "rb") as vf:
            await update.message.reply_voice(voice=vf, caption=f"✅ Timbre aplicado: '{desc}'")
        try: os.remove(path_a)
        except Exception: pass
    else:
        await update.message.reply_text(f"✅ Timbre configurado correctamente: {nuevo_timbre}")

async def manejar_vibe_coding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    instruccion = " ".join(context.args).strip() if context.args else ""
    if not instruccion:
        await update.message.reply_text("Decime qué querés programar o modificar en el código, che. Ej: /codigo agregá una función para contar palabras.")
        return

    await update.message.reply_text(f"💻 Entendido, metiendo vibe coding en: '{instruccion}'...")
    resp_codigo = generar_texto_ia(f"VIBE CODING: {instruccion}. Generá la solución o modificación de código completa, limpia y lista para aplicar.")
    await update.message.reply_text(resp_codigo)

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    global CHAT_ID_ACTIVO
    CHAT_ID_ACTIVO = update.message.chat_id

    u_text = update.message.text or update.message.caption or ""

    # Transcripción si el usuario envía una nota de voz o audio
    if update.message.voice or update.message.audio:
        try:
            audio_obj = update.message.voice or update.message.audio
            voice_file = await context.bot.get_file(audio_obj.file_id)
            tmp_ogg = f"voz_usuario_{int(time.time()*1000)}.ogg"
            await voice_file.download_to_drive(tmp_ogg)

            # Transcribir con Gemini Multimodal
            if client:
                try:
                    with open(tmp_ogg, "rb") as af:
                        audio_bytes = af.read()
                    mime = "audio/ogg" if update.message.voice else "audio/mpeg"
                    res_trans = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[
                            genai.types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                            "Sos un transcriptor experto en español rioplatense (Argentina). Transcribí fielmente lo que dice este audio, prestando atención a expresiones y palabras coloquiales. Devolvé ÚNICAMENTE el texto transcripto sin comentarios ni comillas."
                        ]
                    )
                    trans_text = (res_trans.text or "").strip()
                    if trans_text:
                        u_text = trans_text
                        print(f"🎙️ [AUDIO TRANSCRIPTO GEMINI]: {u_text}")
                except Exception as ex_tg:
                    print(f"Aviso transcripción Gemini: {ex_tg}")

            # Fallback a faster-whisper local si Gemini no transcribió
            if not u_text:
                try:
                    from faster_whisper import WhisperModel
                    w_model = WhisperModel("tiny", device="cpu", compute_type="int8")
                    segments, _ = w_model.transcribe(tmp_ogg, language="es")
                    u_text = " ".join([s.text for s in segments]).strip()
                    if u_text:
                        print(f"🎙️ [AUDIO TRANSCRIPTO WHISPER]: {u_text}")
                except Exception as ex_wh:
                    print(f"Aviso whisper local: {ex_wh}")

            try: os.remove(tmp_ogg)
            except Exception: pass
        except Exception as ex_dl:
            print(f"Error procesando audio recibido: {ex_dl}")

    if not u_text:
        u_text = "¡Qué hacés che! Decime cómo andás y qué programamos hoy."

    registrar_conversacion("Usuario", u_text)

    # Detección de intención de cambiar timbre por lenguaje natural en charla normal
    if any(k in u_text.lower() for k in ["cambiá la voz", "cambia la voz", "cambiá el timbre", "cambia el timbre", "poné la voz", "pone la voz"]):
        desc_limpia = re.sub(r'(cambi[aá]\s+(la\s+voz|el\s+timbre)|pon[eé]\s+la\s+voz)\s*(a|en|como)?', '', u_text, flags=re.IGNORECASE).strip()
        if len(desc_limpia) > 4:
            nuevo_t = parsear_timbre_con_lenguaje_natural(desc_limpia)
            guardar_config_timbre(nuevo_t)
            resp = f"¡De una che! Ya recalibré mi voz para que suene '{desc_limpia}'. Escuchá cómo me queda ahora."
            registrar_conversacion("LeandroBot", resp)
            await update.message.reply_text(resp)
            ogg_f = f"resp_{int(time.time())}.ogg"
            ok, path_a = await sintetizar_voz_edge_tts(resp, ogg_f)
            if ok and path_a and os.path.exists(path_a):
                with open(path_a, "rb") as vf:
                    await update.message.reply_voice(voice=vf, caption="📻 Nuevo timbre aplicado")
                try: os.remove(path_a)
                except Exception: pass
            return

    # Generación de respuesta dinámica aprendida
    resp = generar_texto_ia(u_text)
    if not resp or not str(resp).strip():
        resp = "Te capté perfecto che, mirá que ya lo tengo presente."

    registrar_conversacion("LeandroBot", resp)
    await update.message.reply_text(resp)

    # Generar y enviar nota de voz con Edge-TTS directo
    ogg_f = f"resp_{int(time.time())}.ogg"
    exito, archivo_audio = await sintetizar_voz_edge_tts(resp, ogg_f)
    if exito and archivo_audio and os.path.exists(archivo_audio):
        try:
            if archivo_audio.endswith(".ogg"):
                with open(archivo_audio, "rb") as vf:
                    await update.message.reply_voice(voice=vf, caption="📻 Leandro")
            else:
                with open(archivo_audio, "rb") as af:
                    await update.message.reply_audio(audio=af, title="Leandro")
        except Exception as ex_send:
            print(f"⚠️ Error enviando audio: {ex_send}")
        try: os.remove(archivo_audio)
        except Exception: pass

async def test_ollama_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    query = " ".join(context.args).strip() if context.args else "Che Leandro, ¿cómo anda Ollama por ahí?"
    await update.message.reply_text(f"🦙 Consultando fallback de Ollama en {OLLAMA_HOST} (modelo {OLLAMA_MODEL})...")
    
    texto = ""
    try:
        r = requests.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": query}]},
            timeout=15
        )
        if r.status_code == 200:
            texto = r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"Error test ollama chat: {e}")

    if not texto:
        try:
            r = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": query},
                timeout=15
            )
            if r.status_code == 200:
                texto = r.json().get("response", "").strip()
        except Exception as e:
            print(f"Error test ollama generate: {e}")

    if texto:
        await update.message.reply_text(f"🦙 [Respuesta de Ollama ({OLLAMA_MODEL})]:\n\n{texto}")
    else:
        await update.message.reply_text(f"⚠️ No se pudo conectar a Ollama en {OLLAMA_HOST}. Verificá que Ollama esté corriendo con: ollama run {OLLAMA_MODEL}")

def main():
    if not TOKEN:
        print("❌ [ERROR CRÍTICO]: Falta la variable TELEGRAM_BOT_TOKEN.")
        print("👉 Entrá a tu repo en GitHub: Settings > Secrets and variables > Actions > New repository secret")
        print("👉 Name: TELEGRAM_BOT_TOKEN | Value: Tu token de @BotFather")
        return

    print("🚀 [INIT]: Configurando LeandroBot (Vibe Coding + Timbre Dinámico + Edge-TTS)...")
    request_config = HTTPXRequest(connect_timeout=60.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=120.0)

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        print(f"⚠️ [Telegram Error]: {context.error}")

    app = Application.builder().token(TOKEN).request(request_config).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("timbre", cambiar_timbre))
    app.add_handler(CommandHandler("codigo", manejar_vibe_coding))
    app.add_handler(CommandHandler("vibe", manejar_vibe_coding))
    app.add_handler(CommandHandler("ollama", test_ollama_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, manejar_mensaje))

    print("🔄 [POLLING]: Bot escuchando en Telegram (Sin automatizaciones spam, respondiendo a tus pedidos)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
