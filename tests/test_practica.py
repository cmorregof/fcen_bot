"""Entorno de práctica: flag, base propia, sin Telegram, siembra y reinicio."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import practica
from app.api.web import auth, crear_router
from app.api.web.config import web_settings
from app.core.config import Settings, settings
from app.integrations import telegram
from app.services import casos
from tests.conftest import abrir_base


@pytest.fixture
def en_practica(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "memoria_practica", True)
    (tmp_path / "practica").mkdir()
    monkeypatch.setattr(settings, "db_path", tmp_path / "practica" / "fcen.db")
    monkeypatch.setattr(web_settings, "session_secret", "secreto-de-prueba")
    monkeypatch.setattr(web_settings, "admins", "admin@unal.edu.co")
    monkeypatch.setattr(web_settings, "auth_dev", False)


def _cliente(servicio: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "bot_servicio", servicio)
    app = FastAPI()
    app.include_router(crear_router(servicio))
    return TestClient(app)


def _cab(correo: str, rol: str) -> dict[str, str]:
    usuario = auth.Usuario(correo, None, rol, None)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {auth.sesion_de(usuario)}"}


# --- flag y rutas -----------------------------------------------------------


def test_flag_apagado_por_defecto() -> None:
    assert Settings(_env_file=None).memoria_practica is False  # type: ignore[call-arg]


@pytest.mark.parametrize("servicio", ["actas", "calidad", "admision", "oportunidades"])
def test_base_de_practica_separada(
    servicio: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORIA_PRACTICA", "true")
    monkeypatch.setenv("BOT_SERVICIO", servicio)
    monkeypatch.setenv("DATA_DIR", "/data")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:token-real")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secreto")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.db_path == Path("/data/practica") / servicio / "fcen.db"
    assert "practica" in s.media_dir.parts and "practica" in s.output_dir.parts
    # Aunque el entorno traiga token, la práctica no lo conserva.
    assert s.telegram_bot_token == "" and s.telegram_webhook_secret == ""


def test_practica_rechaza_la_base_de_produccion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORIA_PRACTICA", "true")
    monkeypatch.setenv("DB_PATH", "/data/actas/fcen.db")
    with pytest.raises(ValueError, match="practica"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_sin_practica_la_base_no_cambia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORIA_PRACTICA", raising=False)
    monkeypatch.setenv("DATA_DIR", "/data-inexistente")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "practica" not in s.db_path.parts


@pytest.mark.parametrize("valor", [True, False])
def test_entorno_informa_el_flag(valor: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memoria_practica", valor)
    r = _cliente("calidad", monkeypatch).get("/api/web/entorno")
    assert r.status_code == 200
    assert r.json() == {"servicio": "calidad", "practica": valor}


# --- Telegram ---------------------------------------------------------------


async def test_en_practica_no_sale_nada_a_telegram(
    en_practica: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def prohibido(*a: Any, **kw: Any) -> None:
        raise AssertionError("En práctica no debe abrirse ninguna conexión")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", prohibido)
    assert await telegram.send_message(1, "hola") is None
    await telegram.send_document(1, nombre="a.txt", contenido=b"x", mime="text/plain")
    await telegram.editar_botones(1, 2, None)
    await telegram.responder_callback("cb", "texto")
    await telegram.set_webhook("https://x.test/webhook", "s")
    with pytest.raises(RuntimeError):
        await telegram.descargar_archivo("f")


async def test_fuera_de_practica_si_llama_a_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "memoria_practica", False)
    llamadas: list[str] = []

    async def falso(self: httpx.AsyncClient, url: str, **kw: Any) -> httpx.Response:
        llamadas.append(url)
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 7}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", falso)
    assert await telegram.send_message(1, "hola") == 7
    assert len(llamadas) == 1


# --- siembra ----------------------------------------------------------------


async def _contar(sql: str) -> int:
    async with abrir_base() as db:
        cur = await db.execute(sql)
        fila = await cur.fetchone()
        return int(fila[0]) if fila else 0


async def test_siembra_actas_es_idempotente_y_ficticia(
    en_practica: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "bot_servicio", "actas")
    await practica.reiniciar()
    primera = await _contar("SELECT COUNT(*) FROM casos")
    assert 6 <= primera <= 8
    await practica.reiniciar()
    assert await _contar("SELECT COUNT(*) FROM casos") == primera
    assert await _contar("SELECT MIN(id) FROM casos") == 1

    from app.db import repo
    from app.db.session import connect

    db = await connect()
    try:
        lista = [
            c
            for d in ("ciencias_naturales", "matematicas")
            for c in await repo.casos_recientes(db, direccion=d, limite=50)
        ]
    finally:
        await db.close()
    tipos = {t.value for c in lista if c.extraccion for t in c.extraccion.tipos}
    assert {
        "carga_minima",
        "cancelacion",
        "traslado",
        "designacion_jurados",
        "proyecto_tesis",
        "pae",
        "inscripcion_extemporanea",
    } <= tipos
    for c in lista:
        assert c.extraccion is not None
        assert c.extraccion.documento and c.extraccion.documento.startswith("1000000")
        assert "Fictici" in (c.extraccion.nombre_estudiante or "")
        assert casos.analizar(c) is not None


async def test_siembra_calidad_y_admision(
    en_practica: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "bot_servicio", "calidad")
    await practica.reiniciar()
    acciones = await _contar("SELECT COUNT(*) FROM cal_acciones")
    assert acciones > 0
    await practica.reiniciar()
    assert await _contar("SELECT COUNT(*) FROM cal_acciones") == acciones

    monkeypatch.setattr(settings, "db_path", settings.db_path.with_name("adm.db"))
    monkeypatch.setattr(settings, "bot_servicio", "admision")
    await practica.reiniciar()
    await practica.reiniciar()
    assert await _contar("SELECT SUM(valor) FROM admision_metricas") == 65


async def test_reiniciar_conserva_usuarios_y_borra_lo_creado(
    en_practica: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "bot_servicio", "actas")
    await practica.reiniciar()
    async with abrir_base() as db:
        await db.execute(
            "INSERT INTO web_usuarios (correo, rol, direccion) VALUES (?, ?, ?)",
            ("asistente@unal.edu.co", "administrativa", "matematicas"),
        )
        await db.execute(
            "INSERT INTO casos (chat_id, user_id, direccion) VALUES (0, 0, 'matematicas')"
        )
        await db.commit()
    (settings.media_dir / "9").mkdir(parents=True)
    await practica.reiniciar()
    assert await _contar("SELECT COUNT(*) FROM web_usuarios") == 1
    assert await _contar("SELECT COUNT(*) FROM casos WHERE id > 8") == 0
    assert not (settings.media_dir / "9").exists()


def test_autorizar_asistentes_desde_csv(
    en_practica: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    monkeypatch.setattr(settings, "bot_servicio", "actas")
    csv = tmp_path / "a.csv"
    csv.write_text(
        "correo,nombre,rol,direccion\n"
        "uno@unal.edu.co,Uno Ficticio,administrativa,matematicas\n"
        "dos@unal.edu.co,Dos Ficticio,calidad,\n"  # rol de otro servicio
        "tres@gmail.com,Tres,administrativa,matematicas\n"  # dominio
        "cuatro@unal.edu.co,Cuatro,administrativa,\n",  # sin área
        encoding="utf-8",
    )
    assert asyncio.run(practica.autorizar_asistentes(csv)) == 1


# --- reinicio por la web ----------------------------------------------------


@pytest.mark.parametrize(
    ("rol", "esperado"),
    [("admin", 200), ("decanatura", 403), ("administrativa", 403)],
)
def test_reinicio_exige_admin(
    rol: str, esperado: int, en_practica: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _cliente("actas", monkeypatch)
    # La tabla de usuarios debe existir para que decanatura/administrativa lleguen a 403.
    import asyncio

    async def _alta() -> None:
        async with abrir_base() as db:
            await db.execute(auth._ESQUEMA)
            await db.execute(
                "INSERT INTO web_usuarios (correo, rol, direccion) VALUES (?, ?, ?)",
                (
                    "x@unal.edu.co",
                    rol,
                    "matematicas" if rol == "administrativa" else None,
                ),
            )
            await db.commit()

    if rol != "admin":
        asyncio.run(_alta())
    correo = "admin@unal.edu.co" if rol == "admin" else "x@unal.edu.co"
    r = c.post("/api/web/practica/reiniciar", headers=_cab(correo, rol))
    assert r.status_code == esperado, r.text


def test_reinicio_sin_sesion_es_401(
    en_practica: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _cliente("actas", monkeypatch)
    assert c.post("/api/web/practica/reiniciar").status_code == 401


def test_reinicio_no_existe_fuera_de_practica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "memoria_practica", False)
    monkeypatch.setattr(web_settings, "session_secret", "secreto-de-prueba")
    monkeypatch.setattr(web_settings, "admins", "admin@unal.edu.co")
    c = _cliente("actas", monkeypatch)
    r = c.post(
        "/api/web/practica/reiniciar", headers=_cab("admin@unal.edu.co", "admin")
    )
    assert r.status_code == 404
    with pytest.raises(practica.NoEsPractica):
        practica.exigir_practica()


def test_el_script_no_corre_fuera_de_practica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    monkeypatch.setattr(settings, "memoria_practica", False)
    with pytest.raises(practica.NoEsPractica):
        asyncio.run(practica.reiniciar())


async def test_primer_arranque_siembra_y_los_siguientes_no(
    en_practica: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app

    monkeypatch.setattr(settings, "bot_servicio", "actas")
    with TestClient(app):
        assert await _contar("SELECT COUNT(*) FROM casos") == 8
    async with abrir_base() as db:
        await db.execute("DELETE FROM casos")
        await db.commit()
    with TestClient(app):
        assert await _contar("SELECT COUNT(*) FROM casos") == 0


def test_practica_rechaza_rutas_con_punto_punto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORIA_PRACTICA", "true")
    monkeypatch.setenv("DATA_DIR", "/data")
    monkeypatch.setenv("DB_PATH", "/data/practica/../actas/fcen.db")
    with pytest.raises(ValueError, match="dentro de"):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("valor", ["y", "t", "on", "1", "TRUE"])
def test_mismo_parser_del_flag(valor: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORIA_PRACTICA", valor)
    monkeypatch.setenv("DATA_DIR", "/data")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.memoria_practica and "practica" in s.db_path.parts


def test_practica_anula_las_urls_del_resumen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORIA_PRACTICA", "true")
    monkeypatch.setenv("RESUMEN_SECRET", "real")
    monkeypatch.setenv("RESUMEN_CALIDAD_URL", "https://prod.test")
    monkeypatch.setenv("RESUMEN_ADMISION_URL", "https://prod.test")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert not (s.resumen_secret or s.resumen_calidad_url or s.resumen_admision_url)


async def test_siembra_fallida_se_reintenta_al_arrancar(
    en_practica: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app

    monkeypatch.setattr(settings, "bot_servicio", "actas")

    async def falla(db: aiosqlite.Connection) -> int:
        raise RuntimeError("falló a medias")

    with monkeypatch.context() as m:
        m.setitem(practica._SEMBRAR, "actas", falla)
        with pytest.raises(RuntimeError), TestClient(app):
            pass
    with TestClient(app):
        assert await _contar("SELECT COUNT(*) FROM casos") == 8
