```python
import os
import time
from datetime import datetime

def manejar_estado(update, context):
    # Uptime
    uptime = time.time() - os.path.getctime(__file__)
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    days = int(days) if days > 0 else 0
    uptime = f"{days} días, {hours} horas, {minutes} minutos, {seconds} segundos"

    # Memoria RAM
    memram = str(round(os.popen('ps -ef | awk \'{print $4}\' | grep -c python3\'').stdout, 2)) + ' MB'
    memram = f'memram: {memram}'

    # Actualización de la fecha
    fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Preparación de la respuesta
    respuesta = f"Che, fijate que el uptime es: {uptime} y la memoria RAM es: {memram}. Posta. ¡Che! \nFecha Actual: {fecha_actual}"

    return respuesta

# Agregar el comando al bot
app.add_handler(CommandHandler("estado", manejar_estado))

# Commit y push del código actualizado
os.system("git add .")
os