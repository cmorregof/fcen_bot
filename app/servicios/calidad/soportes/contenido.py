"""Qué se le manda al modelo de cada archivo: lo mínimo para describirlo.

- PDF: las primeras páginas como documento + el texto extraído (recortado).
- Imagen: reducida a un lado mayor de 1568 px.
- xlsx: solo nombres de hojas, encabezados y número de filas. Nunca las filas.
- docx: el texto de los primeros párrafos.
En todo texto se ocultan los correos electrónicos.
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass, field
from typing import Any

from app.servicios.calidad.soportes.modelos import Archivo

PAGINAS_PDF = 4
CARACTERES_TEXTO = 6000
LADO_IMAGEN = 1568
PATRON_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def sin_correos(texto: str) -> str:
    return PATRON_CORREO.sub("[correo]", texto)


@dataclass
class Contenido:
    """Bloques para la API y una nota de lo que se omitió."""

    bloques: list[dict[str, Any]] = field(default_factory=list)
    texto: str = ""
    paginas_enviadas: int = 0
    nota: str = ""
    enviable: bool = True


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def pdf(datos: bytes, paginas: int = PAGINAS_PDF) -> Contenido:
    from pypdf import PdfReader, PdfWriter

    lector = PdfReader(io.BytesIO(datos))
    total = len(lector.pages)
    textos: list[str] = []
    for pagina in lector.pages:
        try:
            textos.append(pagina.extract_text() or "")
        except Exception:
            textos.append("")
        if sum(len(t) for t in textos) > CARACTERES_TEXTO:
            break
    texto = sin_correos(" ".join(" ".join(textos).split()))[:CARACTERES_TEXTO]

    if total <= paginas:
        recorte = datos
    else:
        escritor = PdfWriter()
        for i in range(paginas):
            escritor.add_page(lector.pages[i])
        salida = io.BytesIO()
        escritor.write(salida)
        recorte = salida.getvalue()
    enviadas = min(total, paginas)
    nota = (
        f"PDF de {total} páginas; se envían las primeras {enviadas}."
        if total > paginas
        else f"PDF de {total} páginas."
    )
    bloque = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": _b64(recorte),
        },
    }
    return Contenido([bloque], texto, enviadas, nota)


def imagen(datos: bytes) -> Contenido:
    from PIL import Image

    with Image.open(io.BytesIO(datos)) as img:
        img.thumbnail((LADO_IMAGEN, LADO_IMAGEN))
        rgb = img.convert("RGB")
        salida = io.BytesIO()
        rgb.save(salida, format="JPEG", quality=85)
    bloque = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": _b64(salida.getvalue()),
        },
    }
    return Contenido([bloque], "", 1, "Imagen reducida.")


def resumen_xlsx(datos: bytes) -> str:
    """Hojas, encabezados y número de filas. Las filas no salen de aquí."""
    from openpyxl import load_workbook

    libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    lineas: list[str] = []
    for hoja in libro.worksheets:
        encabezado: list[str] = []
        filas_con_datos = 0
        for fila in hoja.iter_rows(values_only=True):
            celdas = [str(c).strip() for c in fila if c is not None and str(c).strip()]
            if not celdas:
                continue
            if not encabezado and len(celdas) >= 2:
                encabezado = [sin_correos(c)[:60] for c in celdas[:30]]
                continue
            if encabezado:
                filas_con_datos += 1
        lineas.append(
            f"Hoja «{hoja.title}»: encabezados {encabezado or '(no se detectaron)'}; "
            f"{filas_con_datos} filas con datos bajo el encabezado."
        )
    libro.close()
    return "\n".join(lineas)


def xlsx(datos: bytes) -> Contenido:
    texto = resumen_xlsx(datos)
    return Contenido(
        [], texto, 0, "Hoja de cálculo: solo hojas, encabezados y número de filas."
    )


def docx(datos: bytes) -> Contenido:
    from docx import Document

    doc = Document(io.BytesIO(datos))
    texto = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    texto = sin_correos(texto)[:CARACTERES_TEXTO]
    return Contenido([], texto, 0, "Documento Word: texto de los primeros párrafos.")


def preparar(archivo: Archivo, datos: bytes) -> Contenido:
    if archivo.tipo == "pdf":
        return pdf(datos)
    if archivo.tipo == "imagen":
        return imagen(datos)
    if archivo.tipo == "xlsx":
        return xlsx(datos)
    if archivo.tipo == "docx":
        return docx(datos)
    if archivo.tipo == "zip":
        miembros = "\n".join(f"- {m}" for m in archivo.miembros[:200])
        return Contenido(
            [],
            f"Archivo comprimido con {len(archivo.miembros)} archivos:\n{miembros}",
            0,
            "Zip: se describe por su lista de archivos; cada archivo interno se "
            "describe aparte.",
        )
    return Contenido(
        enviable=False, nota=f"Tipo {archivo.extension} no se envía al modelo."
    )
