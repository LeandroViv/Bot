import os
import sys
from datetime import datetime
from asyncio import get_event_loop
from pydub import AudioSegment
from pydub.playback import play

async def manejar_estado(update, context):
    loop = get_event_loop()
    loop.run_until_complete(mostrar_estados())
    app.add_handler(CommandHandler("estado", manejar_estado))

async def mostrar_estados():
    uptime = datetime.now().strftime('%H:%M:%S')
    mem = f"{os memoryUsage().total / (1024.0 ** 3):.2f} GB"
    return f"Uptime: {uptime}, Mem: {mem}"

def main():
    import bot
    bot.run_polling()

if __name__ == "__main__":
    main()