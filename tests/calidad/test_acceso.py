from __future__ import annotations

import aiosqlite

from app.servicios.calidad import textos
from tests.calidad.conftest import Chat_
from tests.conftest import TelegramFalso


async def test_sin_codigo_no_entra(db: aiosqlite.Connection, tg: TelegramFalso) -> None:
    c = Chat_(db, tg, uid=1)
    assert "código de invitación" in await c.texto("/start")
    assert "código de invitación" in await c.texto("/start equivocado")
    assert "solo por invitación" in await c.texto("/plan algo")


async def test_con_codigo_entra_y_ve_el_alcance(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    c = Chat_(db, tg, uid=2)
    respuesta = await c.texto("/start CODIGO-PRUEBA")
    assert textos.ALCANCE in respuesta
    assert "No reemplazo el seguimiento de la DAMA" in respuesta
    assert "Aún no hay plan" in await c.texto("/plan")
