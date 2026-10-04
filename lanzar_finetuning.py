import os
import time
from together import Together

TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY")
DATASET_FILE = "dataset.jsonl"
# Podés cambiar la base según disponibilidad (ej. Meta-Llama-3-8B-Instruct o similar)
BASE_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"

def ejecutar_finetuning():
    if not TOGETHER_API_KEY:
        print("❌ Error: Falta TOGETHER_API_KEY en las variables de entorno.")
        return

    if not os.path.exists(DATASET_FILE):
        print(f"❌ Error: No existe {DATASET_FILE}. Generalo primero con exportar_dataset.py.")
        return

    client = Together(api_key=TOGETHER_API_KEY)

    print("📤 Subiendo dataset.jsonl a Together AI...")
    archivo_subido = client.files.upload(
        file=DATASET_FILE,
        purpose="fine-tune"
    )
    file_id = archivo_subido.id
    print(f"✅ Archivo subido con ID: {file_id}")

    print(f"🚀 Iniciando trabajo de Fine-Tuning sobre {BASE_MODEL}...")
    job = client.fine_tuning.create(
        training_file=file_id,
        model=BASE_MODEL,
        n_epochs=3,
        n_checkpoints=1,
        lora=True,
        suffix="leandro-bot-ft"
    )
    job_id = job.id
    print(f"📌 Trabajo encolado con ID: {job_id}")

    # Monitoreo simple en consola
    print("⏳ Esperando progreso del entrenamiento...")
    while True:
        estado = client.fine_tuning.retrieve(job_id)
        status = estado.status
        print(f"Status actual: {status}")

        if status in ["completed", "failed", "cancelled"]:
            if status == "completed":
                print(f"🎉 Fine-tuning completado con éxito!")
                print(f"Modelo resultado: {estado.fine_tuned_model}")
            else:
                print(f"❌ El trabajo terminó con estado: {status}")
            break

        time.sleep(30)

if __name__ == "__main__":
    ejecutar_finetuning()
