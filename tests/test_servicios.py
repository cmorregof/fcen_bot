from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import app
from app.schemas.telegram import Chat, Message, Update, User
from app.servicios import actas, admision, calidad, despachar_update
from tests.conftest import TelegramFalso

USUARIO_ID = 999


def _mensaje_update(texto: str = "/start", update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id * 10,
            chat=Chat(id=USUARIO_ID, type="private"),
            from_=User(id=USUARIO_ID, first_name="Usuario", last_name="Prueba"),
            text=texto,
        ),
    )


async def test_admision_start_responde_en_construccion(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
) -> None:
    update = _mensaje_update("/start", update_id=101)
    await admision.manejar_update(db, update)

    assert tg.textos() == ["Servicio en construcción"]
    assert tg.mensajes[0]["chat_id"] == USUARIO_ID


async def test_calidad_start_responde_en_construccion(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
) -> None:
    update = _mensaje_update("/start", update_id=102)
    await calidad.manejar_update(db, update)

    assert tg.textos() == ["Servicio en construcción"]
    assert tg.mensajes[0]["chat_id"] == USUARIO_ID


async def test_admision_otro_mensaje_no_responde(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
) -> None:
    update = _mensaje_update("hola bot", update_id=103)
    await admision.manejar_update(db, update)

    assert tg.textos() == []


async def test_calidad_otro_mensaje_no_responde(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
) -> None:
    update = _mensaje_update("hola bot", update_id=104)
    await calidad.manejar_update(db, update)

    assert tg.textos() == []


async def test_despachar_update_admision(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "bot_servicio", "admision")
    update = _mensaje_update("/start", update_id=105)
    await despachar_update(db, update)

    assert tg.textos() == ["Servicio en construcción"]


async def test_despachar_update_calidad(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "bot_servicio", "calidad")
    update = _mensaje_update("/start", update_id=106)
    await despachar_update(db, update)

    assert tg.textos() == ["Servicio en construcción"]


async def test_despachar_update_actas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas: list[int] = []

    async def _falso_manejar(db: aiosqlite.Connection, update: Update) -> None:
        llamadas.append(update.update_id)

    monkeypatch.setattr(actas, "manejar_update", _falso_manejar)
    monkeypatch.setattr(settings, "bot_servicio", "actas")

    update = _mensaje_update("/start", update_id=107)
    await despachar_update(None, update)  # type: ignore[arg-type]

    assert llamadas == [107]


def test_rutas_almacenamiento_por_defecto_por_servicio() -> None:
    s_actas = Settings(bot_servicio="actas")
    assert s_actas.db_path == Path("data/actas/fcen.db")
    assert s_actas.media_dir == Path("data/actas/media")
    assert s_actas.output_dir == Path("data/actas/out")

    s_admision = Settings(bot_servicio="admision")
    assert s_admision.db_path == Path("data/admision/fcen.db")
    assert s_admision.media_dir == Path("data/admision/media")
    assert s_admision.output_dir == Path("data/admision/out")

    s_calidad = Settings(bot_servicio="calidad")
    assert s_calidad.db_path == Path("data/calidad/fcen.db")
    assert s_calidad.media_dir == Path("data/calidad/media")
    assert s_calidad.output_dir == Path("data/calidad/out")


def test_webhook_con_secreto_despacha_en_fondo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telegram_webhook_secret", "secreto-prueba")
    monkeypatch.setattr(settings, "bot_servicio", "admision")

    llamadas: list[Any] = []

    async def _falso_manejar(db: aiosqlite.Connection, update: Update) -> None:
        llamadas.append((settings.bot_servicio, update.update_id))

    monkeypatch.setattr(admision, "manejar_update", _falso_manejar)

    with TestClient(app) as client:
        r = client.post(
            "/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secreto-prueba"},
            json={"update_id": 999},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    assert llamadas == [("admision", 999)]
