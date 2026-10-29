"""Servicios de Telegram del proyecto MemorIA."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import aiosqlite

from app.core.config import settings
from app.schemas.telegram import Update
from app.servicios import actas, admision, calidad

TipoManejador = Callable[[aiosqlite.Connection, Update], Awaitable[None]]


def obtener_manejador(servicio: str) -> TipoManejador:
    if servicio == "actas":
        return actas.manejar_update
    if servicio == "admision":
        return admision.manejar_update
    if servicio == "calidad":
        return calidad.manejar_update
    raise ValueError(f"Servicio no soportado: {servicio}")


async def despachar_update(db: aiosqlite.Connection, update: Update) -> None:
    manejador = obtener_manejador(settings.bot_servicio)
    await manejador(db, update)


__all__ = [
    "TipoManejador",
    "actas",
    "admision",
    "calidad",
    "despachar_update",
    "obtener_manejador",
]
