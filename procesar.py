import os
import sys
import json
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODELO_DEFAULT = os.getenv("OLLAMA_MODEL", "llama3")
TIMEOUT_OLLAMA = 180  # Actualizado de 60s a 180s para evitar timeouts en respuestas largas

def cargar_json(ruta, por_defecto=None):
    if por_defecto is None:
        por_defecto = {}
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error al leer {ruta}: {e}")
    return por_defecto

def guardar_json(ruta, datos):
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error al guardar {ruta}: {e}")

def aplicar_correcciones_whisper(texto):
    correcciones = cargar_json("correcciones_whisper.json", {})
    texto_corregido = texto
    for error, fix in correcciones.items():
        texto_corregido = texto_corregido.replace(error, fix)
    return texto_corregido

def consultar_ollama_generate(prompt, sistema="", modelo=MODELO_DEFAULT, timeout=TIMEOUT_OLLAMA):
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": modelo,
        "prompt": prompt,
        "system": sistema,
        "stream": False
    }
    try:
        logging.info(f"Enviando solicitud a Ollama ({modelo}) con timeout de {timeout}s...")
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()
    except requests.exceptions.Timeout:
        logging.error(f"Timeout de {timeout}s alcanzado consultando Ollama en {url}")
        return "Che, se me fue el tiempo esperando la respuesta local, fijate si Ollama no está colgado."
    except Exception as e:
        logging.error(f"Error en consultar_ollama_generate: {e}")
        return ""

def consultar_ollama_chat(mensajes, modelo=MODELO_DEFAULT, timeout=TIMEOUT_OLLAMA):
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {
        "model": modelo,
        "messages": mensajes,
        "stream": False
    }
    try:
        logging.info(f"Enviando chat a Ollama ({modelo}) con timeout de {timeout}s...")
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()
    except requests.exceptions.Timeout:
        logging.error(f"Timeout de {timeout}s alcanzado en chat con Ollama ({url})")
        return "Che, se agotó el tiempo de espera de 180 segundos con el modelo local."
    except Exception as e:
        logging.error(f"Error en consultar_ollama_chat: {e}")
        return ""

def procesar_entrada_usuario(texto_usuario):
    texto_limpio = aplicar_correcciones_whisper(texto_usuario)
    perfil = cargar_json("perfil_personaje.json", {})
    contexto = ""
    if os.path.exists("contexto_leandro.txt"):
        with open("contexto_leandro.txt", "r", encoding="utf-8") as f:
            contexto = f.read().strip()

    prompt_sistema = perfil.get("sistema", (
        "Sos Leandro: colega de confianza, compañero de vibe coding y locutor rioplatense. "
        "Hablale al usuario de vos o che, directo al pie, con modismos rioplatenses naturales."
    ))
    if contexto:
        prompt_sistema += f"\nContexto adicional:\n{contexto}"

    mensajes = [
        {"role": "system", "content": prompt_sistema},
        {"role": "user", "content": texto_limpio}
    ]

    respuesta = consultar_ollama_chat(mensajes, timeout=TIMEOUT_OLLAMA)

    try:
        with open("conversaciones.txt", "a", encoding="utf-8") as f:
            f.write(f"Usuario: {texto_limpio}\nBot: {respuesta}\n\n")
    except Exception as e:
        logging.error(f"No se pudo registrar la conversación: {e}")

    return respuesta

def hot_reload():
    logging.info("Ejecutando hot-reload de módulos en ejecución...")
    modulos_a_recargar = [k for k in sys.modules.keys() if "procesar" in k]
    for mod in modulos_a_recargar:
        sys.modules.pop(mod, None)
    logging.info("Hot-reload completado con éxito.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(procesar_entrada_usuario(query))
    else:
        logging.info(f"procesar.py inicializado con timeout local = {TIMEOUT_OLLAMA}s.")
        hot_reload()