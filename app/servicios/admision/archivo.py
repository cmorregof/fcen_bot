"""Reglas deterministas sobre el archivo, antes de llamar al modelo.

Todo ocurre en memoria: los bytes nunca se escriben en disco.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageStat, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.servicios.admision.config import config


@dataclass(frozen=True)
class Problema:
    tipo: str  # clave para las métricas: formato, peso, paginas, ilegible
    mensaje: str


@dataclass
class Archivo:
    """Archivo ya validado y listo para el modelo."""

    datos: bytes
    media_type: str
    es_pdf: bool
    paginas: int = 1
    problemas: list[Problema] = field(default_factory=list)


def _revisar_pdf(datos: bytes) -> tuple[int, list[Problema]]:
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            return 0, [
                Problema("formato", "El PDF tiene contraseña. Envíalo sin ella.")
            ]
        paginas = len(lector.pages)
    except (PyPdfError, ValueError, OSError):
        return 0, [Problema("formato", "No pude abrir el PDF; parece dañado.")]
    problemas: list[Problema] = []
    if paginas == 0:
        problemas.append(Problema("ilegible", "El PDF no tiene páginas."))
    elif paginas > config.max_paginas:
        problemas.append(
            Problema(
                "paginas",
                f"El PDF tiene {paginas} páginas; el máximo es {config.max_paginas}.",
            )
        )
    return paginas, problemas


def _preparar_imagen(datos: bytes) -> tuple[bytes, list[Problema]]:
    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except (UnidentifiedImageError, OSError):
        return b"", [Problema("formato", "No pude abrir la imagen.")]
    problemas: list[Problema] = []
    if min(img.size) < config.lado_minimo_px:
        problemas.append(
            Problema(
                "ilegible",
                "La imagen es muy pequeña; tómala de nuevo con más resolución.",
            )
        )
    gris = img.convert("L")
    if ImageStat.Stat(gris).stddev[0] < 8:
        problemas.append(
            Problema("ilegible", "La imagen está casi en blanco o muy oscura.")
        )
    rgb = img.convert("RGB")
    rgb.thumbnail((config.lado_maximo_px, config.lado_maximo_px))
    salida = io.BytesIO()
    rgb.save(salida, format="JPEG", quality=88)  # re-codificar quita el EXIF
    return salida.getvalue(), problemas


def revisar(datos: bytes, mime: str | None = None) -> Archivo:
    """Aplica las reglas de tipo, peso, páginas y legibilidad básica."""
    if len(datos) > config.max_bytes:
        mb = config.max_bytes / 1_000_000
        return Archivo(
            b"",
            "",
            False,
            0,
            [Problema("peso", f"El archivo pesa demasiado; el máximo es {mb:.0f} MB.")],
        )
    if datos[:5] == b"%PDF-":
        paginas, problemas = _revisar_pdf(datos)
        return Archivo(datos, "application/pdf", True, paginas, problemas)
    if datos[:3] == b"\xff\xd8\xff" or datos[:8] == b"\x89PNG\r\n\x1a\n":
        jpeg, problemas = _preparar_imagen(datos)
        return Archivo(jpeg, "image/jpeg", False, 1, problemas)
    return Archivo(
        b"",
        "",
        False,
        0,
        [Problema("formato", "Solo acepto PDF o fotos (JPG o PNG).")],
    )
