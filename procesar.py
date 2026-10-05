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
        "options": {"num_ctx": 16384, "temperature": 0.7},
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
        {"role": "user", "content": f"Contexto previo:\n{historial_resumido}\n\nTexto transcrito a revisar: {texto_transcrito}"},
    ]

    texto_corregido = llamar_ollama(prompt, timeout_secs=60)
    return texto_corregido if texto_corregido else texto_transcrito


def calcular_parametros_audio_dinamicos(texto_respuesta):
    """Motor de pulido de voz paramétrico: calcula tempo y compresión dinámica según el texto."""
    if not os.path.exists(TXT_FILE):
        return "atempo=1.03", "dynaudnorm=f=150:g=15"

    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un motor algorítmico de procesamiento de audio adaptativo. "
                "Analizá el texto de respuesta para definir su cadencia óptima. "
                "Devolvé UNICAMENTE dos valores separados por coma: \n"
                "1. Un factor de tempo para atempo (ejemplo: 1.02, 1.05, 0.98)\n"
                "2. Un valor de normalización y compresión dinámica para el volumen\n"
                "Formato estricto: ATEMPO,VALOR_AUDIO (Ejemplo: 1.03,dynaudnorm=f=150:g=15)"
            ),
        },
        {"role": "user", "content": f"Texto a procesar: {texto_respuesta}"},
    ]

    respuesta_ia = llamar_ollama(prompt, timeout_secs=30)
    
    tempo_val = "1.03"
    audio_val = "dynaudnorm=f=150:g=15"

    try:
        if "," in respuesta_ia:
            partes = respuesta_ia.split(",")
            t = partes[0].strip()
            if 0.5 <= float(t) <= 2.0:
                tempo_val = t
    except:
        pass

    return f"atempo={tempo_val}", audio_val


def extraer_conceptos_semanticos(consulta):
    prompt = [
        {
            "role": "system",
            "content": (
                "Sos un extractor de conceptos semánticos. Dado el mensaje de un "
                "usuario, generá una lista de palabras clave separadas por comas.\n"
                "Devolvé SOLAMENTE los términos, sin explicaciones."
            ),
        },
        {"role": "user", "content": f"Mensaje del usuario: {consulta}"},
    ]
    respuesta = llamar_ollama(prompt, timeout_secs=120)
    if respuesta:
        return [
            c.strip().lower()
            for c in respuesta.replace("\n", "").split(",")
            if len(c.strip()) > 2
        ]
    return [p.lower() for p in re.findall(r"\w+", consulta) if len(p) > 3]


def recuperar_contexto_de_txt(consulta, max_bloques=3):
    if not os.path.exists(TXT_FILE):
        return ""

    with open(TXT_FILE, "r", encoding="utf-8") as f:
        contenido = f.read()

    bloques = contenido.split("---\n")
    bloques_validos = [b.strip() for b in bloques if b.strip()]
    if not bloques_validos:
        return ""

    conceptos = extraer_conceptos_semanticos(consulta)
    if not conceptos:
        return ""

    bloques_puntuados = []
    for b in bloques_validos:
        b_lower = b.lower()
        coincidencias = sum(1 for c in conceptos if c in b_lower)
        if coincidencias > 0:
            bloques_puntuados.append((coincidencias, b))

    bloques_puntuados.sort(key=lambda x: x[0], reverse=True)

    top_bloques = []
    vistos = set()
    for _, b in bloques_puntuados:
        if b not in vistos:
            top_bloques.append(b)
            vistos.add(b)
        if len(top_bloques) >= max_bloques:
            break

    return "\n\n".join(top_bloques)


def generar_query_semantica(orden_usuario):
    historial_completo = ""
    if os.path.exists(TXT_FILE):
        with open(TXT_FILE, "r", encoding="utf-8") as f:
            historial_completo = f.read()

    prompt = [
        {
            "role": "system",
            "content": "Analizá el historial y la consulta para devolver de 2 a 5 palabras clave de búsqueda web en texto plano.",
        },
        {
            "role": "user",
            "content": f"HISTORIAL:\n{historial_completo}\n\nCONSULTA: {orden_usuario}",
        },
    ]
    query = llamar_ollama(prompt, timeout_secs=120)
    return query.replace('"', "").replace("'", "").strip() if query else orden_usuario


def consultar_ia_duckduckgo(orden_usuario):
    """Extrae datos limpios y directos desde la IA/Web de DuckDuckGo sin contaminar."""
    query = generar_query_semantica(orden_usuario)
    texto_resultados = ""
    try:
        with DDGS() as ddgs:
            if hasattr(ddgs, "chat"):
                respuestas = list(ddgs.chat(query))
                if respuestas:
                    texto_resultados = "\n".join([str(r) for r in respuestas])
            
            if not texto_resultados:
                res = list(ddgs.text(query, max_results=5, backend="html"))
                for r in res:
                    texto_resultados += f"• {r.get('title')}: {r.get('body')}\n"
    except Exception as e:
        print(f"⚠️ Error consultando DuckDuckGo: {e}")

    return texto_resultados if texto_resultados else "Sin datos web disponibles."


