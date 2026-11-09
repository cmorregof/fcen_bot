"""Imágenes de firma de quien firma por cada programa.

Las firmas no van en el repositorio (es público). Viven en FIRMAS_DIR, por
defecto <DATA_DIR>/actas/firmas en el volumen, con el nombre de la clave del
programa: matematicas.png, ciencias_computacion.jpg… Firma el primer integrante
del comité (app/core/programas.py). El procedimiento para cargarlas está en
docs/integrantes-y-firmas.md.

Uso, dentro del servicio de actas:

    python -m app.services.firmas                    # qué programas tienen firma
    python -m app.services.firmas cargar <clave>     # pega el base64 y Ctrl-D
    python -m app.services.firmas cargar <clave> <archivo.png>
"""

from __future__ import annotations

import base64
import binascii
import sys
from pathlib import Path

from app.core.config import settings
from app.core.programas import PROGRAMAS

_FIRMAS: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
}
EXTENSIONES = (".png", ".jpg", ".jpeg")
MAX_BYTES = 2 * 1024 * 1024


def ruta_firma(clave: str, directorio: Path | None = None) -> Path | None:
    """La imagen de firma del programa, si está cargada."""
    carpeta = directorio or settings.firmas_dir
    for extension in EXTENSIONES:
        ruta = carpeta / f"{clave}{extension}"
        if ruta.is_file():
            return ruta
    return None


def extension_de(datos: bytes) -> str:
    """.png o .jpg según el contenido; ValueError si no es una imagen válida."""
    if len(datos) > MAX_BYTES:
        raise ValueError("La imagen pesa más de 2 MB.")
    for cabecera, extension in _FIRMAS.items():
        if datos.startswith(cabecera):
            return extension
    raise ValueError("La firma debe ser una imagen PNG o JPG.")


def guardar_firma(clave: str, datos: bytes, directorio: Path | None = None) -> Path:
    """Guarda la firma del programa y borra la anterior, si tenía otra extensión."""
    if clave not in PROGRAMAS:
        raise ValueError(f"No conozco el programa «{clave}».")
    extension = extension_de(datos)
    carpeta = directorio or settings.firmas_dir
    carpeta.mkdir(parents=True, exist_ok=True)
    for vieja in EXTENSIONES:
        (carpeta / f"{clave}{vieja}").unlink(missing_ok=True)
    destino = carpeta / f"{clave}{extension}"
    destino.write_bytes(datos)
    return destino


def estado(directorio: Path | None = None) -> list[str]:
    """Una línea por programa con comité: quién firma y si su firma está."""
    lineas = []
    for programa in PROGRAMAS.values():
        if not programa.miembros:
            continue
        firmante = programa.miembros[0].nombre
        ruta = ruta_firma(programa.clave, directorio)
        marca = f"✓ {ruta.name}" if ruta else "✗ sin firma"
        lineas.append(f"{programa.clave:22} {marca:28} {firmante}")
    return lineas


def _principal(argumentos: list[str]) -> int:
    if not argumentos:
        print(f"Firmas en {settings.firmas_dir}:")
        print("\n".join(estado()))
        return 0
    if argumentos[0] != "cargar" or len(argumentos) not in (2, 3):
        print(__doc__)
        return 2
    clave = argumentos[1]
    try:
        if len(argumentos) == 3:
            datos = Path(argumentos[2]).read_bytes()
        else:
            print("Pega la imagen en base64 y termina con Ctrl-D:", file=sys.stderr)
            datos = base64.b64decode("".join(sys.stdin.read().split()), validate=True)
        destino = guardar_firma(clave, datos)
    except (OSError, ValueError, binascii.Error) as error:
        print(f"No se guardó la firma: {error}", file=sys.stderr)
        return 1
    print(f"Firma de {clave} guardada en {destino}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_principal(sys.argv[1:]))
