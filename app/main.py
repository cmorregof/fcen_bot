from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings
from app.db import repo
from app.db.session import connect

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db = await connect()  # crea las tablas si no existen
    await repo.reabrir_interrumpidos(db)
    await db.close()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="fcen_bot", lifespan=lifespan)
app.include_router(router)
