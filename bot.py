import os
import sys
import requests
from procesar import generar_respuesta_llm

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
ORDEN_USUARIO = os.environ.get("ORDEN_USUARIO")


def responder_telegram(chat_id, texto):
    """Envía la respuesta procesada directamente al chat de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            # Reintento sin formato si falla la sintaxis Markdown
            payload.pop("parse_mode")
            requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"⚠️ Error al enviar mensaje a Telegram: {e}")


def main():
    orden = ORDEN_USUARIO or (sys.argv[1] if len(sys.argv) > 1 else "")
    
    if not orden:
        print("❌ Error: No se ingresó ninguna orden para procesar.")
        return

    print(f"📩 Procesando orden: {orden}")

    # Generar respuesta con la IA
    respuesta = generar_respuesta_llm(orden)

    # Responder al canal/chat de Telegram
    if respuesta:
        print("📤 Enviando respuesta a Telegram...")
        responder_telegram(CHAT_ID, respuesta)
    else:
        mensaje_error = "⚠️ No pude obtener respuesta del servidor de Ollama en Hugging Face."
        responder_telegram(CHAT_ID, mensaje_error)


if __name__ == "__main__":
    main()
