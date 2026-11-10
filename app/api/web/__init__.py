"""API de la web de MemorIA.

Cada backend monta solo las rutas de su servicio (BOT_SERVICIO): el backend de
calidad no tiene rutas de actas ni de admisión, y viceversa.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.web import comun


class SinCache:
    """Marca `Cache-Control: no-store` en las respuestas de /api/web.

    La web llega a estos backends por el proxy de Vercel (rewrites de
    web/next.config.ts): con esto ni Vercel ni el navegador guardan copia de
    los datos, aunque falle la configuración del proxy. Es ASGI puro para no
    tocar el cuerpo de la petición (la subida de soportes llega en flujo)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/web"):
            await self.app(scope, receive, send)
            return

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                cabeceras = [
                    (k, v)
                    for k, v in mensaje.get("headers", [])
                    if k.lower() != b"cache-control"
                ]
                cabeceras.append((b"cache-control", b"no-store"))
                mensaje["headers"] = cabeceras
            await send(mensaje)

        await self.app(scope, receive, enviar)


def crear_router(servicio: str) -> APIRouter:
    router = APIRouter(prefix="/api/web")
    router.include_router(comun.router)
    if servicio == "calidad":
        from app.api.web import calidad

        router.include_router(calidad.router)
    elif servicio == "admision":
        from app.api.web import admision

        router.include_router(admision.router)
    elif servicio == "oportunidades":
        from app.api.web import oportunidades

        router.include_router(oportunidades.router)
    elif servicio == "actas":
        from app.api.web import actas, archivo, secretaria

        router.include_router(actas.router)
        router.include_router(archivo.router)
        router.include_router(secretaria.router)
    return router


__all__ = ["SinCache", "crear_router"]
