"""Aislamiento entre direcciones: pregrado y posgrados de matemáticas.

Todos los datos son ficticios.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web import auth, crear_router
from app.api.web.config import web_settings
from app.core.conexion import Conexion
from app.core.config import settings
from app.core.programas import (
    COMITES,
    DIRECCIONES,
    PROGRAMAS,
    identificar_programa,
    programa_unico,
    programas_de,
)
from app.db import repo
from app.db.reubicar import reubicar_posgrados
from app.db.session import connect
from app.schemas.caso import DatosSIA
from app.services import firma
from app.services.extraccion import _programa_de
from tests.conftest import extraccion_ejemplo

POSGRADOS = "posgrados_matematicas"
PREGRADO = "matematicas"


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------


def test_posgrados_de_matematicas_tienen_su_direccion() -> None:
    assert POSGRADOS in DIRECCIONES
    assert {p.clave for p in programas_de(POSGRADOS)} == {
        "esp_actuaria",
        "esp_estadistica",
        "mecen",
        "mcma",
        "dcm",
    }
    assert all(p.nivel == "posgrado" for p in programas_de(POSGRADOS))
    assert {p.clave for p in programas_de(PREGRADO)} == {
        "matematicas",
        "estadistica",
        "ciencias_computacion",
    }
    assert all(p.nivel == "pregrado" for p in programas_de(PREGRADO))


def test_programas_nuevos_sin_datos_inventados() -> None:
    for clave in ("esp_actuaria", "esp_estadistica", "dcm"):
        p = PROGRAMAS[clave]
        assert p.planes == () and p.correo is None and p.radicado_prefijo is None
        assert p.miembros == ()


@pytest.mark.parametrize(
    ("plan", "clave"),
    [
        ("DOCTORADO EN CIENCIAS - MATEMÁTICAS", "dcm"),
        ("Doctorado en Ciencias Matemáticas", "dcm"),
        ("ESPECIALIZACIÓN EN ESTADÍSTICA", "esp_estadistica"),
        ("Especialización en Actuaría", "esp_actuaria"),
        ("ESPECIALIZACIÓN EN ACTUARÍA Y FINANZAS", "esp_actuaria"),
        ("MAESTRÍA EN CIENCIAS - MATEMÁTICA APLICADA", "mcma"),
        ("MATEMÁTICAS", "matematicas"),
        ("ESTADÍSTICA", "estadistica"),
    ],
)
def test_el_alias_mas_largo_gana(plan: str, clave: str) -> None:
    programa = identificar_programa(None, plan)
    assert programa is not None and programa.clave == clave


def test_programa_de_otra_direccion_no_se_acepta() -> None:
    doctorado = extraccion_ejemplo(
        sia=DatosSIA(plan_nombre="DOCTORADO EN CIENCIAS - MATEMATICAS")
    )
    assert _programa_de(doctorado, PREGRADO) is None
    programa = _programa_de(doctorado, POSGRADOS)
    assert programa is not None and programa.clave == "dcm"
    pregrado = extraccion_ejemplo(sia=DatosSIA(plan_nombre="MATEMATICAS"))
    assert _programa_de(pregrado, POSGRADOS) is None


def test_un_solo_programa_no_se_pregunta(monkeypatch: pytest.MonkeyPatch) -> None:
    assert programa_unico(POSGRADOS) is None
    import app.services.extraccion as extraccion

    unico = PROGRAMAS["mcf"]
    monkeypatch.setattr(extraccion, "programa_unico", lambda d: unico)
    sin_plan = extraccion_ejemplo(sia=None)
    assert _programa_de(sin_plan, "ciencias_naturales") == unico


def test_firmar_solo_programas_de_la_direccion() -> None:
    # En posgrados se firma el comité único, sea cual sea el programa escrito.
    assert firma.programa_de_la_direccion("dcm", POSGRADOS) == COMITES[POSGRADOS]
    assert firma.programa_de_la_direccion("matematicas", POSGRADOS) is None
    assert firma.programa_de_la_direccion("mcma", PREGRADO) is None


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------


async def _caso(
    db: Conexion, programa: str | None, *, plan: str | None = None, persona: str = "x"
) -> int:
    caso_id = await repo.crear_caso(
        db, chat_id=0, user_id=0, direccion=PREGRADO, canal="web", persona=persona
    )
    if plan is not None:
        e = extraccion_ejemplo(sia=DatosSIA(plan_nombre=plan))
        await repo.guardar_extraccion(db, caso_id, e, programa)
    elif programa is not None:
        await repo.set_programa(db, caso_id, programa)
    return caso_id


async def _donde(db: Conexion, caso_id: int) -> tuple[str, str | None]:
    caso = await repo.get_caso(db, caso_id)
    assert caso is not None
    return caso.direccion, caso.programa


async def test_migracion_mueve_los_casos_de_posgrado(db: Conexion) -> None:
    await db.execute(auth._ESQUEMA)
    await db.execute(
        "INSERT INTO web_usuarios (correo, nombre, rol, direccion)"
        " VALUES (?, ?, 'administrativa', ?)",
        ("posgrado.ficticia@unal.edu.co", "Posgrado Ficticia", POSGRADOS),
    )
    maestria = await _caso(db, "mcma")
    # Antes, el doctorado se tomaba por el pregrado de Matemáticas.
    doctorado = await _caso(
        db, "matematicas", plan="DOCTORADO EN CIENCIAS - MATEMATICAS"
    )
    suyo = await _caso(db, "matematicas", persona="Posgrado Ficticia")
    pregrado = await _caso(db, "estadistica", plan="ESTADISTICA")
    sin_nada = await _caso(db, None)
    await db.commit()

    assert await reubicar_posgrados(db) == 3
    await db.commit()
    assert await reubicar_posgrados(db) == 0  # idempotente

    assert await _donde(db, maestria) == (POSGRADOS, "mcma")
    assert await _donde(db, doctorado) == (POSGRADOS, "dcm")
    assert await _donde(db, suyo) == (POSGRADOS, None)
    assert await _donde(db, pregrado) == (PREGRADO, "estadistica")
    assert await _donde(db, sin_nada) == (PREGRADO, None)


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------

Cliente = Callable[[], TestClient]


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> Cliente:
    monkeypatch.setattr(web_settings, "session_secret", "secreto-de-prueba")
    monkeypatch.setattr(web_settings, "admins", "admin@unal.edu.co")
    monkeypatch.setattr(web_settings, "auth_dev", False)

    def _crear() -> TestClient:
        monkeypatch.setattr(settings, "bot_servicio", "actas")
        app = FastAPI()
        app.include_router(crear_router("actas"))
        return TestClient(app)

    return _crear


async def _token(correo: str, rol: str, direccion: str | None = None) -> dict[str, str]:
    db = await connect()
    await db.execute(auth._ESQUEMA)
    await db.execute(
        "INSERT INTO web_usuarios (correo, rol, direccion) VALUES (?, ?, ?)"
        " ON CONFLICT(correo) DO UPDATE SET direccion = excluded.direccion",
        (correo, rol, direccion),
    )
    await db.commit()
    await db.close()
    usuario = auth.Usuario(correo, None, rol, direccion)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {auth.sesion_de(usuario)}"}


async def test_cada_administrativa_ve_solo_su_direccion(cliente: Cliente) -> None:
    c = cliente()
    pos = await _token("pos.ficticia@unal.edu.co", "administrativa", POSGRADOS)
    pre = await _token("pre.ficticia@unal.edu.co", "administrativa", PREGRADO)

    r = c.post("/api/web/actas/casos", data={"texto": "Correo ficticio"}, headers=pos)
    caso_pos = r.json()["id"]
    r = c.post("/api/web/actas/casos", data={"texto": "Otro ficticio"}, headers=pre)
    caso_pre = r.json()["id"]

    lista = c.get("/api/web/actas/casos", headers=pos).json()
    assert lista["area"] == DIRECCIONES[POSGRADOS].nombre
    assert [x["id"] for x in lista["casos"]] == [caso_pos]
    lista = c.get("/api/web/actas/casos", headers=pre).json()
    assert [x["id"] for x in lista["casos"]] == [caso_pre]

    assert c.get(f"/api/web/actas/casos/{caso_pos}", headers=pre).status_code == 404
    assert c.get(f"/api/web/actas/casos/{caso_pre}", headers=pos).status_code == 404

    ficha = c.get(f"/api/web/actas/casos/{caso_pos}", headers=pos).json()
    assert {p["clave"] for p in ficha["programas"]} == {
        p.clave for p in programas_de(POSGRADOS)
    }
    ruta = f"/api/web/actas/casos/{caso_pos}/programa"
    assert (
        c.post(ruta, json={"programa": "matematicas"}, headers=pos).status_code == 400
    )
    assert c.post(ruta, json={"programa": "dcm"}, headers=pos).status_code == 200

    archivo = c.get("/api/web/actas/archivo", headers=pos).json()
    # Las actas de posgrados son del comité único: se archivan con su clave.
    assert [p["clave"] for p in archivo["programas"]] == [POSGRADOS]
    assert c.get("/api/web/actas/firmar/dcm", headers=pre).status_code == 404


async def test_usuarios_ofrece_la_direccion_y_mueve_sus_casos(
    cliente: Cliente,
) -> None:
    c = cliente()
    correo = "pos.ficticia@unal.edu.co"
    viejo = await _token(correo, "administrativa", PREGRADO)
    caso = c.post("/api/web/actas/casos", data={"texto": "x"}, headers=viejo).json()[
        "id"
    ]

    admin = await _token("admin@unal.edu.co", "admin")
    lista = c.get("/api/web/usuarios", headers=admin).json()
    assert lista["direcciones"][POSGRADOS] == (
        "Área Curricular de Posgrados de Ciencias Exactas"
    )
    cuerpo = {"correo": correo, "rol": "administrativa", "direccion": POSGRADOS}
    assert c.post("/api/web/usuarios", json=cuerpo, headers=admin).status_code == 200

    # La dirección se relee de la base en cada petición: no hay que reingresar.
    assert c.get(f"/api/web/actas/casos/{caso}", headers=viejo).status_code == 200
    lista = c.get("/api/web/actas/casos", headers=viejo).json()
    assert lista["area"] == DIRECCIONES[POSGRADOS].nombre
    pre = await _token("pre.ficticia@unal.edu.co", "administrativa", PREGRADO)
    assert c.get(f"/api/web/actas/casos/{caso}", headers=pre).status_code == 404
