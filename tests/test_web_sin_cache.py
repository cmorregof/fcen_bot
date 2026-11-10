"""La web llega a los backends por el proxy de Vercel: las respuestas de
/api/web no se guardan en caché (ni en Vercel ni en el navegador)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, Response
from fastapi.testclient import TestClient

from app.api.web import SinCache


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SinCache)

    @app.get("/api/web/dato")
    def dato() -> dict[str, int]:
        return {"x": 1}

    @app.get("/api/web/archivo")
    def archivo() -> Response:
        return PlainTextResponse("a", headers={"Cache-Control": "max-age=600"})

    @app.post("/api/web/subir")
    async def subir(cuerpo: dict[str, int]) -> dict[str, int]:
        return cuerpo

    @app.get("/otra")
    def otra() -> dict[str, int]:
        return {"x": 1}

    return app


def test_las_respuestas_de_la_web_no_se_guardan() -> None:
    c = TestClient(_app())
    assert c.get("/api/web/dato").headers["cache-control"] == "no-store"
    # Si una ruta pide caché, se reemplaza: un solo Cache-Control.
    r = c.get("/api/web/archivo")
    assert r.headers.get_list("cache-control") == ["no-store"]
    # El cuerpo de la petición llega intacto.
    r = c.post("/api/web/subir", json={"y": 2})
    assert r.json() == {"y": 2} and r.headers["cache-control"] == "no-store"
    # Fuera de /api/web no se toca nada.
    assert "cache-control" not in c.get("/otra").headers


def test_la_app_monta_el_middleware() -> None:
    from app.main import app

    assert any(m.cls is SinCache for m in app.user_middleware)
