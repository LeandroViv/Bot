import os
import requests
import json

print("🔍 [TEST]: Iniciando prueba de fuego de conectividad...", flush=True)

# 1. Probar conectividad con Ollama local
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
try:
    print(f"🦙 [TEST OLLAMA]: Consultando {OLLAMA_HOST}/api/tags...", flush=True)
    res = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=5)
    print(f"🦙 [TEST OLLAMA RESPUESTA]: Código {res.status_code} - {res.text[:100]}", flush=True)
except Exception as e:
    print(f"❌ [TEST OLLAMA ERROR]: {e}", flush=True)

# 2. Probar inferencia directa con Llama3.2
try:
    print("🦙 [TEST INFERENCIA]: Enviando prompt de prueba a Llama3.2...", flush=True)
    payload = {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Hola che, respondé corto."}],
        "options": {"num_ctx": 512, "num_predict": 50},
        "stream": False
    }
    res_chat = requests.post(f"{OLLAMA_HOST.rstrip('/')}/api/chat", json=payload, timeout=30)
    print(f"🦙 [TEST INFERENCIA RESPUESTA]: Código {res_chat.status_code}", flush=True)
    if res_chat.status_code == 200:
        print(f"✅ [CONTENIDO]: {res_chat.json().get('message', {}).get('content', '')}", flush=True)
except Exception as e:
    print(f"❌ [TEST INFERENCIA ERROR]: {e}", flush=True)

print("🏁 [TEST]: Prueba finalizada.", flush=True)
