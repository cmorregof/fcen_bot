"""Formatos de solicitud que diligencian los estudiantes (PDF o Word).

Un formato se reconoce por su título («FORMATO DE …»). Se lee su texto aquí,
sin el modelo; al modelo solo llega ese texto, igual que un correo pegado. Los
demás PDF (certificados, soportes médicos) no se leen ni se guardan: solo se
registra su nombre.

Si el PDF no tiene texto (escaneado o foto), no se puede saber qué es. Entonces
la administrativa decide con un botón si es el formato; si lo es, sus páginas
se convierten en imágenes y se tratan como pantallazos.
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import tempfile
from pathlib import Path

from docx import Document

from app.core.programas import normalizar

logger = logging.getLogger(__name__)

EXTENSIONES = {".pdf", ".docx"}
MAX_BYTES = 20 * 1024 * 1024  # límite de descarga de la API de bots
MAX_PAGINAS = 3


def es_formato(texto: str) -> bool:
    inicio = normalizar(" ".join(texto.split()[:60]))
    return "formato de " in inicio or "formato para " in inicio


def texto_docx(datos: bytes) -> str:
    """Párrafos y tablas en orden; cada fila de una tabla en una línea."""
    doc = Document(io.BytesIO(datos))
    lineas: list[str] = []
    cuerpo = doc.element.body
    for elemento in cuerpo.iterchildren():
        etiqueta = elemento.tag.rsplit("}", 1)[-1]
        if etiqueta == "p":
            texto = "".join(
                t.text or "" for t in elemento.iter() if t.tag.endswith("}t")
            )
            lineas.append(texto.strip())
        elif etiqueta == "tbl":
            for fila in elemento.iter():
                if not fila.tag.endswith("}tr"):
                    continue
                celdas: list[str] = []
                for celda in fila.iterchildren():
                    if not celda.tag.endswith("}tc"):
                        continue
                    valor = " ".join(
                        "".join(
                            t.text or "" for t in celda.iter() if t.tag.endswith("}t")
                        ).split()
                    )
                    celdas.append(valor)
                if any(celdas):
                    lineas.append(" | ".join(celdas))
    texto = "\n".join(lineas)
    while "\n\n\n" in texto:
        texto = texto.replace("\n\n\n", "\n\n")
    return texto.strip()


async def _ejecutar(*args: str, timeout: float = 60) -> bool:
    proceso = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        await asyncio.wait_for(proceso.wait(), timeout)
    except TimeoutError:
        proceso.kill()
        return False
    return proceso.returncode == 0


async def texto_pdf(datos: bytes) -> str:
    if shutil.which("pdftotext") is None:
        logger.warning("pdftotext (poppler-utils) no está instalado.")
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        entrada, salida = Path(tmp) / "f.pdf", Path(tmp) / "f.txt"
        entrada.write_bytes(datos)
        if not await _ejecutar("pdftotext", "-layout", str(entrada), str(salida)):
            return ""
        texto = salida.read_text(encoding="utf-8", errors="replace")
    lineas = [ln.rstrip() for ln in texto.replace("\f", "\n").splitlines()]
    return "\n".join(lineas).strip()


async def texto_de_archivo(datos: bytes, extension: str) -> str:
    try:
        if extension == ".docx":
            return texto_docx(datos)
        if extension == ".pdf":
            return await texto_pdf(datos)
    except Exception:
        logger.warning("No pude leer el archivo %s", extension, exc_info=True)
    return ""


async def paginas_pdf(pdf: Path, carpeta: Path, prefijo: str) -> list[Path]:
    """Las primeras páginas del PDF como PNG, para leerlas como pantallazos."""
    if shutil.which("pdftoppm") is None:
        logger.warning("pdftoppm (poppler-utils) no está instalado.")
        return []
    carpeta.mkdir(parents=True, exist_ok=True)
    base = carpeta / prefijo
    ok = await _ejecutar(
        "pdftoppm", "-r", "110", "-png", "-l", str(MAX_PAGINAS), str(pdf), str(base)
    )
    if not ok:
        return []
    return sorted(carpeta.glob(f"{prefijo}*.png"))
