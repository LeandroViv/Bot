import json
import os

TXT_FILE = "conversaciones.txt"
OUTPUT_JSONL = "dataset.jsonl"

SYSTEM_PROMPT = (
    "Sos Leandro Bot, el asistente personal de Leandro. "
    "Hablá siempre en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate') "
    "y sé directo, conciso y técnico."
)


def generar_dataset():
  if not os.path.exists(TXT_FILE):
    print(f"❌ No existe el archivo {TXT_FILE}")
    return

  with open(TXT_FILE, "r", encoding="utf-8") as f:
    contenido = f.read()

  bloques = [b.strip() for b in contenido.split("---\n") if b.strip()]
  ejemplos = []

  i = 0
  while i < len(bloques) - 1:
    bloque_usr = bloques[i]
    bloque_bot = bloques[i + 1]

    if bloque_usr.startswith("[USUARIO]:") and bloque_bot.startswith(
        "[LEANDRO_BOT]:"
    ):
      texto_usr = bloque_usr.replace("[USUARIO]:", "").strip()
      texto_bot = bloque_bot.replace("[LEANDRO_BOT]:", "").strip()

      # Filtrar respuestas genéricas o de error para mantener la calidad del dataset
      if (
          texto_usr
          and texto_bot
          and "demoró en responder" not in texto_bot
          and len(texto_bot) > 10
      ):
        ejemplo = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": texto_usr},
                {"role": "assistant", "content": texto_bot},
            ]
        }
        ejemplos.append(ejemplo)
      i += 2
    else:
      i += 1

  with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
    for ej in ejemplos:
      f.write(json.dumps(ej, ensure_ascii=False) + "\n")

  print(
      f"✅ Dataset generado con {len(ejemplos)} interacciones en"
      f" {OUTPUT_JSONL}"
  )


if __name__ == "__main__":
  generar_dataset()
