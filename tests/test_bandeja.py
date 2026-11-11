"""Archivar de la bandeja: marca aparte de la etapa (app/services/flujo.py).

Datos ficticios. La administrativa saca de su bandeja los casos terminados
sin borrarlos y sin cambiar la etapa oficial ni los indicadores.
"""

from __future__ import annotations

import aiosqlite
import pytest

from app.db import repo
from app.db.session import init_db
from app.services import flujo, indicadores
from app.services.flujo import Accion, Etapa, TransicionNoPermitida
from tests.test_flujo import _decidir, _hasta_consejo, _nuevo
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

ADM = flujo.ADMINISTRATIVA
AREA = "ciencias_naturales"


async def _decidido(db: aiosqlite.Connection) -> int:
    caso = await _hasta_consejo(db)
    await _decidir(db, caso, "2026-10-01")
    return caso


async def test_archivar_no_cambia_la_etapa_y_queda_en_la_linea(
    db: aiosqlite.Connection,
) -> None:
    caso = await _decidido(db)
    hoy = indicadores.hoy_local()
    periodo = indicadores.periodo_de(f"{hoy.year}", hoy)
    antes = await indicadores.reporte(db, periodo, hoy)
    tramos_antes = flujo.tramos(await flujo.eventos(db, caso))

    n = await flujo.archivar_de_bandeja(
        db, [caso], rol=ADM, persona="Marta Ficticia", canal="web", direccion=AREA
    )

    assert n == 1
    assert await flujo.etapa_de(db, caso) == Etapa.DECIDIDA
    leido = await repo.get_caso(db, caso)
    assert leido is not None and leido.archivado is not None
    ultimo = (await flujo.eventos(db, caso))[-1]
    assert ultimo.accion == Accion.SACAR_DE_BANDEJA
    assert ultimo.desde == ultimo.hacia == Etapa.DECIDIDA
    assert ultimo.persona == "Marta Ficticia"
    assert flujo.tramos(await flujo.eventos(db, caso)) == tramos_antes
    assert await indicadores.reporte(db, periodo, hoy) == antes

    # Archivar de nuevo no repite el registro.
    assert (
        await flujo.archivar_de_bandeja(
            db, [caso], rol=ADM, persona="x", canal="web", direccion=AREA
        )
        == 0
    )

    n = await flujo.desarchivar_de_bandeja(
        db, [caso], rol=ADM, persona="Marta Ficticia", canal="web", direccion=AREA
    )
    assert n == 1
    leido = await repo.get_caso(db, caso)
    assert leido is not None and leido.archivado is None
    assert (await flujo.eventos(db, caso))[-1].accion == Accion.VOLVER_A_BANDEJA
    assert await flujo.etapa_de(db, caso) == Etapa.DECIDIDA


async def test_un_caso_en_curso_no_se_archiva_y_el_lote_es_atomico(
    db: aiosqlite.Connection,
) -> None:
    terminado = await _decidido(db)
    en_curso = await _nuevo(db)
    with pytest.raises(TransicionNoPermitida, match="sigue en curso"):
        await flujo.archivar_de_bandeja(
            db,
            [terminado, en_curso],
            rol=ADM,
            persona="x",
            canal="web",
            direccion=AREA,
        )
    leido = await repo.get_caso(db, terminado)
    assert leido is not None and leido.archivado is None


async def test_solo_la_administrativa_de_su_area_o_admin(
    db: aiosqlite.Connection,
) -> None:
    caso = await _decidido(db)
    for rol in ("comite", "secretaria", "decanatura"):
        with pytest.raises(TransicionNoPermitida):
            await flujo.archivar_de_bandeja(
                db, [caso], rol=rol, persona="x", canal="web", direccion=AREA
            )
    with pytest.raises(TransicionNoPermitida, match="en su área"):
        await flujo.archivar_de_bandeja(
            db, [caso], rol=ADM, persona="x", canal="web", direccion="otra_area"
        )
    # Admin, sin dirección: cualquiera.
    assert (
        await flujo.archivar_de_bandeja(
            db, [caso], rol=flujo.ADMIN, persona="x", canal="web", direccion=None
        )
        == 1
    )


async def test_la_migracion_es_idempotente(db: aiosqlite.Connection) -> None:
    caso = await _decidido(db)
    await flujo.archivar_de_bandeja(
        db, [caso], rol=ADM, persona="x", canal="web", direccion=AREA
    )
    await init_db(db)
    await init_db(db)
    await db.commit()
    leido = await repo.get_caso(db, caso)
    assert leido is not None and leido.archivado is not None


async def test_bandeja_web(
    db: aiosqlite.Connection,
    cliente: Cliente,  # noqa: F811
) -> None:
    uno = await _decidido(db)
    dos = await _decidido(db)
    activo = await _nuevo(db)
    await db.commit()
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", AREA)
    com = await _token("com@unal.edu.co", "comite", AREA)
    admin = await _token("admin@unal.edu.co", "admin")

    bandeja = c.get("/api/web/actas/casos", headers=adm).json()["casos"]
    archivables = {x["id"] for x in bandeja if x["archivable"]}
    assert {uno, dos} <= archivables and activo not in archivables

    # El comité no archiva.
    r = c.post("/api/web/actas/casos/archivar", json={"ids": [uno]}, headers=com)
    assert r.status_code == 403
    # Un caso en curso no se archiva, ni en lote.
    r = c.post(
        "/api/web/actas/casos/archivar", json={"ids": [uno, activo]}, headers=adm
    )
    assert r.status_code == 409
    # En lote.
    r = c.post("/api/web/actas/casos/archivar", json={"ids": [uno, dos]}, headers=adm)
    assert r.status_code == 200 and r.json() == {"archivados": 2}

    activos = {
        x["id"] for x in c.get("/api/web/actas/casos", headers=adm).json()["casos"]
    }
    assert activo in activos and uno not in activos and dos not in activos
    archivados = c.get("/api/web/actas/casos?archivados=true", headers=adm).json()
    assert {x["id"] for x in archivados["casos"]} == {uno, dos}
    assert all(x["archivado"] for x in archivados["casos"])

    ficha = c.get(f"/api/web/actas/casos/{uno}", headers=adm).json()
    assert ficha["etapa"] == "decidida"
    assert ficha["linea"][-1]["accion"] == "sacar_de_bandeja"

    # Admin puede devolverlo a la bandeja.
    r = c.post("/api/web/actas/casos/desarchivar", json={"ids": [uno]}, headers=admin)
    assert r.status_code == 200 and r.json() == {"desarchivados": 1}
    activos = {
        x["id"] for x in c.get("/api/web/actas/casos", headers=adm).json()["casos"]
    }
    assert uno in activos
