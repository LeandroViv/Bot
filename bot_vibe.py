# -*- coding: utf-8 -*-
"""bot_vibe.py - bot de Telegram alternativo que corre en el runner de Actions.

Es el hermano chico de procesar.py: no toca el repo, no hace push, no usa
aider. Solo chatea. La idea es tener un bot aparte para probar sin pisar a
@locura_agente_bot (mismo token = error 409 y se pelean).

Modelo: Ollama local en el runner. Sin API keys y sin tope de mensajes,
porque no hay costo por token.
"""

import asyncio
import json
import os
import time
import urllib.error
import urllib.request

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_VIBE", "").strip()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODELO = os.environ.get("OLLAMA_MODEL", "phi3")
# El runner de Actions tiene tope de 6h. Salimos un rato antes para que el
# job cierre limpio y el proximo cron tome la posta sin cortar a lo bruto.
MAX_SEGUNDOS = int(os.environ.get("MAX_RUNTIME_SECONDS", str(5 * 3600 + 1800)))
MAX_HISTORIAL = 12  # turnos que se mandan como contexto

# Allowlist: en un repo publico el bot es descubrible. Solo Leandro.
# Ojo con el `or`: si el secret no existe, GitHub manda "", y get() con
# default NO lo reemplaza (la variable existe, vacia). Sin el `or` la
# allowlist queda vacia y el bot no le contesta a nadie.
PERMITIDOS = {
    int(x) for x in (os.environ.get("ALLOWED_CHAT_IDS") or "7043094764").split(",")
    if x.strip().lstrip("-").isdigit()
}

SISTEMA = (
    "Sos el bot de Leandro, un compañero de vibe coding rioplatense. Hablás "
    "en español de Argentina, con voseo, 'che', 'boludo' ocasional, y ritmo "
    "de barrio. Sos directo, ingenioso y no te la das de asistente formal. "
    "Respondés corto: 1 a 3 oraciones, salvo que te pidan algo técnico largo. "
    "Nunca digas que sos una IA generica ni pidas disculpas de más."
)

historiales = {}
INICIO = time.time()


def log(msg):
    print(msg, flush=True)


def consultar_ollama(chat_id, texto):
    """Devuelve la respuesta del modelo, con el historial del chat."""
    historial = historiales.setdefault(chat_id, [])
    historial.append({"role": "user", "content": texto})
    # Recortamos al guardar, no solo al enviar: si no, en un proceso de
    # horas el historial crece sin control y se come la RAM del runner.
    del historial[:-MAX_HISTORIAL]
    mensajes = [{"role": "system", "content": SISTEMA}] + historial
    payload = json.dumps({
        "model": MODELO,
        "messages": mensajes,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 400},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat", data=payload, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            respuesta = json.load(resp).get("message", {}).get("content", "").strip()
    except Exception as exc:  # noqa: BLE001
        log(f"❌ Ollama: {exc!r}")
        historial.pop()
        return "Uy, se me trabó el modelo. Probá de nuevo en un toque."
    if respuesta:
        historial.append({"role": "assistant", "content": respuesta})
        return respuesta
    return "Me quedé en blanco, che. Repetime eso."


async def partir_y_enviar(update, texto, max_chunk=4000):
    """Telegram corta a 4096 chars: partimos sin cortar palabras."""
    for i in range(0, len(texto), max_chunk):
        await update.message.reply_text(texto[i:i + max_chunk])


async def cmd_start(update, context):
    if update.effective_chat.id not in PERMITIDOS:
        return
    await update.message.reply_text(
        "¡Qué hacés che! Soy @lv_vibebot, el bot de pruebas de Leandro.\n"
        "Escribime lo que quieras. Ando con un modelo local en el runner, "
        "así que no hay tope de mensajes.")


async def cmd_status(update, context):
    if update.effective_chat.id not in PERMITIDOS:
        return
    minutos = int((time.time() - INICIO) // 60)
    await update.message.reply_text(
        f"Vivo hace {minutos} min en este runner.\n"
        f"Modelo: {MODELO}\n"
        f"Cortes: cada {MAX_SEGUNDOS // 3600}h aprox, cuando rota el cron.")


async def cmd_reset(update, context):
    if update.effective_chat.id not in PERMITIDOS:
        return
    historiales.pop(update.effective_chat.id, None)
    await update.message.reply_text("Listo, borrón y cuenta nueva.")


async def manejar_texto(update, context):
    if update.effective_chat.id not in PERMITIDOS:
        return
    texto = (update.message.text or "").strip()
    if not texto:
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    respuesta = await asyncio.to_thread(consultar_ollama, update.effective_chat.id, texto)
    await partir_y_enviar(update, respuesta)


async def main():
    if not TOKEN:
        log("❌ Falta TELEGRAM_BOT_TOKEN_VIBE.")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))

    log(f"🤖 @lv_vibebot arriba | modelo {MODELO} | permitidos {PERMITIDOS}")
    async with app:
        await app.start()
        # drop_pending_updates=False: si el bot estuvo caído entre rotaciones,
        # los mensajes que llegaron en el medio se procesan al volver.
        await app.updater.start_polling(drop_pending_updates=False)
        try:
            while time.time() - INICIO < MAX_SEGUNDOS:
                await asyncio.sleep(30)
            log("⏰ Tiempo máximo alcanzado, cerrando para que rote el cron.")
        finally:
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
