from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from PIL import Image, ImageDraw

from app.schemas.telegram import (
    CallbackQuery,
    Chat,
    Document,
    Message,
    PhotoSize,
    Update,
    User,
)
from app.servicios import admision
from app.servicios.admision import fuentes
from app.servicios.admision.archivo import Archivo
from app.servicios.admision.chequeo import Documento
from app.servicios.admision.config import config
from app.servicios.admision.modelo import RespuestaPregunta, RevisionDocumento

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "admision"
CHAT = 4242
ADMIN = 7


class ModeloFalso:
    def __init__(self) -> None:
        self.preguntas: list[str] = []
        self.revisiones: list[tuple[str, int]] = []
        self.fuentes_vistas: list[str] = []
        self.respuesta: RespuestaPregunta | None = RespuestaPregunta(
            cubierta=True,
            respuesta="Debes enviar el documento por ambas caras.",
            citas=["LISTADO_FICTICIO.md, página 1"],
        )
        self.revision: RevisionDocumento | None = RevisionDocumento(items=[])

    async def responder(self, fuentes: str, pregunta: str) -> RespuestaPregunta | None:
        self.fuentes_vistas.append(fuentes)
        self.preguntas.append(pregunta)
        return self.respuesta

    async def revisar(
        self, fuentes: str, documento: Documento, archivo: Archivo
    ) -> RevisionDocumento | None:
        self.revisiones.append((documento.clave, len(archivo.datos)))
        return self.revision


@pytest.fixture(autouse=True)
def entorno(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(config, "insumos_dir", FIXTURES)
    monkeypatch.setattr(config, "admin_ids", str(ADMIN))
    monkeypatch.setattr(config, "contacto", "María Ficticia (maria@ejemplo.test)")
    fuentes.olvidar()
    yield
    fuentes.olvidar()
    admision.usar_modelo(None)
    admision._PENDIENTES.clear()


@pytest.fixture
def modelo() -> ModeloFalso:
    falso = ModeloFalso()
    admision.usar_modelo(falso)
    return falso


def imagen_legible() -> bytes:
    img = Image.new("RGB", (900, 700), "white")
    d = ImageDraw.Draw(img)
    for y in range(40, 660, 40):
        d.rectangle((60, y, 840, y + 14), fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Chatbot:
    """Envía updates al servicio como si fueran de Telegram."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self.db = db
        self._n = 0

    def _id(self) -> int:
        self._n += 1
        return self._n

    def _mensaje(self, uid: int = CHAT, **kw: Any) -> Message:
        n = self._id()
        return Message(
            message_id=n, chat=Chat(id=uid), from_=User(id=uid, first_name="X"), **kw
        )

    async def texto(self, texto: str, uid: int = CHAT) -> None:
        await admision.manejar_update(
            self.db,
            Update(update_id=self._id(), message=self._mensaje(uid, text=texto)),
        )

    async def boton(self, data: str, uid: int = CHAT) -> None:
        cb = CallbackQuery(
            id="cb",
            **{"from": User(id=uid)},
            message=self._mensaje(uid),
            data=data,
        )
        await admision.manejar_update(
            self.db, Update(update_id=self._id(), callback_query=cb)
        )

    async def foto(self, caption: str | None = None) -> None:
        msg = self._mensaje(
            photo=[PhotoSize(file_id="F1", file_unique_id="u1", file_size=5000)],
            caption=caption,
        )
        await admision.manejar_update(
            self.db, Update(update_id=self._id(), message=msg)
        )

    async def documento(self, caption: str | None = None, tamano: int = 5000) -> None:
        msg = self._mensaje(
            document=Document(file_id="D1", file_unique_id="u2", file_size=tamano),
            caption=caption,
        )
        await admision.manejar_update(
            self.db, Update(update_id=self._id(), message=msg)
        )

    async def registrar_adulto(self) -> None:
        await self.texto("/start")
        await self.boton("adm:acepto")
        await self.boton("adm:menor:0")


@pytest.fixture
def bot(db: aiosqlite.Connection) -> Chatbot:
    return Chatbot(db)
