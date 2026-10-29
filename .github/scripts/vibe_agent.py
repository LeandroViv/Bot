#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vibe_agent.py - builder que corre Ollama en el propio runner de Actions.

Flujo:
  1. Escanea el repo (con tope de contexto, para no reventar la ventana).
  2. Le pide al modelo un JSON {ruta: contenido}.
  3. Aplica los archivos y valida que compilen.
  4. Si falla, reintenta pasandole el error.
  5. Pushea a una rama y abre un PR.

NUNCA toca main: todo va a una rama `vibe/issue-N` y sale como PR.
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODELO = os.environ.get("VIBE_MODEL", "qwen2.5-coder:3b")
MAX_CONTEXT_CHARS = int(os.environ.get("VIBE_MAX_CONTEXT", "60000"))
MAX_INTENTOS = int(os.environ.get("VIBE_MAX_TRIES", "3"))
PROMPT = os.environ.get("PROMPT_CHAT", "").strip()
NRO_ISSUE = os.environ.get("ISSUE_NUMBER", "").strip()
REPO = os.environ.get("REPO", "").strip()
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
API = "https://api.github.com"

# Carpetas que no se escanean: dependencias, caches y basura de build.
CARPETAS_SALTADAS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "vendor",
    ".ollama", ".hf_cache", "dist", "build", ".pytest_cache", ".mypy_cache",
}
EXTENSIONES = (
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".txt", ".md",
    ".yml", ".yaml", ".toml", ".cfg", ".ini", ".html", ".css", ".sh",
)
# Archivos enormes que no aportan y ocupan todo el contexto.
NOMBRES_SALTADOS = {
    "package-lock.json", "yarn.lock", "poetry.lock", "uv.lock",
    "conversaciones.txt", "historial_metricas_voz.json",
}


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Escaneo del repositorio
# --------------------------------------------------------------------------

def escanear_repositorio():
    """Devuelve un mapa textual del repo, recortado al tope de contexto.

    Ordena por tamaño ascendente antes de llenar el presupuesto. Sin esto, un
    solo archivo de datos enorme (un historial, un dataset) se come el
    presupuesto entero y deja afuera el código fuente real.
    """
    candidatos = []
    for raiz, directorios, archivos in os.walk("."):
        directorios[:] = [d for d in directorios if d not in CARPETAS_SALTADAS]
        for archivo in archivos:
            if archivo in NOMBRES_SALTADOS or not archivo.endswith(EXTENSIONES):
                continue
            ruta = os.path.relpath(os.path.join(raiz, archivo), ".")
            try:
                with open(ruta, encoding="utf-8") as fh:
                    contenido = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            candidatos.append((len(contenido), ruta, contenido))

    candidatos.sort(key=lambda c: c[0])
    partes, total, recortado = [], 0, []
    for tamano, ruta, contenido in candidatos:
        if total + tamano > MAX_CONTEXT_CHARS:
            recortado.append(ruta)
            continue
        partes.append(f"\n--- ARCHIVO: {ruta} ---\n{contenido}\n")
        total += tamano
    if not partes:
        return "[El repositorio está vacío o no tiene archivos de texto]"
    mapa = "".join(partes)
    if recortado:
        mapa += ("\n[AVISO: estos archivos no entraron por el tope de contexto: "
                 + ", ".join(recortado) + "]")
    return mapa


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------

SISTEMA = (
    "Sos un agente que construye software. Se te da el estado COMPLETO del "
    "repositorio y un pedido. AUDITA lo que ya existe: si algo ya se puede "
    "resolver con archivos o funciones que ya están, reutilizalo en vez de "
    "duplicar.\n"
    "Responde EXCLUSIVAMENTE con un JSON válido, sin markdown ni texto extra, "
    "con esta forma: {\"ruta/archivo.py\": \"contenido completo del archivo\"}.\n"
    "Incluí el contenido COMPLETO de cada archivo que crees o modifiques, no "
    "parches ni fragmentos."
)


