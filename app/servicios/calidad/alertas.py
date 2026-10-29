"""Alerta quincenal: se calcula siempre, se envía solo con ALERTAS_ACTIVAS=true."""

from __future__ import annotations

from datetime import date

import aiosqlite

from app.integrations import telegram
from app.servicios.calidad import plan, textos
from app.servicios.calidad.config import calidad_settings


async def construir_alertas(db: aiosqlite.Connection, hoy: date) -> dict[str, str]:
    tareas = await plan.listar_tareas(db)
    return {
        programa: textos.texto_alerta(
            programa, [t for t in tareas if t.programa == programa], hoy
        )
        for programa in sorted({t.programa for t in tareas})
    }


async def enviar_alertas(db: aiosqlite.Connection, hoy: date) -> dict[str, object]:
    if not calidad_settings.alertas_activas:
        return {"activas": False, "enviados": 0}
    alertas = await construir_alertas(db, hoy)
    cur = await db.execute("SELECT telegram_id FROM cal_usuarios")
    destinos = [int(r[0]) for r in await cur.fetchall()]
    enviados = 0
    for chat_id in destinos:
        for texto in alertas.values():
            await telegram.send_message(chat_id, texto)
            enviados += 1
    return {"activas": True, "enviados": enviados}
