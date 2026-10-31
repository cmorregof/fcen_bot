from __future__ import annotations

import io
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from PIL import Image

from app.core import conexion
from app.core.config import settings
from app.db import session
from app.db.session import connect
from app.integrations import telegram
from app.schemas.caso import (
    AsignaturaSolicitada,
    DatosSIA,
    ExtraccionCaso,
    FilaCreditos,
    TipoSolicitud,
)


def filas_sia() -> list[FilaCreditos]:
    """Cifras agregadas con la estructura real de la tabla del SIA."""
    datos = [
        ("DISCIPLINAR OPTATIVA", 12, 0, 12, 3, 0),
        ("FUND. OBLIGATORIA", 66, 63, 3, 4, 63),
        ("FUND. OPTATIVA", 12, 8, 4, 0, 8),
        ("DISCIPLINAR OBLIGATORIA", 40, 17, 23, 6, 17),
        ("LIBRE ELECCIÓN", 34, 8, 26, 0, 8),
        ("TRABAJO DE GRADO", 6, 0, 6, 0, 0),
        ("TOTAL", 170, 96, 74, 13, 96),
        ("NIVELACIÓN", 12, 12, 0, 0, 12),
        ("TOTAL ESTUDIANTE", 182, 108, 74, 13, 108),
    ]
    return [
        FilaCreditos(
            tipologia=t, exigidos=a, aprobados=b, pendientes=c, inscritos=d, cursados=e
        )
        for t, a, b, c, d, e in datos
    ]


def extraccion_ejemplo(**cambios: Any) -> ExtraccionCaso:
    base = ExtraccionCaso(
        nombre_estudiante="Persona Ficticia Uno",
        documento="1000000001",
        tratamiento="La estudiante",
        fecha_solicitud="2026-09-02",
        tipos=[TipoSolicitud.CARGA_MINIMA, TipoSolicitud.CANCELACION],
        objeto_solicitud="cancelación de la asignatura 4100849 Termodinámica y carga mínima",
        asignaturas=[
            AsignaturaSolicitada(
                codigo="4100849", nombre="Termodinámica", creditos=4, accion="cancelar"
            )
        ],
        cuerpo_desde_linea=2,
        cuerpo_hasta_linea=3,
        sia=DatosSIA(
            plan_codigo="4030",
            plan_nombre="INGENIERIA FISICA",
            periodo="2026-2S",
            papa=4.5,
            porcentaje_avance=56.5,
            resumen_creditos=filas_sia(),
        ),
    )
    return base.model_copy(update=cambios)


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


# Con TEST_DATABASE_URL (postgresql://…) toda la suite corre contra Postgres:
# cada prueba en un esquema propio que se borra al terminar. Las pruebas que
# abren el archivo SQLite directamente llevan @pytest.mark.solo_sqlite.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if not TEST_DATABASE_URL:
        return
    saltar = pytest.mark.skip(reason="abre el archivo SQLite directamente")
    for item in items:
        if "solo_sqlite" in item.keywords:
            item.add_marker(saltar)


@pytest.fixture(autouse=True)
def aislar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _rutas(tmp_path, monkeypatch)
    if TEST_DATABASE_URL:
        yield from _esquema_postgres(monkeypatch)
    else:
        monkeypatch.setattr(settings, "database_url", "")
        yield


def _esquema_postgres(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import psycopg

    esquema = f"prueba_{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "database_url", TEST_DATABASE_URL)
    monkeypatch.setattr(settings, "db_schema", esquema)
    session.olvidar_iniciadas()
    try:
        yield
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE')
        conexion.olvidar_cache(TEST_DATABASE_URL, esquema)


def _rutas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "media_dir", tmp_path / "media")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "out")
    monkeypatch.setattr(settings, "soffice_bin", "no-existe-soffice")
    monkeypatch.setattr(settings, "telegram_bot_token", "TEST")
    # El mínimo de jurados sale de config/solicitudes.yaml, no del .env local.
    monkeypatch.setattr(settings, "jurados_minimo", None)


@asynccontextmanager
async def abrir_base() -> AsyncIterator[conexion.Conexion]:
    """La base del servicio (SQLite o Postgres), como en producción."""
    db = await connect()
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    conexion = await connect()
    yield conexion
    await conexion.close()


class TelegramFalso:
    def __init__(self) -> None:
        self.mensajes: list[dict[str, Any]] = []
        self.documentos: list[dict[str, Any]] = []
        self.callbacks: list[str | None] = []
        self._id = 1000

    async def send_message(self, chat_id: int, texto: str, **kw: Any) -> int:
        self._id += 1
        self.mensajes.append({"chat_id": chat_id, "texto": texto, "id": self._id, **kw})
        return self._id

    async def send_document(self, chat_id: int, **kw: Any) -> None:
        self.documentos.append({"chat_id": chat_id, **kw})

    async def responder_callback(
        self, callback_id: str, texto: str | None = None
    ) -> None:
        self.callbacks.append(texto)

    async def editar_botones(self, *a: Any, **kw: Any) -> None:
        return None

    async def descargar_archivo(self, file_id: str, **kw: Any) -> bytes:
        return png_bytes()

    def textos(self) -> list[str]:
        return [m["texto"] for m in self.mensajes]


@pytest.fixture
def tg(monkeypatch: pytest.MonkeyPatch) -> TelegramFalso:
    falso = TelegramFalso()
    for nombre in (
        "send_message",
        "send_document",
        "responder_callback",
        "editar_botones",
        "descargar_archivo",
    ):
        monkeypatch.setattr(telegram, nombre, getattr(falso, nombre))
    return falso