def consultar_ollama(mapa_repo, error_previo=""):
    instruccion = SISTEMA
    if error_previo:
        instruccion += (
            "\n\nATENCION: el intento anterior falló con este error. "
            f"Corregilo:\n{error_previo}"
        )
    prompt = (
        f"{instruccion}\n\nESTADO DEL REPOSITORIO:\n{mapa_repo}\n\n"
        f"PEDIDO:\n{PROMPT}\n\nJSON:"
    )
    payload = json.dumps({
        "model": MODELO,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 16384},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate", data=payload, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.load(resp).get("response", "").strip()
    except Exception as exc:  # noqa: BLE001 - cualquier falla cae al reporte
        return f"__ERROR_OLLAMA__ {exc!r}"


# --------------------------------------------------------------------------
# Parseo de la respuesta
# --------------------------------------------------------------------------

def extraer_json(texto):
    """Saca el JSON de la respuesta del modelo, tolerando lo que ensucia.

    Los modelos chicos suelen envolver en ```json o agregar texto antes y
    despues. Buscamos el primer objeto balanceado en vez de confiar en que
    el texto sea JSON puro.
    """
    if not texto or texto.startswith("__ERROR_OLLAMA__"):
        return None
    limpio = re.sub(r"```(?:json)?", "", texto).strip()
    inicio = limpio.find("{")
    if inicio == -1:
        return None
    profundidad, en_string, escape = 0, False, False
    for i, ch in enumerate(limpio[inicio:], start=inicio):
        if en_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                en_string = False
            continue
        if ch == '"':
            en_string = True
        elif ch == "{":
            profundidad += 1
        elif ch == "}":
            profundidad -= 1
            if profundidad == 0:
                try:
                    datos = json.loads(limpio[inicio:i + 1])
                    return datos if isinstance(datos, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def aplicar_archivos(estructura):
    """Escribe los archivos pedidos. Devuelve la lista de rutas escritas."""
    escritas = []
    for ruta, contenido in estructura.items():
        if not isinstance(contenido, str) or not ruta.strip():
            continue
        # Sin esto un modelo puede escribir fuera del repo (../../etc).
        normalizada = os.path.normpath(ruta).lstrip("/")
        if normalizada.startswith("..") or os.path.isabs(normalizada):
            log(f"⚠️  Ruta rechazada por insegura: {ruta}")
            continue
        padre = os.path.dirname(normalizada)
        if padre:
            os.makedirs(padre, exist_ok=True)
        with open(normalizada, "w", encoding="utf-8") as fh:
            fh.write(contenido)
        escritas.append(normalizada)
    return escritas


# --------------------------------------------------------------------------
# Verificacion
# --------------------------------------------------------------------------

def validar(escritas):
    """Devuelve (ok, detalle). Chequea sintaxis de lo que se tocó.

    Es a proposito conservador: si no hay nada que correr, da ok y lo dice.
    """
    if not escritas:
        return False, "El modelo no devolvió ningún archivo para escribir."
    py = [r for r in escritas if r.endswith(".py")]
    if py:
        res = subprocess.run(
            [sys.executable, "-m", "py_compile", *py],
            capture_output=True, text=True)
        if res.returncode != 0:
            return False, (res.stderr or res.stdout).strip()[-2000:]
    return True, f"Sintaxis OK en {len(escritas)} archivo(s)."


# --------------------------------------------------------------------------
# Git + PR
# --------------------------------------------------------------------------

def git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=check)


def api(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def publicar(escritas, resumen):
    """Commitea en una rama nueva y abre el PR. Devuelve (numero, url)."""
    rama = f"vibe/issue-{NRO_ISSUE}" if NRO_ISSUE else "vibe/cambio"
    git("config", "user.name", "vibe-agent[bot]")
    git("config", "user.email", "vibe-agent@users.noreply.github.com")
    git("checkout", "-B", rama)
    git("add", "-A")
    git("commit", "-m", f"vibe: {resumen}")
    git("push", "--force", "origin", rama)

    cuerpo = (
        f"Generado por el vibe agent (Ollama `{MODELO}`) a partir del "
        f"{'issue #' + NRO_ISSUE if NRO_ISSUE else 'pedido'}.\n\n"
        f"**Archivos:** {', '.join(f'`{r}`' for r in escritas)}\n\n"
        f"**Verificación:** {resumen}\n\n"
        "Revisá el diff antes de mergear: el modelo es chico y puede "
        "equivocarse.\n\n"
        "_Este PR fue creado por un agente de IA (vibe agent)._\n"
    )
    pr = api("POST", f"/repos/{REPO}/pulls", {
        "title": f"vibe: {resumen}",
        "head": rama,
        "base": os.environ.get("BASE_BRANCH", "main"),
        "body": cuerpo,
    })
    return pr.get("number"), pr.get("html_url")


# --------------------------------------------------------------------------

def main():
    if not PROMPT:
        log("Sin pedido (PROMPT_CHAT vacío): no hay nada que hacer.")
        return 0
    log(f"🔍 Escaneando repositorio (tope {MAX_CONTEXT_CHARS} chars)...")
    mapa = escanear_repositorio()
    log(f"   contexto: {len(mapa)} chars")

    error, escritas, resumen = "", [], ""
    for intento in range(1, MAX_INTENTOS + 1):
        log(f"🔄 Intento {intento}/{MAX_INTENTOS}")
        estructura = extraer_json(consultar_ollama(mapa, error))
        if estructura is None:
            error = ("Tu respuesta anterior no era un JSON válido. Responde "
                     "SOLO con el objeto JSON {ruta: contenido}.")
            continue
        escritas = aplicar_archivos(estructura)
        ok, resumen = validar(escritas)
        if ok:
            break
        error = resumen
    else:
        _reporte(False, error, escritas)
        return 1

    try:
        nro, url = publicar(escritas, resumen)
        _reporte(True, f"PR #{nro}: {url}", escritas)
    except (urllib.error.HTTPError, subprocess.CalledProcessError) as exc:
        detalle = (exc.read().decode()
                   if isinstance(exc, urllib.error.HTTPError) else str(exc))
        _reporte(False, f"No pude publicar: {detalle[:500]}", escritas)
        return 1
    return 0


def _reporte(ok, detalle, escritas):
    lineas = ["### 🤖 Vibe Agent\n"]
    if ok:
        lineas.append(f"✅ Listo. {detalle}\n")
    else:
        lineas.append(f"⚠️ No pude cerrar el cambio.\n\n```text\n{detalle}\n```\n")
    if escritas:
        lineas.append("**Archivos tocados:**\n")
        lineas += [f"- `{r}`\n" for r in escritas]
    lineas.append("\n_Generado por un agente de IA (vibe agent)._\n")
    with open("vibe_report.txt", "w", encoding="utf-8") as fh:
        fh.write("".join(lineas))


if __name__ == "__main__":
    sys.exit(main())
