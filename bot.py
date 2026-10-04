import os
import time
import requests
from procesar import responder_usuario, evaluar_iniciativa_propia

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = str(os.environ.get("CHAT_ID"))
GH_PAT = os.environ.get("GH_PAT")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")

TIEMPO_MAXIMO_SEGUNDOS = 5 * 3600  # 5 horas
INTERVALO_INICIATIVA = 30 * 60     # Evalúa iniciativa propia cada 30 min

def enviar_telegram(chat_id, texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            payload.pop("parse_mode")
            requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"⚠️ Error Telegram: {e}")

def obtener_updates(offset):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 20}
    try:
        res = requests.get(url, params=params, timeout=25)
        if res.status_code == 200:
            return res.json().get("result", [])
    except Exception:
        pass
    return []

def gatillar_reenganche():
    if not GH_PAT or not GITHUB_REPOSITORY:
        return
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/dispatches"
    headers = {"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github.v3+json"}
    payload = {"event_type": "reenganche-bot"}
    try:
        requests.post(url, json=payload, headers=headers, timeout=15)
    except Exception as e:
        print(f"⚠️ Error reenganche: {e}")

def main():
    inicio = time.time()
    ultimo_chequeo_iniciativa = time.time()
    offset = 0
    print("🚀 Bot iniciado con criterio de iniciativa por relevancia...")

    while (time.time() - inicio) < TIEMPO_MAXIMO_SEGUNDOS:
        updates = obtener_updates(offset)

        for u in updates:
            offset = u["update_id"] + 1
            mensaje = u.get("message", {})
            texto = mensaje.get("text", "")
            id_chat = str(mensaje.get("chat", {}).get("id", ""))

            if texto and id_chat == CHAT_ID:
                print(f"📩 Mensaje recibido: {texto}")
                respuesta = responder_usuario(texto)
                if respuesta:
                    enviar_telegram(CHAT_ID, respuesta)

        # Chequeo con criterio humano en segundo plano
        if (time.time() - ultimo_chequeo_iniciativa) > INTERVALO_INICIATIVA:
            print("🧠 Analizando si hay alguna novedad relevante para Leandro...")
            mensaje_propio = evaluar_iniciativa_propia()
            if mensaje_propio:
                print("💡 Criterio positivo: enviando aporte de iniciativa propia.")
                enviar_telegram(CHAT_ID, mensaje_propio)
            else:
                print("💤 Nada verdaderamente relevante por ahora. Silencio.")
            ultimo_chequeo_iniciativa = time.time()

        time.sleep(2)

    gatillar_reenganche()

if __name__ == "__main__":
    main()
