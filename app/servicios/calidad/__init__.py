"""Servicio de calidad (plan de mejoramiento y acreditación)."""

from __future__ import annotations

import aiosqlite

from app.db import repo
from app.integrations import telegram
from app.schemas.telegram import Update

MENSAJE_EN_CONSTRUCCION = "Servicio en construcción"


async def manejar_update(db: aiosqlite.Connection, update: Update) -> None:
    if not await repo.marcar_update(db, update.update_id):
        return
    msg = update.message
    if msg is None:
        return
    texto = (msg.text or "").strip()
    if texto.startswith("/start"):
        await telegram.send_message(msg.chat.id, MENSAJE_EN_CONSTRUCCION)


__all__ = ["MENSAJE_EN_CONSTRUCCION", "manejar_update"]
