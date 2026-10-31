"""Copia nocturna de la base del servicio en Drive.

Cada servicio (actas, calidad, admision) respalda solo su propia base en
`<DRIVE_CARPETA_ID>/Respaldos/<servicio>/` y conserva las últimas
DRIVE_RESPALDOS_CONSERVAR copias. Las más viejas van a la papelera de Drive, y
solo las de esa carpeta con el patrón de nombre del servicio.

El volcado está detrás de `Volcador`, según el motor de la base:

- SQLite: API de respaldo de sqlite3 (copia consistente aunque el servicio
  esté escribiendo), comprimida con gzip → `memoria_<servicio>_<AAAAMMDD>.db.gz`.
- Postgres (DATABASE_URL): `pg_dump --schema=<DB_SCHEMA>` en formato custom,
  que ya viene comprimido → `memoria_<servicio>_<AAAAMMDD>.dump`. Se restaura
  con `pg_restore` (docs/respaldo-drive.md).
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlsplit, urlunsplit

from app.core.config import settings
from app.services.drive import cliente as drive

logger = logging.getLogger(__name__)

CARPETA = "Respaldos"
MIME_GZIP = "application/gzip"
MIME_DUMP = "application/octet-stream"
# Cliente de Postgres que instala el Dockerfile (vuelca servidores 16 y 17).
PG_DUMP = "pg_dump"


class VolcadoNoDisponible(RuntimeError):
    """No hay cómo volcar esta base aquí (por ejemplo, falta pg_dump)."""


class ErrorVolcado(RuntimeError):
    """El volcado se intentó y falló."""


class Volcador(Protocol):
    """Saca una copia consistente de la base a un archivo local."""

    @property
    def extension(self) -> str:
        """ "db" para SQLite, "dump" para un volcado de Postgres."""
        ...

    @property
    def ya_comprimido(self) -> bool:
        """True si el volcado ya sale comprimido (no se pasa por gzip)."""
        ...

    def volcar(self, destino: Path) -> None: ...


@dataclass(frozen=True)
class VolcadorSqlite:
    origen: Path
    extension: str = "db"
    ya_comprimido: bool = False

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


def separar_clave(url: str) -> tuple[str, str]:
    """La URL sin la clave y la clave aparte (va por PGPASSWORD, no en la línea
    de comandos, donde la vería cualquier proceso)."""
    partes = urlsplit(url)
    if partes.password is None:
        return url, ""
    usuario = f"{partes.username}@" if partes.username else ""
    host = partes.hostname or ""
    if ":" in host:  # IPv6
        host = f"[{host}]"
    puerto = f":{partes.port}" if partes.port else ""
    sin_clave = urlunsplit(partes._replace(netloc=f"{usuario}{host}{puerto}"))
    return sin_clave, unquote(partes.password)


@dataclass(frozen=True)
class VolcadorPostgres:
    url: str
    esquema: str
    extension: str = "dump"
    ya_comprimido: bool = True
    binario: str = PG_DUMP
    timeout: float = 900.0

    def volcar(self, destino: Path) -> None:
        ejecutable = shutil.which(self.binario)
        if ejecutable is None:
            raise VolcadoNoDisponible(
                f"no está {self.binario} en el contenedor; la base está en "
                "Postgres y no se respalda en Drive (Railway Pro sí la respalda)."
            )
        url, clave = separar_clave(self.url)
        entorno = dict(os.environ)
        if clave:
            entorno["PGPASSWORD"] = clave
        try:
            resultado = self._correr(ejecutable, destino, url, entorno)
        except subprocess.TimeoutExpired as exc:
            raise ErrorVolcado(f"pg_dump tardó más de {self.timeout:.0f} s") from exc
        if resultado.returncode != 0:
            # El detalle va al log; pg_dump no imprime la clave.
            logger.error("pg_dump falló: %s", resultado.stderr.strip())
            raise ErrorVolcado(f"pg_dump terminó con código {resultado.returncode}")

    def _correr(
        self, ejecutable: str, destino: Path, url: str, entorno: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                ejecutable,
                "--format=custom",
                "--compress=6",
                f"--schema={self.esquema}",
                "--no-owner",
                "--no-privileges",
                f"--file={destino}",
                f"--dbname={url}",
            ],
            env=entorno,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )


def volcador_actual() -> Volcador:
    """El volcador de la base que usa este servicio. Con Postgres nunca se
    copia la SQLite que haya quedado en el volumen: esa ya no es la base."""
    if settings.database_url:
        return VolcadorPostgres(settings.database_url, settings.db_schema)
    return VolcadorSqlite(settings.db_path)


def nombre(
    servicio: str, dia: date, extension: str, *, ya_comprimido: bool = False
) -> str:
    base = f"memoria_{servicio}_{dia:%Y%m%d}.{extension}"
    return base if ya_comprimido else f"{base}.gz"


def _patron(servicio: str) -> re.Pattern[str]:
    # .db.gz (SQLite) y .dump (Postgres) cuentan juntas para la retención.
    return re.compile(rf"^memoria_{re.escape(servicio)}_\d{{8}}\.([a-z]+\.gz|dump)$")


def comprimido(volcador: Volcador) -> bytes:
    """Vuelca y comprime en una carpeta temporal que se borra al terminar."""
    with tempfile.TemporaryDirectory() as tmp:
        crudo = Path(tmp) / f"copia.{volcador.extension}"
        volcador.volcar(crudo)
        if volcador.ya_comprimido:
            return crudo.read_bytes()
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

    try:
        datos = await asyncio.to_thread(comprimido, volcador)
    except VolcadoNoDisponible as exc:
        logger.warning("Respaldo en Drive apagado: %s", exc)
        return {"activo": False, "motivo": str(exc)}
    archivo = nombre(
        servicio, hoy, volcador.extension, ya_comprimido=volcador.ya_comprimido
    )
    mime = MIME_DUMP if volcador.ya_comprimido else MIME_GZIP
    destino = await drive.carpeta(
        cliente, settings.drive_carpeta_id, [CARPETA, servicio]
    )
    existentes = await cliente.listar(destino)
    mismo = next((a for a in existentes if a.nombre == archivo), None)
    if mismo:  # se corrió dos veces el mismo día: se reemplaza
        await cliente.reemplazar(mismo.id, datos, mime)
    else:
        await cliente.subir(archivo, destino, datos, mime)

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
