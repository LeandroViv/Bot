...

def responder_usuario(orden):
    # ...
    return respuesta

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Buenas che! Bot activo con memoria contextual profunda y directorios duales (originales / recursiva).")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    print(f"📩 Mensaje recibido: {texto_usuario}")

    if texto_usuario.lower().startswith(("corregir:", "corrección:")):
        # PROCESAR AUDIO
        ...
    else:
        await update.message.reply_text("Che, no te entendí nada, tirámela de nuevo.")

async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # PROCESAR VOZ
    ...
    return texto_reconocido

def main():
    inicializar_directorios_control("procesar.py")

    if not TOKEN:
        print("❌ ERROR: Falta token.")
        return

    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
        print("🧹 Webhook limpio.")
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")

    print("🚀 Iniciando bot con memoria contextual profunda y directorios de control duales...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()