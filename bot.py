import os
import time
import requests
from procesar import responder_usuario, evaluar_iniciativa_propia

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = str(os.environ.get("CHAT_ID", ""))
GH_PAT = os.environ.get("GH_PAT")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")

# Cerca del límite de 5 horas de GitHub Actions (4h 58m = 17880 seg)
TIEMPO_MAXIMO_SEGUNDOS = 17880
INTERVALO_INICIATIVA = 30 * 60  # Chequeo de relevancia cada 30 min


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
    """Autodispara un nuevo workflow mediante repository_dispatch antes de que el runner muera."""
    if not GH_PAT or not GITHUB_REPOSITORY:
        print("❌ No se puede reenganchar: falta configurar GH_PAT o GITHUB_REPOSITORY.")
        return
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/dispatches"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {"event_type": "reenganche-bot"}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code == 204:
            print("🔄 Reenganche automático solicitado con éxito a GitHub.")
        else:
            print(f"⚠️ Error en reenganche HTTP {res.status_code}: {res.text}")
    except Exception as e:
        print(f"⚠️ Excepción al solicitar reenganche: {e}")


def main():
    inicio = time.time()
    ultimo_chequeo_iniciativa = time.time()
    offset = 0
    print("🚀 Bot iniciado y escuchando en tiempo real...")

    while (time.time() - inicio) < TIEMPO_MAXIMO_SEGUNDOS:
        updates = obtener_updates(offset)

        for u in updates:
            offset = u["update_id"] + 1
            mensaje = u.get("message", {})
            texto = mensaje.get("text", "")
            id_chat = str(mensaje.get("chat", {}).get("id", ""))

            if texto and (not CHAT_ID or id_chat == CHAT_ID):
                print(f"📩 Mensaje recibido: {texto}")
                respuesta = responder_usuario(texto)
                if respuesta:
                    enviar_telegram(id_chat, respuesta)

        # Chequeo periódico de proactividad
        if (time.time() - ultimo_chequeo_iniciativa) > INTERVALO_INICIATIVA:
            print("🧠 Evaluando relevancia de novedades para Leandro...")
            mensaje_propio = evaluar_iniciativa_propia()
            if mensaje_propio:
                print("💡 Criterio positivo: enviando aporte propio.")
                enviar_telegram(CHAT_ID, mensaje_propio)
            else:
                print("💤 Sin novedades de alto valor por ahora.")
            ultimo_chequeo_iniciativa = time.time()

        time.sleep(2)

    print("⏰ Alcanzado límite de tiempo del ciclo. Solicitando reenganche...")
    gatillar_reenganche()


if __name__ == "__main__":
    main()
