"""API de la web de MemorIA.

Cada backend monta solo las rutas de su servicio (BOT_SERVICIO): el backend de
calidad no tiene rutas de actas ni de admisión, y viceversa.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.web import comun


def crear_router(servicio: str) -> APIRouter:
    router = APIRouter(prefix="/api/web")
    router.include_router(comun.router)
    if servicio == "calidad":
        from app.api.web import calidad

        router.include_router(calidad.router)
    elif servicio == "admision":
        from app.api.web import admision

        router.include_router(admision.router)
    elif servicio == "actas":
        from app.api.web import actas

        router.include_router(actas.router)
    return router


__all__ = ["crear_router"]
