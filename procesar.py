import os
import sys
import time
import logging
import asyncio
import aiohttp
from datetime import timedelta

try:
    import psutil
except ImportError:
    psutil = None

try:
    import resource
except ImportError:
    resource = None

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

TIEMPO_INICIO = time.time()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN_TELEGRAM = os.getenv("TELEGRAM_BOT_TOKEN", "TU_TOKEN_AQUI")
URL_MICROSERVICIO = os.getenv("MICROSERVICIO_URL", "http://127.0.0.1:8000")


async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "¡Buenas che! Acá estoy al pie del cañón. Mandame un texto o un audio y lo procesamos al toque."
        )


async def comando_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        ayuda_texto = (
            "Comandos disponibles:\n"
            "/start - Arrancar el bot\n"
            "/ayuda - Ver este mensaje\n"
            "/estado - Chequear uptime y memoria RAM\n\n"
            "También podés mandarme notas de voz o mensajes de texto directamente."
        )
        await update.message.reply_text(ayuda_texto)


async def manejar_mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    texto_usuario = update.message.text
    chat_id = update.effective_chat.id

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"texto": texto_usuario, "chat_id": chat_id}
            async with session.post(
                f"{URL_MICROSERVICIO}/procesar_texto", json=payload, timeout=60
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    respuesta = data.get("respuesta", "Dale, recibido.")
                    await update.message.reply_text(respuesta)
                else:
                    await update.message.reply_text(
                        "Che, hubo un drama conectando con el microservicio."
                    )
    except Exception as e:
        logger.error(f"Error procesando texto: {e}")
        await update.message.reply_text(
            "Fijate que falló la comunicación interna, bancame un toque."
        )


async def manejar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    archivo_audio = update.message.voice or update.message.audio
    if not archivo_audio:
        return

    chat_id = update.effective_chat.id

    try:
        tg_file = await context.bot.get_file(archivo_audio.file_id)
        ruta_descarga = f"audio_{archivo_audio.file_unique_id}.ogg"
        await tg_file.download_to_drive(ruta_descarga)

        async with aiohttp.ClientSession() as session:
            with open(ruta_descarga, "rb") as f:
                datos = aiohttp.FormData()
                datos.add_field(
                    "audio",
                    f,
                    filename=ruta_descarga,
                    content_type="audio/ogg",
                )
                datos.add_field("chat_id", str(chat_id))

                async with session.post(
                    f"{URL_MICROSERVICIO}/procesar_audio", data=datos, timeout=120
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        respuesta_texto = data.get(
                            "texto", "Audio procesado con éxito."
                        )
                        await update.message.reply_text(respuesta_texto)
                    else:
                        await update.message.reply_text(
                            "No se pudo procesar el audio en el microservicio, che."
                        )

        if os.path.exists(ruta_descarga):
            os.remove(ruta_descarga)

    except Exception as e:
        logger.error(f"Error procesando nota de voz: {e}")
        await update.message.reply_text("Se complicó procesar el audio, mirá.")


async def manejar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    segundos_activos = int(time.time() - TIEMPO_INICIO)
    uptime_formateado = str(timedelta(seconds=segundos_activos))

    memoria_mb = 0.0
    if psutil:
        proceso = psutil.Process(os.getpid())
        memoria_mb = proceso.memory_info().rss / (1024 * 1024)
    elif resource:
        memoria_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            memoria_mb = memoria_mb / 1024
        else:
            memoria_mb = memoria_mb / (1024 * 1024)

    mensaje_estado = (
        f"⏱ *Uptime:* `{uptime_formateado}`\n"
        f"🧠 *RAM en uso:* `{memoria_mb:.2f} MB`\n"
        f"🚀 *Estado:* Operativo y escuchando."
    )

    if update.message:
        await update.message.reply_text(mensaje_estado, parse_mode="Markdown")


def main():
    app = Application.builder().token(TOKEN_TELEGRAM).build()

    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(CommandHandler("ayuda", comando_ayuda))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje_texto)
    )
    app.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, manejar_audio)
    )
    app.add_handler(CommandHandler("estado", manejar_estado))

    logger.info("Bot de Telegram iniciado. Corriendo polling...")
    app.run_polling()


if __name__ == "__main__":
    main()