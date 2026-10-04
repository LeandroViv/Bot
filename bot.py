import os
import time
import requests
from procesar import responder_usuario

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_AUTORIZADO = str(os.getenv("CHAT_ID", ""))


def obtener_mensajes(offset=None):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    try:
        res = requests.get(url, params=params, timeout=35)
        if res.status_code == 200:
            return res.json().get("result", [])
    except Exception as e:
        print(f"Error de conexión con Telegram: {e}")
    return []


def enviar_mensaje(chat_id, texto):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error al enviar mensaje: {e}")


def iniciar_bot():
    print("🤖 Bot iniciado y escuchando en bucle...")
    offset = None

    while True:
        actualizaciones = obtener_mensajes(offset)
        for act in actualizaciones:
            offset = act["update_id"] + 1
            mensaje = act.get("message", {})
            text = mensaje.get("text", "")
            chat_id = str(mensaje.get("chat", {}).get("id", ""))

            # Filtro por CHAT_ID si está configurado
            if CHAT_ID_AUTORIZADO and chat_id != CHAT_ID_AUTORIZADO:
                continue

            if text:
                print(f"📩 Procesando orden: {text}")
                print("🧠 Generando respuesta con la IA...")
                respuesta = responder_usuario(text)
                if respuesta:
                    print("📤 Enviando respuesta a Telegram...")
                    enviar_mensaje(chat_id, respuesta)

        time.sleep(1)


if __name__ == "__main__":
    iniciar_bot()
