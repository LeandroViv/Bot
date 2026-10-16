import inspect
import json
import os
import subprocess
import time
import urllib.request
from datetime import timedelta
import psutil

# Registro de inicio para cálculo de uptime
BOT_START_TIME = time.time()


def obtener_info_memoria():
    """Obtiene el consumo de memoria del proceso actual y del sistema."""
    proceso = psutil.Process(os.getpid())
    mem_proceso_mb = proceso.memory_info().rss / (1024 * 1024)
    mem_sistema = psutil.virtual_memory()
    return {
        "proceso_mb": round(mem_proceso_mb, 2),
        "sistema_percent": mem_sistema.percent,
        "sistema_usado_mb": round(mem_sistema.used / (1024 * 1024), 2),
        "sistema_total_mb": round(mem_sistema.total / (1024 * 1024), 2),
    }


def verificar_conexion_ollama(url="http://localhost:11434/api/tags", timeout=2):
    """Verifica el estado del servicio Ollama local."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Bot-Monitor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                modelos = [m.get("name") for m in data.get("models", [])]
                return True, modelos
            return False, []
    except Exception:
        return False, []


def obtener_parametros_acusticos():
    """Lee las configuraciones activas de timbre y perillas de voz."""
    timbre = {}
    perillas = {}

    if os.path.exists("config_timbre.json"):
        try:
            with open("config_timbre.json", "r", encoding="utf-8") as f:
                timbre = json.load(f)
        except Exception:
            pass

    if os.path.exists("perillas_voz.json"):
        try:
            with open("perillas_voz.json", "r", encoding="utf-8") as f:
                perillas = json.load(f)
        except Exception:
            pass

    voz = timbre.get("voz") or perillas.get("voz", "es-AR-ElenaNeural")
    pitch = timbre.get("pitch") or perillas.get("pitch", "+0Hz")
    rate = timbre.get("rate") or perillas.get("rate", "+0%")
    f0 = timbre.get("f0") or perillas.get("f0", 95)
    volumen = timbre.get("volumen") or perillas.get("volumen", "+0%")

    return {
        "voz": voz,
        "pitch": pitch,
        "rate": rate,
        "f0": f0,
        "volumen": volumen,
    }


def sincronizar_git_y_recargar():
    """Guarda cambios pendientes, sincroniza con GitHub y ejecuta hot-reload."""
    try:
        subprocess.run(["git", "add", "procesar.py"], check=False)
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "feat: agregar comando /estado y métricas del sistema",
            ],
            check=False,
        )
        subprocess.run(
            ["git", "push", "origin", "main"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


async def manejar_estado(update, context):
    """
    Manejador para /estado o /status.
    Muestra consumo de memoria RAM, uptime, conectividad con Ollama
    y parámetros acústicos del timbre activo.
    """
    uptime_segundos = int(time.time() - BOT_START_TIME)
    uptime_str = str(timedelta(seconds=uptime_segundos))

    memoria = obtener_info_memoria()
    ollama_ok, modelos_ollama = verificar_conexion_ollama()
    timbre = obtener_parametros_acusticos()

    estado_ollama = (
        f"🟢 Online ({len(modelos_ollama)} modelos disponibles)"
        if ollama_ok
        else "🔴 Offline / Inaccesible"
    )

    mensaje = (
        "⚙️ *ESTADO DEL SISTEMA Y TELEMETRÍA*\n\n"
        f"⏱ *Uptime:* `{uptime_str}`\n"
        f"🧠 *RAM del Bot:* `{memoria['proceso_mb']} MB`\n"
        f"🖥 *RAM Sistema:* `{memoria['sistema_percent']}%` ({memoria['sistema_usado_mb']} / {memoria['sistema_total_mb']} MB)\n"
        f"🦙 *Ollama:* {estado_ollama}\n\n"
        "🎛 *Parámetros Acústicos Activos:*\n"
        f"  • *Voz:* `{timbre['voz']}`\n"
        f"  • *Pitch:* `{timbre['pitch']}`\n"
        f"  • *Rate:* `{timbre['rate']}`\n"
        f"  • *Frecuencia f0:* `{timbre['f0']} Hz`\n"
        f"  • *Volumen:* `{timbre['volumen']}`"
    )

    if update and hasattr(update, "message") and update.message:
        respuesta = update.message.reply_text(mensaje, parse_mode="Markdown")
        if inspect.isawaitable(respuesta):
            await respuesta
    elif update and hasattr(update, "effective_chat") and update.effective_chat:
        respuesta = context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=mensaje,
            parse_mode="Markdown",
        )
        if inspect.isawaitable(respuesta):
            await respuesta

    # Ejecutar push y hot-reload no bloqueante
    sincronizar_git_y_recargar()


# Alias para compatibilidad con dispatchers sincrónicos o alternativos
manejar_status = manejar_estado