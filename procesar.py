import os
import sys
import time
import logging
import psutil
import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Configuración de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Control de tiempo de actividad
TIEMPO_INICIO = time.time()

TOKEN = os.getenv("TELEGRAM_TOKEN", "TU_TOKEN_AQUI")
URL_MICROSERVICIO = os.getenv("URL_MICROSERVICIO", "http://localhost:8000/procesar")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saludo = "¡Buenas! Soy Leandro, tu bot y colega de vibe coding. Mandame un mensaje o nota de voz y lo charlamos."
    if update.message:
        await update.message.reply_text(saludo)


async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    texto_usuario = update.message.text
    logger.info("Texto recibido: %s", texto_usuario)

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"texto": texto_usuario, "tipo": "texto"}
            async with session.post(URL_MICROSERVICIO, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    respuesta = data.get("respuesta", "Dale, recibido che.")
                    await update.message.reply_text(respuesta)
                else:
                    await update.message.reply_text("Che, hubo un drama comunicando con el microservicio.")
    except Exception as e:
        logger.error("Error al procesar texto: %s", e)
        await update.message.reply_text("Mirá, saltó un error procesando el mensaje.")


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not (update.message.voice or update.message.audio):
        return

    archivo_id = update.message.voice.file_id if update.message.voice else update.message.audio.file_id
    logger.info("Voz/Audio recibido con file_id: %s", archivo_id)

    try:
        nuevo_archivo = await context.bot.get_file(archivo_id)
        ruta_ogg = f"voz_{update.message.message_id}.ogg"
        await nuevo_archivo.download_to_drive(ruta_ogg)

        async with aiohttp.ClientSession() as session:
            with open(ruta_ogg, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("audio", f, filename=ruta_ogg, content_type="audio/ogg")
                async with session.post(f"{URL_MICROSERVICIO}_audio", data=data, timeout=120) as resp:
                    if resp.status == 200:
                        resultado = await resp.json()
                        respuesta_texto = resultado.get("texto", "Audio procesado posta.")
                        audio_respuesta_path = resultado.get("audio_path")
                        if audio_respuesta_path and os.path.exists(audio_respuesta_path):
                            with open(audio_respuesta_path, "rb") as audio_out:
                                await update.message.reply_voice(audio_out, caption=respuesta_texto)
                        else:
                            await update.message.reply_text(respuesta_texto)
                    else:
                        await update.message.reply_text("Che, se complicó procesar el audio con el microservicio.")

        if os.path.exists(ruta_ogg):
            os.remove(ruta_ogg)
    except Exception as e:
        logger.error("Error procesando audio: %s", e)
        await update.message.reply_text("Fijate que falló el procesamiento del audio, che.")


async def manejar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime_segundos = int(time.time() - TIEMPO_INICIO)
    horas, resto = divmod(uptime_segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    uptime_formateado = f"{horas:02d}:{minutos:02d}:{segundos:02d}"

    proceso = psutil.Process(os.getpid())
    memoria_mb = proceso.memory_info().rss / (1024 * 1024)

    mensaje_estado = (
        f"📊 *Estado del Bot:*\n"
        f"⏱️ *Uptime:* `{uptime_formateado}`\n"
        f"💾 *Memoria RAM:* `{memoria_mb:.2f} MB`"
    )
    if update.message:
        await update.message.reply_text(mensaje_estado, parse_mode="Markdown")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("estado", manejar_estado))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))

    logger.info("Bot iniciado. Esperando mensajes...")
    app.run_polling()


if __name__ == "__main__":
    main()