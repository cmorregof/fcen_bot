from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import aiosqlite
import pytest
from openpyxl import Workbook

from app.integrations import telegram
from app.schemas.telegram import Chat, Document, Message, Update, User
from app.servicios import calidad
from app.servicios.calidad import reloj
from app.servicios.calidad.config import calidad_settings
from tests.conftest import TelegramFalso

HOY = date(2026, 10, 28)
USUARIO = 777
ENCABEZADO = [
    "programa", "código", "tarea", "responsable_cargo", "responsable_dependencia",
    "fecha_límite", "evidencia_esperada",
]  # fmt: skip


def fila(
    programa: str = "Programa Uno",
    codigo: str = "UNO-01",
    limite: date | str = date(2026, 11, 10),
    **cambios: str,
) -> list[object]:
    valores: dict[str, object] = {
        "programa": programa,
        "código": codigo,
        "tarea": "Tarea de prueba " + codigo,
        "responsable_cargo": "Cargo de prueba",
        "responsable_dependencia": "Dependencia de prueba",
        "fecha_límite": limite,
        "evidencia_esperada": "Informe",
    }
    valores.update(cambios)
    return [valores[c] for c in ENCABEZADO]


def xlsx(filas: list[list[object]], encabezado: list[str] | None = None) -> bytes:
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.append(encabezado or ENCABEZADO)
    for f in filas:
        hoja.append(f)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


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
