import json
import os
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

HISTORIAL_FILE = "historial.json"


def cargar_historial():
  if os.path.exists(HISTORIAL_FILE):
    try:
      with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return []
  return []


def guardar_mensaje(rol, contenido):
  historial = cargar_historial()
  historial.append({"role": rol, "content": contenido})
  historial = historial[-20:]
  with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
    json.dump(historial, f, ensure_ascii=False, indent=2)


def llamar_ollama(messages):
  url = "http://127.0.0.1:11434/api/chat"
  payload = {"model": "llama3.2", "messages": messages, "stream": False}
  try:
    res = requests.post(url, json=payload, timeout=90)
    if res.status_code == 200:
      return res.json().get("message", {}).get("content", "").strip()
  except Exception as e:
    print(f"⚠️ Error conectando con Ollama: {e}")
  return ""


def generar_query_semantica(orden_usuario):
  """Pide a Llama 3.2 que interprete la intención del usuario y genere 2-4 palabras clave optimizadas para buscadores."""
  prompt = [
      {
          "role": "system",
          "content": (
              "Tu única tarea es actuar como un optimizador de búsquedas web."
              " Analizá la intención del usuario y devolvé ÚNICAMENTE de 2 a 5"
              " palabras clave en español o inglés ideales para buscar en"
              " Google/DuckDuckGo.\n"
              "REGLAS:\n"
              "- NO agregues comillas, frases como 'aquí tienes' ni"
              " explicaciones.\n"
              "- NO incluyas palabras como 'buscame', 'que es', 'noticias"
              " sobre'.\n"
              "Ejemplo Usuario: 'Buscame en la web qué onda con los llm"
              " últimamente'\n"
              "Respuesta: novedades llm modelos lenguaje"
          ),
      },
      {"role": "user", "content": orden_usuario},
  ]
  query = llamar_ollama(prompt)
  # Si por alguna razón la IA no responde bien, usa la orden original
  query_limpia = (
      query.replace('"', "").replace("'", "").strip() if query else orden_usuario
  )
  print(f"🧠 Intención entendida por la IA -> Query web: '{query_limpia}'")
  return query_limpia


def buscar_web(orden_usuario):
  query = generar_query_semantica(orden_usuario)
  texto_resultados = ""

  # Intento 1: DuckDuckGo API
  try:
    with DDGS() as ddgs:
      res = list(ddgs.text(query, max_results=4))
      for r in res:
        texto_resultados += f"• Título: {r.get('title')}\n  Detalle: {r.get('body')}\n  URL: {r.get('href')}\n\n"
      if texto_resultados:
        return texto_resultados
  except Exception as e:
    print(f"⚠️ DDGS falló: {e}. Probando respaldo Lite...")

  # Intento 2: Fallback BeautifulSoup
  try:
    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    }
    res = requests.post(url, data={"q": query}, headers=headers, timeout=10)
    if res.status_code == 200:
      soup = BeautifulSoup(res.text, "html.parser")
      filas = soup.find_all("td", class_="result-snippet")
      for f in filas[:4]:
        texto_resultados += f"• {f.get_text(strip=True)}\n\n"
  except Exception as e:
    print(f"⚠️ Fallback Lite falló: {e}")

  return texto_resultados


def responder_usuario(orden):
  guardar_mensaje("user", orden)
  historial = cargar_historial()

  # Realiza la búsqueda semántica
  info_web = buscar_web(orden)

  system_prompt = (
      "Sos Leandro Bot, el asistente personal de Leandro.\n"
      "Hablá en español rioplatense (usá vos, che, mirá), de forma clara,"
      " directa y técnica.\n"
      "Tenés acceso directo a los datos web suministrados en el prompt.\n"
      "PROHIBIDO: NUNCA digas 'sin necesidad de ir a la web' ni 'como modelo de"
      " IA no tengo acceso a internet'."
  )

  datos_reporte = (
      info_web
      if info_web
      else (
          "No se encontraron resultados externos adicionales. Respondé usando"
          " tu conocimiento previo."
      )
  )

  mensaje_con_contexto = (
      f"Consulta de Leandro: {orden}\n\n"
      f"[INFORMACIÓN OBTENIDA DE LA WEB PARA ESTA CONSULTA]:\n"
      f"{datos_reporte}\n\n"
      f"Instrucción: Respondé la consulta de Leandro utilizando la información"
      f" obtenida."
  )

  mensajes_chat = [{"role": "system", "content": system_prompt}]
  for m in historial[:-1]:
    mensajes_chat.append(m)

  mensajes_chat.append({"role": "user", "content": mensaje_con_contexto})

  respuesta = llamar_ollama(mensajes_chat)

  if respuesta:
    guardar_mensaje("assistant", respuesta)
  return respuesta
