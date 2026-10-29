"""Lectura de las fuentes (listado y guía) que van en el system prompt.

Las fuentes viven fuera del repositorio. Si un PDF es escaneado (casi sin capa
de texto) se le hace OCR una sola vez y el texto queda en una caché `.txt` junto
al PDF, dentro de la carpeta de insumos.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.servicios.admision.config import config

logger = logging.getLogger(__name__)

_MIN_CARACTERES_POR_PAGINA = 80
_SUFIJOS = {".pdf", ".txt", ".md"}


@dataclass(frozen=True)
class Fuente:
    nombre: str
    paginas: tuple[str, ...]

    def render(self) -> str:
        partes = [f'<fuente nombre="{self.nombre}">']
        for i, texto in enumerate(self.paginas, start=1):
            if texto.strip():
                partes.append(f"[{self.nombre}, página {i}]\n{texto.strip()}")
        partes.append("</fuente>")
        return "\n\n".join(partes)


def _texto_pdf(ruta: Path) -> list[str]:
    lector = PdfReader(str(ruta))
    return [(p.extract_text() or "") for p in lector.pages]


def _ocr(ruta: Path) -> list[str]:
    """OCR con ocrmypdf/tesseract (español). Devuelve el texto por página."""
    if shutil.which("ocrmypdf") is None:
        raise RuntimeError(
            f"{ruta.name} está escaneado y falta ocrmypdf/tesseract para leerlo."
        )
    with tempfile.TemporaryDirectory() as tmp:
        lado = Path(tmp) / "texto.txt"
        subprocess.run(
            [
                "ocrmypdf",
                "--force-ocr",
                "-l",
                "spa",
                "--output-type",
                "pdf",
                "--sidecar",
                str(lado),
                str(ruta),
                str(Path(tmp) / "salida.pdf"),
            ],
            check=True,
            capture_output=True,
            timeout=1800,
        )
        return lado.read_text(encoding="utf-8").split("\f")


def _leer_pdf(ruta: Path) -> list[str]:
    cache = ruta.with_suffix(".ocr.txt")
    if cache.exists() and cache.stat().st_mtime >= ruta.stat().st_mtime:
        return cache.read_text(encoding="utf-8").split("\f")
    paginas = _texto_pdf(ruta)
    total = sum(len(p.strip()) for p in paginas)
    if total < _MIN_CARACTERES_POR_PAGINA * max(len(paginas), 1):
        logger.info("%s es escaneado: se aplica OCR", ruta.name)
        paginas = _ocr(ruta)
        cache.write_text("\f".join(paginas), encoding="utf-8")
    return paginas


def leer_fuentes(carpeta: Path) -> list[Fuente]:
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta de insumos: {carpeta}")
    fuentes: list[Fuente] = []
    for ruta in sorted(carpeta.iterdir()):
        if ruta.suffix.lower() not in _SUFIJOS or ruta.name.endswith(".ocr.txt"):
            continue
        if ruta.suffix.lower() == ".pdf":
            paginas = _leer_pdf(ruta)
        else:
            paginas = [ruta.read_text(encoding="utf-8")]
        fuentes.append(Fuente(ruta.name, tuple(paginas)))
    if not fuentes:
        raise FileNotFoundError(f"La carpeta de insumos está vacía: {carpeta}")
    return fuentes


def texto_fuentes(carpeta: Path | None = None) -> str:
    fuentes = leer_fuentes(carpeta or config.insumos_dir)
    return "\n\n".join(f.render() for f in fuentes)


_cache: dict[Path, str] = {}


async def cargar(carpeta: Path | None = None) -> str:
    """Texto de las fuentes, leído una sola vez por carpeta."""
    ruta = carpeta or config.insumos_dir
    if ruta not in _cache:
        _cache[ruta] = await asyncio.to_thread(texto_fuentes, ruta)
    return _cache[ruta]


def olvidar() -> None:
    _cache.clear()
