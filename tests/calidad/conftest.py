from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo

import aiosqlite
import pytest
from openpyxl import Workbook, load_workbook

from app.integrations import telegram
from app.schemas.telegram import Chat, Document, Message, Update, User
from app.servicios import calidad
from app.servicios.calidad import reloj
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.plantilla import Plan, leer_plantilla
from tests.conftest import TelegramFalso

HOY = date(2026, 10, 28)
USUARIO = 777
DOCS = Path(__file__).resolve().parents[2] / "docs" / "calidad"
ALFA = DOCS / "plantilla_plan_mejoramiento.xlsx"
BETA = DOCS / "plantilla_plan_mejoramiento_beta.xlsx"


def plantilla(
    ruta: Path = ALFA, cambios: Callable[[Workbook], None] | None = None
) -> bytes:
    """Una de las plantillas ficticias de docs/calidad, con cambios opcionales."""
    if cambios is None:
        return ruta.read_bytes()
    libro = load_workbook(io.BytesIO(ruta.read_bytes()))
    cambios(libro)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def leer(ruta: Path = ALFA) -> Plan:
    lectura = leer_plantilla(plantilla(ruta))
    assert lectura.plan is not None, lectura.errores
    return lectura.plan


@pytest.fixture(autouse=True)
def calidad_fijo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calidad_settings, "invite_code", "CODIGO-PRUEBA")
    monkeypatch.setattr(calidad_settings, "alertas_activas", False)
    monkeypatch.setattr(
        reloj,
        "ahora",
        lambda: datetime(2026, 10, 28, 9, 0, tzinfo=ZoneInfo("America/Bogota")),
    )


class Chat_:
    """Envía updates al servicio como si los mandara una persona."""

    def __init__(self, db: aiosqlite.Connection, tg: TelegramFalso, uid: int = USUARIO):
        self.db, self.tg, self.uid, self._n = db, tg, uid, 0

    def _update(self, **campos: object) -> Update:
        self._n += 1
        return Update(
            update_id=self.uid * 1000 + self._n,
            message=Message(
                message_id=self._n,
                chat=Chat(id=self.uid),
                from_=User(id=self.uid, first_name="Persona", last_name="Ficticia"),
                **campos,  # type: ignore[arg-type]
            ),
        )

    async def texto(self, texto: str) -> str:
        antes = len(self.tg.mensajes)
        await calidad.manejar_update(self.db, self._update(text=texto))
        return "\n".join(m["texto"] for m in self.tg.mensajes[antes:])

    async def documento(self, nombre: str, caption: str | None = None) -> str:
        antes = len(self.tg.mensajes)
        doc = Document(file_id="F1", file_unique_id="U1", file_name=nombre)
        await calidad.manejar_update(
            self.db, self._update(document=doc, caption=caption)
        )
        return "\n".join(m["texto"] for m in self.tg.mensajes[antes:])

    async def boton(self, data: str) -> str:
        from app.schemas.telegram import CallbackQuery

        antes = len(self.tg.mensajes)
        self._n += 1
        cb = CallbackQuery(
            id="cb",
            from_=User(id=self.uid, first_name="Persona"),
            message=Message(message_id=1, chat=Chat(id=self.uid)),
            data=data,
        )
        await calidad.manejar_update(
            self.db, Update(update_id=self.uid * 1000 + self._n, callback_query=cb)
        )
        return "\n".join(m["texto"] for m in self.tg.mensajes[antes:])


@pytest.fixture
async def chat(db: aiosqlite.Connection, tg: TelegramFalso) -> Chat_:
    c = Chat_(db, tg)
    await c.texto("/start CODIGO-PRUEBA")
    return c


@pytest.fixture
def servir_excel(monkeypatch: pytest.MonkeyPatch) -> Callable[[bytes], None]:
    def _servir(contenido: bytes) -> None:
        async def _descargar(file_id: str, **kw: object) -> bytes:
            return contenido

        monkeypatch.setattr(telegram, "descargar_archivo", _descargar)

    return _servir
