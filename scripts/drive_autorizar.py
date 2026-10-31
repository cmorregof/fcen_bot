"""Autoriza a MemorIA a escribir en Google Drive y crea su carpeta raíz.

Se corre una vez, en la máquina de quien es dueño de la cuenta @unal.edu.co
(hoy Carlos; luego la Vicedecanatura). Abre el navegador con el flujo local
de OAuth (PKCE, redirección a 127.0.0.1), pide solo el alcance `drive.file`
y, con esa misma autorización, crea la carpeta raíz «MemorIA». Así la
aplicación ve la carpeta aunque el alcance no le deje ver nada más del Drive.

Al final imprime DRIVE_REFRESH_TOKEN y DRIVE_CARPETA_ID para ponerlos en
Railway. No escribe nada en disco ni en el repositorio.

Uso:
    DRIVE_CLIENT_ID=... DRIVE_CLIENT_SECRET=... uv run python scripts/drive_autorizar.py
    (o con las dos variables en .env)

Opciones:
    --carpeta NOMBRE   nombre de la carpeta raíz (por defecto «MemorIA»)
    --carpeta-id ID    no crear carpeta: usar una que esta misma app ya creó
Ver docs/respaldo-drive.md.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.drive.cliente import ALCANCE, MIME_CARPETA, URL_TOKEN  # noqa: E402

URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
URL_ARCHIVOS = "https://www.googleapis.com/drive/v3/files"


def _variable(nombre: str) -> str:
    valor = os.environ.get(nombre, "")
    if not valor:
        try:
            from app.core.config import settings

            valor = str(getattr(settings, nombre.lower(), ""))
        except Exception:  # noqa: BLE001 - sin .env válido, solo el entorno
            valor = ""
    if not valor:
        sys.exit(f"Falta {nombre}. Defínala en el entorno o en .env.")
    return valor


class _Respuesta(http.server.BaseHTTPRequestHandler):
    datos: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - nombre de la librería estándar
        consulta = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Respuesta.datos = {k: v[0] for k, v in consulta.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        texto = (
            "Listo. Puede cerrar esta pestaña y volver a la terminal."
            if "code" in _Respuesta.datos
            else "No se autorizó. Vuelva a la terminal."
        )
        self.wfile.write(f"<p>{texto}</p>".encode())

    def log_message(self, *_: object) -> None:
        return


def _codigo(client_id: str) -> tuple[str, str, str]:
    """Devuelve (código, verificador PKCE, redirect_uri)."""
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _Respuesta)
    redirect = f"http://127.0.0.1:{servidor.server_port}"
    verificador = secrets.token_urlsafe(64)
    reto = (
        base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    estado = secrets.token_urlsafe(16)
    url = (
        URL_AUTORIZAR
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": ALCANCE,
                "access_type": "offline",
                "prompt": "consent",  # para que Google entregue el refresh token
                "code_challenge": reto,
                "code_challenge_method": "S256",
                "state": estado,
            }
        )
    )
    hilo = threading.Thread(target=servidor.handle_request, daemon=True)
    hilo.start()
    print(
        "Abriendo el navegador. Ingrese con la cuenta @unal.edu.co dueña del archivo."
    )
    print(f"Si no se abre, copie esta dirección:\n\n{url}\n")
    webbrowser.open(url)
    hilo.join(timeout=300)
    servidor.server_close()
    datos = _Respuesta.datos
    if datos.get("state") != estado or "code" not in datos:
        sys.exit(
            f"No se recibió la autorización ({datos.get('error', 'sin respuesta')})."
        )
    return datos["code"], verificador, redirect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--carpeta", default="MemorIA")
    parser.add_argument("--carpeta-id", default="")
    args = parser.parse_args()

    client_id = _variable("DRIVE_CLIENT_ID")
    client_secret = _variable("DRIVE_CLIENT_SECRET")
    codigo, verificador, redirect = _codigo(client_id)

    r = httpx.post(
        URL_TOKEN,
        data={
            "grant_type": "authorization_code",
            "code": codigo,
            "code_verifier": verificador,
            "redirect_uri": redirect,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    if r.status_code != 200:
        sys.exit(f"Google no entregó el token: {r.text[:300]}")
    tokens = r.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit(
            "Google no entregó refresh token. Quite el acceso de la app en "
            "https://myaccount.google.com/permissions y vuelva a correr el script."
        )
    acceso = {"Authorization": f"Bearer {tokens['access_token']}"}

    carpeta_id = args.carpeta_id
    if not carpeta_id:
        r = httpx.post(
            URL_ARCHIVOS,
            params={"fields": "id, webViewLink", "supportsAllDrives": "true"},
            json={"name": args.carpeta, "mimeType": MIME_CARPETA},
            headers=acceso,
            timeout=30,
        )
        if r.status_code >= 400:
            sys.exit(f"No pude crear la carpeta: {r.text[:300]}")
        carpeta_id = r.json()["id"]
        print(f"Carpeta «{args.carpeta}» creada: {r.json().get('webViewLink', '')}")

    print("\nPonga estas variables en Railway (actas, calidad y admisión):\n")
    print(f"DRIVE_REFRESH_TOKEN={refresh}")
    print(f"DRIVE_CARPETA_ID={carpeta_id}")
    print("\nNo las guarde en el repositorio ni las envíe por chat.")


if __name__ == "__main__":
    main()
