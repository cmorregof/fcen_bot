from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import practica
from app.api.routes import router
from app.api.web import crear_router
from app.api.web.config import web_settings
from app.core.config import settings
from app.db import repo
from app.db.session import connect

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db = await connect()
    # Entorno de práctica: se siembra si la siembra anterior no terminó.
    primera_vez = settings.memoria_practica and not await practica.sembrado(
        db
    )  # crea las tablas si no existen
    await repo.reabrir_interrumpidos(db)
    await db.close()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    if primera_vez:
        await practica.reiniciar()
    precarga = None
    if settings.bot_servicio == "admision":
        from app.servicios.admision import fuentes

        precarga = asyncio.create_task(fuentes.precargar())
    yield
    if precarga is not None and not precarga.done():
        precarga.cancel()


app = FastAPI(title="fcen_bot", lifespan=lifespan)
app.include_router(router)
app.include_router(crear_router(settings.bot_servicio))
app.add_middleware(
    CORSMiddleware,
    allow_origins=web_settings.lista_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
