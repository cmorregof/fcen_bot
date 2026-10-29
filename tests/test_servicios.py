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


async def test_calidad_start_responde_en_construccion(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
) -> None:
    update = _mensaje_update("/start", update_id=102)
    await calidad.manejar_update(db, update)

    assert tg.textos() == ["Servicio en construcción"]
    assert tg.mensajes[0]["chat_id"] == USUARIO_ID


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

    assert "PENDIENTE DE AVAL" in tg.textos()[0]


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


@pytest.fixture
def sin_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Que el .env y las variables de quien corre las pruebas no influyan."""
    for var in ("BOT_SERVICIO", "DATA_DIR", "DB_PATH", "MEDIA_DIR", "OUTPUT_DIR"):
        monkeypatch.delenv(var, raising=False)


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@pytest.mark.usefixtures("sin_entorno")
def test_rutas_almacenamiento_por_defecto_por_servicio(tmp_path: Path) -> None:
    for servicio in ("actas", "admision", "calidad"):
        s = _settings(bot_servicio=servicio, data_dir=tmp_path)
        assert s.db_path == tmp_path / servicio / "fcen.db"
        assert s.media_dir == tmp_path / servicio / "media"
        assert s.output_dir == tmp_path / servicio / "out"


@pytest.mark.usefixtures("sin_entorno")
def test_data_dir_por_defecto_y_variables_vacias() -> None:
    s = _settings(bot_servicio="calidad", db_path="", media_dir="", output_dir="")
    assert s.db_path == Path("data/calidad/fcen.db")
    assert s.media_dir == Path("data/calidad/media")
    assert s.output_dir == Path("data/calidad/out")


@pytest.mark.usefixtures("sin_entorno")
def test_actas_conserva_la_base_de_un_despliegue_anterior(tmp_path: Path) -> None:
    # El Dockerfile de main guardaba la base en /data/fcen.db.
    (tmp_path / "fcen.db").write_bytes(b"")
    s = _settings(bot_servicio="actas", data_dir=tmp_path)
    assert s.db_path == tmp_path / "fcen.db"
    assert s.media_dir == tmp_path / "media"
    assert s.output_dir == tmp_path / "out"
    # Los demás servicios no la heredan.
    s_adm = _settings(bot_servicio="admision", data_dir=tmp_path)
    assert s_adm.db_path == tmp_path / "admision" / "fcen.db"


@pytest.mark.usefixtures("sin_entorno")
def test_ruta_explicita_se_respeta(tmp_path: Path) -> None:
    s = _settings(bot_servicio="actas", db_path=tmp_path / "otra.db")
    assert s.db_path == tmp_path / "otra.db"


@pytest.mark.usefixtures("sin_entorno")
@pytest.mark.parametrize(
    "ruta", ["data/fcen.db", "/data/fcen.db", "/data/actas/fcen.db"]
)
def test_otro_servicio_no_puede_usar_la_base_de_actas(ruta: str) -> None:
    with pytest.raises(ValueError, match="base de actas"):
        _settings(bot_servicio="admision", db_path=ruta)


@pytest.mark.parametrize("servicio", ["admision", "calidad"])
def test_cron_de_borradores_no_aplica_fuera_de_actas(
    servicio: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "internal_cron_secret", "cron-prueba")
    monkeypatch.setattr(settings, "bot_servicio", servicio)
    with TestClient(app) as client:
        r = client.post(
            "/internal/borrador-diario", headers={"X-Cron-Secret": "cron-prueba"}
        )
    assert r.status_code == 404


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
