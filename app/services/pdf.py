"""Conversión .docx -> PDF con LibreOffice en modo headless."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


async def docx_a_pdf(docx: bytes) -> bytes | None:
    """Devuelve el PDF, o None si LibreOffice no está disponible o falla."""
    if shutil.which(settings.soffice_bin) is None:
        logger.warning("LibreOffice (%s) no está instalado.", settings.soffice_bin)
        return None
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        entrada = base / "oficio.docx"
        entrada.write_bytes(docx)
        perfil = base / "perfil"
        proceso = await asyncio.create_subprocess_exec(
            settings.soffice_bin,
            f"-env:UserInstallation=file://{perfil}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(base),
            str(entrada),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(
                proceso.communicate(), timeout=settings.pdf_timeout_seconds
            )
        except TimeoutError:
            proceso.kill()
            logger.warning("LibreOffice tardó demasiado.")
            return None
        salida = base / "oficio.pdf"
        if not salida.exists():
            logger.warning("LibreOffice no produjo el PDF.")
            return None
        return salida.read_bytes()
