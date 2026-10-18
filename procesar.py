# ... código aquí ...

# ARCHIVO: procesar.py

# ... código aquí ...

# ARCHIVO: procesar.py

# ... código aquí ...
...
# Iniciamos el bot con la memoria contextual profunda y directorios de control duales
if not TOKEN:
    print("❌ ERROR: Falta token.")
    return

try:
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")
    print("🧹 Webhook limpio.")
except Exception as e:
    print(f"⚠️ Webhook error: {e}")

print("🚀 Iniciando bot con memoria contextual profunda y directorios de control duales...")

# ... código aquí ...

# ARCHIVO: procesar.py

# ... código aquí ...

# ARCHIVO: procesar.py

# ... código aquí ...
async def responder_usuario(orden):
    # ... código para responder al mensaje ...

    # Parte 1: Responder al mensaje
    respuesta = responder_usuario(orden)
    await update.message.reply_text(respuesta)

    # Parte 2: Guardar en archivo de texto
    guardar_en_txt("usuario", orden)
    guardar_en_txt("leandro_bot", respuesta)

    # Parte 3: Comentar en código
    print(f"Comentado en código: {orden}")
    # ... código aquí ...