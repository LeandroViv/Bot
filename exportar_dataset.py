import json
import os
from huggingface_hub import HfApi

TXT_FILE = "conversaciones.txt"
OUTPUT_JSONL = "dataset.jsonl"
HF_TOKEN = os.environ.get("HF_TOKEN")
HF_REPO = os.environ.get("HF_REPO")

SYSTEM_PROMPT = (
    "Sos Leandro Bot, el asistente personal de Leandro. "
    "Hablá siempre en español rioplatense (usá 'vos', 'che', 'mirá', 'fijate') "
    "y sé directo, conciso y técnico, sin armar resúmenes largos ni guías de SEO."
)

def generar_y_subir_dataset():
    if not os.path.exists(TXT_FILE):
        print(f"❌ No existe {TXT_FILE}")
        return

    with open(TXT_FILE, "r", encoding="utf-8") as f:
        contenido = f.read()

    bloques = [b.strip() for b in contenido.split("---\n") if b.strip()]
    ejemplos = []

    i = 0
    while i < len(bloques) - 1:
        bloque_usr = bloques[i]
        bloque_bot = bloques[i + 1]

        if bloque_usr.startswith("[USUARIO]:") and bloque_bot.startswith("[LEANDRO_BOT]:"):
            texto_usr = bloque_usr.replace("[USUARIO]:", "").strip()
            texto_bot = bloque_bot.replace("[LEANDRO_BOT]:", "").strip()

            # Filtramos interacciones donde el bot se haya equivocado tirando choclos de SEO o errores largos
            es_basura_seo = "palabras clave" in texto_bot.lower() or "optimización seo" in texto_bot.lower() or len(texto_bot) > 1200

            if texto_usr and texto_bot and not es_basura_seo:
                ejemplos.append({
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": texto_usr},
                        {"role": "assistant", "content": texto_bot}
                    ]
                })
            i += 2
        else:
            i += 1

    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for ej in ejemplos:
            f.write(json.dumps(ej, ensure_ascii=False) + "\n")

    print(f"✅ Dataset local preparado y filtrado: {len(ejemplos)} interacciones limpias.")

    if HF_TOKEN and HF_REPO:
        try:
            api = HfApi()
            api.upload_file(
                path_or_fileobj=OUTPUT_JSONL,
                path_in_repo="dataset.jsonl",
                repo_id=HF_REPO,
                repo_type="dataset",
                token=HF_TOKEN
            )
            print("🚀 Dataset subido automáticamente a Hugging Face.")
        except Exception as e:
            print(f"⚠️️ Error subiendo dataset a HF: {e}")

if __name__ == "__main__":
    generar_y_subir_dataset()
