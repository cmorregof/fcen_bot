"""Copia nocturna de la base del servicio en Drive.

Cada servicio (actas, calidad, admision) respalda solo su propia base en
`<DRIVE_CARPETA_ID>/Respaldos/<servicio>/memoria_<servicio>_<AAAAMMDD>.<ext>.gz`
y conserva las últimas DRIVE_RESPALDOS_CONSERVAR copias. Las más viejas van a
la papelera de Drive, y solo las de esa carpeta con ese patrón de nombre.

El volcado está detrás de `Volcador`: hoy SQLite (API de respaldo de
sqlite3, copia consistente aunque el servicio esté escribiendo); para Postgres
basta otro volcador con `pg_dump` y extensión `sql`.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from app.core.config import settings
from app.services.drive import cliente as drive

logger = logging.getLogger(__name__)

CARPETA = "Respaldos"
MIME_GZIP = "application/gzip"


class Volcador(Protocol):
    """Saca una copia consistente de la base a un archivo local."""

    @property
    def extension(self) -> str:
        """ "db" para SQLite, "sql" para un volcado de Postgres."""
        ...

    def volcar(self, destino: Path) -> None: ...


@dataclass(frozen=True)
class VolcadorSqlite:
    origen: Path
    extension: str = "db"

    def volcar(self, destino: Path) -> None:
        if not self.origen.exists():
            raise FileNotFoundError(f"No existe la base {self.origen}.")
        fuente = sqlite3.connect(f"file:{self.origen}?mode=ro", uri=True)
        copia = sqlite3.connect(destino)
        try:
            with copia:
                fuente.backup(copia)
        finally:
            copia.close()
            fuente.close()


def volcador_actual() -> Volcador:
    """El volcador de la base que usa este servicio."""
    return VolcadorSqlite(settings.db_path)


def nombre(servicio: str, dia: date, extension: str) -> str:
    return f"memoria_{servicio}_{dia:%Y%m%d}.{extension}.gz"


def _patron(servicio: str) -> re.Pattern[str]:
    return re.compile(rf"^memoria_{re.escape(servicio)}_\d{{8}}\.[a-z]+\.gz$")


def comprimido(volcador: Volcador) -> bytes:
    """Vuelca y comprime en una carpeta temporal que se borra al terminar."""
    with tempfile.TemporaryDirectory() as tmp:
        crudo = Path(tmp) / f"copia.{volcador.extension}"
        volcador.volcar(crudo)
        gz = Path(tmp) / "copia.gz"
        with crudo.open("rb") as f_in, gzip.open(gz, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        return gz.read_bytes()


async def respaldar(
    cliente: drive.ClienteDrive | None,
    hoy: date,
    *,
    volcador: Volcador | None = None,
    servicio: str | None = None,
    conservar: int | None = None,
) -> dict[str, object]:
    """Sube la copia de hoy y aplica la retención. Sin cliente, no hace nada."""
    if cliente is None:
        return {"activo": False}
    servicio = servicio or settings.bot_servicio
    volcador = volcador or volcador_actual()
    conservar = max(1, conservar or settings.drive_respaldos_conservar)

    datos = await asyncio.to_thread(comprimido, volcador)
    archivo = nombre(servicio, hoy, volcador.extension)
    destino = await drive.carpeta(
        cliente, settings.drive_carpeta_id, [CARPETA, servicio]
    )
    existentes = await cliente.listar(destino)
    mismo = next((a for a in existentes if a.nombre == archivo), None)
    if mismo:  # se corrió dos veces el mismo día: se reemplaza
        await cliente.reemplazar(mismo.id, datos, MIME_GZIP)
    else:
        await cliente.subir(archivo, destino, datos, MIME_GZIP)

    # El nombre lleva la fecha AAAAMMDD: el orden alfabético es el cronológico.
    patron = _patron(servicio)
    previas = [
        a
        for a in existentes
        if patron.match(a.nombre) and a.id != (mismo.id if mismo else "")
    ]
    quedan = set(
        sorted({a.nombre for a in previas} | {archivo}, reverse=True)[:conservar]
    )
    sobran = [a for a in previas if a.nombre not in quedan]
    for a in sobran:
        await cliente.a_papelera(a.id)
    logger.info(
        "Respaldo %s subido (%d bytes); %d copias viejas a la papelera",
        archivo,
        len(datos),
        len(sobran),
    )
    return {
        "activo": True,
        "archivo": archivo,
        "bytes": len(datos),
        "eliminadas": len(sobran),
    }