def responder_usuario(orden):
    """Procesa la respuesta usando el historial solo como guía de estilo y DuckDuckGo como verdad absoluta."""
    if not orden or not orden.strip():
        return "Che, no te entendí nada, tirámela de nuevo."

    contexto_txt = recuperar_contexto_de_txt(orden, max_bloques=3)
    info_web = consultar_ia_duckduckgo(orden)

    system_prompt = (
        "Sos Leandro hablando con un colega por Telegram. CERO formato de asistente virtual o de manual.\n"
        "REGLAS ESTRICTAS:\n"
        "1. FUENTE DE INFORMACIÓN: La respuesta factual debe basarse EXCLUSIVAMENTE en los 'DATOS FRESCOS DE DUCKDUCKGO'. No inventes información ni mezcles datos viejos del historial como si fueran actuales.\n"
        "2. USO DEL HISTORIAL: El bloque de historial provisto es SÓLO para entender tu tono, modismos rioplatenses ('vos', 'che', 'fijate') y términos técnicos previos. No lo resumas ni repitas lo que ya se charló antes.\n"
        "3. CADENCIA: Hablar directo al hueso, frases naturales y al pie."
    )

    mensaje_usuario = f"MENSAJE ACTUAL: {orden}\n\n[DATOS FRESCOS DE DUCKDUCKGO - USAR ESTO COMO VERDAD ABSOLUTA]:\n{info_web}"
    
    if contexto_txt:
        mensaje_usuario += f"\n\n[HISTORIAL DE REFERENCIA DE ESTILO - NO REPETIR NI RESUMIR]:\n{contexto_txt}"

    mensajes_chat = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": mensaje_usuario},
    ]

    respuesta = llamar_ollama(mensajes_chat, timeout_secs=300)

    if not respuesta or not respuesta.strip():
        respuesta = "Che, me quedé pensando y no me salió nada."

    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)
    exportar_dataset_actualizado()

    return respuesta


def limpiar_texto_para_voz(texto):
    """Limpia formatos para síntesis de voz fluida."""
    texto_limpio = re.sub(r'http\S+|www\S+|https\S+', '', texto)
    texto_limpio = re.sub(r'[*_#`\[\]()~>+-]', '', texto_limpio)
    texto_limpio = re.sub(r'\n+', '. ', texto_limpio)
    return texto_limpio.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Leandro Bot activo con DuckDuckGo puro y uso inteligente del historial de estilo.")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje de texto recibido: {texto_usuario}")
    await update.message.chat.send_action(action="typing")

    respuesta = responder_usuario(texto_usuario)
    await update.message.reply_text(respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa audio aplicando consulta a DuckDuckGo y modulación paramétrica de voz."""
    async with lock_voz:
        print("🎤 Audio recibido, procesando voz con IA de DDG y paramétrica...")
        await update.message.chat.send_action(action="record_voice")

        ruta_ogg = "temp_audio.ogg"
        ruta_respuesta_mp3 = "respuesta.mp3"
        ruta_respuesta_ogg = "respuesta.ogg"
        texto_reconocido = ""
        respuesta = ""

        try:
            modelo_whisper = whisper.load_model("base")

            archivo_telegram = await update.message.voice.get_file()
            await archivo_telegram.download_to_drive(ruta_ogg)

            vocabulario_global = extraer_vocabulario_global_de_txt()
            resultado_transcripcion = modelo_whisper.transcribe(
                ruta_ogg, 
                language="es", 
                initial_prompt=vocabulario_global
            )
            texto_crudo = resultado_transcripcion.get("text", "").strip()
            texto_reconocido = corregir_transcripcion_por_contexto(texto_crudo)

            if os.path.exists(ruta_ogg):
                os.remove(ruta_ogg)

            if not texto_reconocido:
                await update.message.reply_text("Che, no te capté bien el audio, ¿me lo repetís?")
                return

            respuesta = responder_usuario(texto_reconocido)
            print(f"🔊 Respuesta generada: '{respuesta}'")

            respuesta_para_voz = limpiar_texto_para_voz(respuesta)
            if not respuesta_para_voz:
                respuesta_para_voz = "Che, me quedé pensando y no supe qué decirte."

            tts = gTTS(text=respuesta_para_voz, lang="es", tld="com.ar")
            tts.save(ruta_respuesta_mp3)

            # APLICACIÓN DEL PULIDO DE VOZ PARAMÉTRICO
            filtro_atempo, filtro_dinamico = calcular_parametros_audio_dinamicos(respuesta_para_voz)
            print(f"🎛️ Parámetros de audio paramétrico: Tempo={filtro_atempo} | Dinámica={filtro_dinamico}")

            subprocess.run([
                "ffmpeg", "-y", "-i", ruta_respuesta_mp3,
                "-filter:a", f"{filtro_atempo},{filtro_dinamico}",
                "-c:a", "libopus", "-b:a", "48k", "-ar", "24000",
                ruta_respuesta_ogg
            ], check=True)

            with open(ruta_respuesta_ogg, "rb") as voice_file:
                await update.message.reply_voice(
                    voice=voice_file, 
                    caption=f"*(Entendido: \"{texto_reconocido}\")*"
                )

            print("✅ Nota de voz paramétrica enviada con éxito.")

        except Exception as e:
            print(f"⚠ Error procesando el audio: {e}")
            try:
                await update.message.reply_text(f"*(Entendido: \"{texto_reconocido}\")*\n\n{respuesta}")
            except:
                await update.message.reply_text("Che, se me armó un lío procesando el audio.")

        finally:
            for archivo in [ruta_ogg, ruta_respuesta_mp3, ruta_respuesta_ogg]:
                if os.path.exists(archivo):
                    try:
                        os.remove(archivo)
                    except:
                        pass


def main():
    if not TOKEN:
        print("❌ ERROR: No se encontró TELEGRAM_BOT_TOKEN.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
        print("🧹 Webhook y actualizaciones limpiadas correctamente.")
    except Exception as e:
        print(f"⚠️ No se pudo limpiar el webhook: {e}")

    print("🚀 Iniciando Leandro Bot con DuckDuckGo puro y guía de estilo limpia...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
