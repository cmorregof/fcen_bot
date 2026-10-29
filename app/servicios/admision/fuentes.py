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

# Los PDF escaneados suelen traer solo el encabezado como texto (~100 caracteres).
_MIN_CARACTERES_POR_PAGINA = 300
_SUFIJOS = {".pdf", ".txt", ".md"}

# Lo que la oficina de admisiones publica para 2027-1S. Se cargan todos los
# PDF, TXT y MD de la carpeta; estos nombres solo sirven para avisar si falta
# alguno.
INSUMOS_ESPERADOS = (
    "LISTADO_DE_DOCUMENTOS_ADMITIDOS_PREGRADO_2027_1S.pdf",
    "2.Lista-de-Chequeo-y-Verificacion-de-Documentos.pdf",
    "Formato-de-matricula-2027-1S-2.pdf",
    "Manual_Usuario_FORE_Admitidos_2027_1S.pdf",
)


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


def _cache_vigente(ruta: Path) -> Path | None:
    cache = ruta.with_suffix(".ocr.txt")
    # Si no hay ocrmypdf (p. ej. en Railway) la caché se acepta aunque el PDF
    # sea más reciente: subir ambos al volumen cambia las fechas.
    if cache.exists() and (
        cache.stat().st_mtime >= ruta.stat().st_mtime
        or shutil.which("ocrmypdf") is None
    ):
        return cache
    return None


def _es_escaneado(paginas: list[str]) -> bool:
    total = sum(len(p.strip()) for p in paginas)
    return total < _MIN_CARACTERES_POR_PAGINA * max(len(paginas), 1)


def _leer_pdf(ruta: Path) -> list[str]:
    cache = ruta.with_suffix(".ocr.txt")
    if _cache_vigente(ruta) is not None:
        return cache.read_text(encoding="utf-8").split("\f")
    paginas = _texto_pdf(ruta)
    if _es_escaneado(paginas):
        logger.info("%s es escaneado: se aplica OCR", ruta.name)
        paginas = _ocr(ruta)
        cache.write_text("\f".join(paginas), encoding="utf-8")
    return paginas


def leer_fuentes(carpeta: Path) -> list[Fuente]:
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta de insumos: {carpeta}")
    fuentes: list[Fuente] = []
    for ruta in sorted(carpeta.iterdir()):
        if not ruta.is_file() or not _es_insumo(ruta):
            continue
        if ruta.suffix.lower() == ".pdf":
            paginas = _leer_pdf(ruta)
        else:
            paginas = [ruta.read_text(encoding="utf-8")]
        fuentes.append(Fuente(ruta.name, tuple(paginas)))
    if not fuentes:
        raise FileNotFoundError(f"La carpeta de insumos está vacía: {carpeta}")
    return fuentes


def _es_insumo(ruta: Path) -> bool:
    return ruta.suffix.lower() in _SUFIJOS and not ruta.name.endswith(".ocr.txt")


@dataclass(frozen=True)
class Diagnostico:
    nombre: str
    bytes: int
    paginas: int
    caracteres: int
    # ok, ocr_en_cache, se_hara_ocr, falta_ocr o ilegible
    estado: str


def diagnosticar(carpeta: Path | None = None) -> list[Diagnostico]:
    """Qué hay en la carpeta de insumos y si se puede leer. Nunca hace OCR."""
    carpeta = carpeta or config.insumos_dir
    if not carpeta.is_dir():
        return []
    salida: list[Diagnostico] = []
    for ruta in sorted(carpeta.iterdir()):
        if not ruta.is_file() or not _es_insumo(ruta):
            continue
        peso = ruta.stat().st_size
        if ruta.suffix.lower() != ".pdf":
            texto = ruta.read_text(encoding="utf-8", errors="replace")
            salida.append(Diagnostico(ruta.name, peso, 1, len(texto.strip()), "ok"))
            continue
        cache = _cache_vigente(ruta)
        try:
            if cache is not None:
                paginas = cache.read_text(encoding="utf-8").split("\f")
                estado = "ocr_en_cache"
            else:
                paginas = _texto_pdf(ruta)
                estado = "ok"
                if _es_escaneado(paginas):
                    hay_ocr = shutil.which("ocrmypdf") is not None
                    estado = "se_hara_ocr" if hay_ocr else "falta_ocr"
        except Exception:  # PDF dañado o cifrado
            logger.warning("No se pudo leer el insumo %s", ruta.name)
            salida.append(Diagnostico(ruta.name, peso, 0, 0, "ilegible"))
            continue
        caracteres = sum(len(p.strip()) for p in paginas)
        salida.append(Diagnostico(ruta.name, peso, len(paginas), caracteres, estado))
    return salida


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


async def precargar() -> None:
    """Lee las fuentes al arrancar (y hace el OCR si hace falta).

    Así un insumo ilegible aparece en los logs del despliegue y no en la
    primera pregunta de un admitido.
    """
    try:
        texto = await cargar()
    except Exception as exc:
        logger.warning("Insumos de admisión no disponibles: %s", exc)
        return
    nombres = [d.nombre for d in await asyncio.to_thread(diagnosticar)]
    logger.info(
        "Insumos de admisión listos: %s (%d caracteres)", ", ".join(nombres), len(texto)
    )
    faltan = [n for n in INSUMOS_ESPERADOS if n not in nombres]
    if faltan:
        logger.warning("Faltan insumos de admisión: %s", ", ".join(faltan))


def olvidar() -> None:
    _cache.clear()
