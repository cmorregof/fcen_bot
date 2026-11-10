"""Actas del comité por programa: consecutivo, cierre y acta siguiente
(app/services/actas_comite.py). Datos ficticios."""

from __future__ import annotations

import hashlib
import json
from datetime import date

import aiosqlite
import pytest

from app.db import repo
from app.db.session import connect
from app.schemas.caso import EstadoCaso, Sentido
from app.services import actas_comite, bot, firma, flujo
from app.services.flujo import Etapa
from tests.conftest import TelegramFalso
from tests.test_bot import USUARIO, _callback, _update
from tests.test_firma import (  # noqa: F401
    ADM,
    DIR,
    PROG,
    SESION,
    _caso,
    _con_imagen,
    _registrar_matematicas,
    carpeta_firmas,
)
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

HOY = date(2026, 11, 9)
OTRO = "estadistica"  # otro programa de la misma dirección


async def _firmar(db: aiosqlite.Connection, numero: str, radicado: str) -> firma.Firma:
    prep = await firma.preparar(db, direccion=DIR, clave=PROG, hoy=HOY)
    return await firma.firmar(
        db,
        direccion=DIR,
        clave=PROG,
        radicado=radicado,
        sesion=firma.DatosSesion(numero, SESION.fecha_sesion, "10 a. m.", "Sala"),
        caso_ids=prep.caso_ids,
        persona="Persona Administrativa",
        rol=ADM,
        canal="web",
        hoy=HOY,
    )


async def _cerrar(
    db: aiosqlite.Connection, numero: int, clave: str = PROG
) -> actas_comite.ActaComite:
    acta = await actas_comite.abierta(db, direccion=DIR, clave=clave, hoy=HOY)
    return await actas_comite.cerrar_sin_firma(
        db,
        direccion=DIR,
        clave=clave,
        numero=numero,
        fecha_sesion=date(2026, 11, 6),
        caso_ids=acta.caso_ids,
        persona="Persona Administrativa",
        rol=ADM,
        canal="web",
        hoy=HOY,
    )


def test_numero_del_acta() -> None:
    assert actas_comite.leer_numero("019") == 19
    assert actas_comite.leer_numero(" Acta No. 7 ") == 7
    for malo in ("", "0", "19-A", "acta diecinueve"):
        with pytest.raises(ValueError):
            actas_comite.leer_numero(malo)
    sesion = firma.validar_sesion(
        numero_acta="acta 7", fecha_sesion="2026-11-05", hora="10", lugar="Sala"
    )
    assert sesion.numero_acta == "007"


async def test_consecutivo_cierre_y_acta_siguiente(db: aiosqlite.Connection) -> None:
    _con_imagen()
    primero = await _caso(db, Sentido.APROBAR)
    pendiente = await _caso(db, Sentido.PENDIENTE, nombre="Persona Ficticia Dos")

    # La primera del año se propone como 001.
    prep = await firma.preparar(db, direccion=DIR, clave=PROG, hoy=HOY)
    assert prep.numero_acta_propuesto == "001"
    hecha = await _firmar(db, "001", "Mz.FCEN.1.065-001-26")

    [acta] = await actas_comite.de_la_direccion(db, DIR)
    assert (acta.numero, acta.anio, acta.fecha_sesion) == (1, 2026, "2026-11-05")
    assert acta.estado == actas_comite.FIRMADA and acta.firma_id == hecha.id
    assert acta.caso_ids == [primero]  # el pendiente no entra

    # El caso firmado sale del borrador; el pendiente y los nuevos van a la 002.
    caso = await repo.get_caso(db, primero)
    assert caso and caso.estado == EstadoCaso.CERRADO
    nuevo = await _caso(db, Sentido.NO_APROBAR, nombre="Persona Ficticia Tres")
    await flujo.recomendar(
        db, pendiente, Sentido.APROBAR, rol=ADM, persona="Adm", canal="web"
    )
    siguiente = await actas_comite.abierta(db, direccion=DIR, clave=PROG, hoy=HOY)
    assert siguiente.numero_propuesto == 2
    assert sorted(siguiente.caso_ids) == sorted([pendiente, nuevo])

    # Cierre sin firma: la dirección numeró por fuera, la persona corrige a 010.
    cerrada = await _cerrar(db, 10)
    assert cerrada.numero_texto == "010" and cerrada.estado == actas_comite.CERRADA
    assert sorted(cerrada.caso_ids) == sorted([pendiente, nuevo])
    assert cerrada.docx_ruta and cerrada.docx_sha256
    assert actas_comite.leer_docx(cerrada) == cerrada.docx_ruta.read_bytes()
    for caso_id in (pendiente, nuevo):
        c = await repo.get_caso(db, caso_id)
        assert c and c.estado == EstadoCaso.CERRADO and c.etapa == Etapa.EN_CONSEJO
    assert await actas_comite.proponer_numero(db, PROG, 2026) == 11
    assert [a.numero for a in await actas_comite.de_la_direccion(db, DIR)] == [10, 1]


async def test_no_hay_doble_cierre(db: aiosqlite.Connection) -> None:
    _con_imagen()
    await _caso(db)
    await _firmar(db, "001", "Mz.FCEN.1.065-001-26")

    # Sin casos con recomendación no se cierra (un segundo clic, p. ej.).
    with pytest.raises(actas_comite.ActaNoPermitida, match="No hay casos"):
        await _cerrar(db, 2)

    # El mismo número no se repite, ni firmando ni cerrando.
    await _caso(db, nombre="Persona Ficticia Dos")
    with pytest.raises(firma.FirmaNoPermitida, match="ya está cerrada"):
        await _firmar(db, "1", "Mz.FCEN.1.065-002-26")
    with pytest.raises(actas_comite.ActaNoPermitida, match="ya está cerrada"):
        await _cerrar(db, 1)

    # Casos que cambiaron desde el resumen: no se cierra.
    acta = await actas_comite.abierta(db, direccion=DIR, clave=PROG, hoy=HOY)
    with pytest.raises(actas_comite.ActaNoPermitida, match="cambiaron"):
        await actas_comite.cerrar_sin_firma(
            db,
            direccion=DIR,
            clave=PROG,
            numero=2,
            fecha_sesion=HOY,
            caso_ids=[*acta.caso_ids, 999],
            persona="x",
            rol=ADM,
            canal="web",
            hoy=HOY,
        )
    assert len(await actas_comite.de_la_direccion(db, DIR)) == 1


async def test_aislamiento_por_programa_y_direccion(db: aiosqlite.Connection) -> None:
    await _caso(db)
    await _caso(db, programa=OTRO, nombre="Persona Ficticia Dos")
    await _cerrar(db, 5)
    # Otro programa de la misma dirección lleva su propio consecutivo.
    otro = await actas_comite.abierta(db, direccion=DIR, clave=OTRO, hoy=HOY)
    assert otro.numero_propuesto == 1 and len(otro.casos) == 1
    assert (await _cerrar(db, 5, OTRO)).numero == 5  # el mismo número, otro programa
    assert await actas_comite.proponer_numero(db, PROG, 2026) == 6
    # Cada año empieza en 001.
    assert await actas_comite.proponer_numero(db, PROG, 2027) == 1
    # Un programa de otra dirección no se cierra desde esta.
    with pytest.raises(actas_comite.ActaNoPermitida, match="No conozco"):
        await actas_comite.abierta(
            db, direccion="ciencias_naturales", clave=PROG, hoy=HOY
        )
    assert await actas_comite.de_la_direccion(db, "ciencias_naturales") == []


async def test_migracion_sin_inventar_numeros(db: aiosqlite.Connection) -> None:
    """Firmas y casos cerrados de antes del consecutivo; corre dos veces."""
    con_numero = await _caso(db)
    sin_numero = await _caso(db, nombre="Persona Ficticia Dos")
    cerrado = await _caso(db, nombre="Persona Ficticia Tres")
    await repo.cerrar_casos(db, [con_numero, sin_numero, cerrado])
    for radicado, numero, caso_id in (
        ("Mz.FCEN.1.065-001-26", "019", con_numero),
        ("Mz.FCEN.1.065-002-26", "extraordinaria", sin_numero),
    ):
        await db.execute(
            "INSERT INTO firmas (direccion, programa, radicado, numero_acta, "
            "fecha_sesion, hora, lugar, caso_ids, firmante, firmado_por, rol, "
            "canal, con_imagen) VALUES (?, ?, ?, ?, '2026-11-05', 'h', 'l', ?, "
            "'f', 'p', 'administrativa', 'web', 0)",
            (DIR, PROG, radicado, numero, json.dumps([caso_id])),
        )
    await db.execute("DELETE FROM acta_comite_casos")
    await db.execute("DELETE FROM actas_comite")

    assert await actas_comite.migrar(db, tabla_nueva=True) == 3
    assert await actas_comite.migrar(db, tabla_nueva=True) == 0
    assert await actas_comite.migrar(db, tabla_nueva=False) == 0
    await db.commit()
    actas = {tuple(a.caso_ids): a for a in await actas_comite.de_la_direccion(db, DIR)}
    assert actas[(con_numero,)].numero == 19
    assert actas[(sin_numero,)].numero is None  # no se inventa
    historica = actas[(cerrado,)]
    assert historica.numero is None and historica.fecha_sesion is None
    assert historica.canal == "migracion"
    assert await actas_comite.proponer_numero(db, PROG, 2026) == 20


# ---------------------------------------------------------------------------
# Web y bot
# ---------------------------------------------------------------------------


async def test_web_cerrar_acta_y_lista(cliente: Cliente) -> None:  # noqa: F811
    db = await connect()
    caso = await _caso(db)
    await _caso(db, Sentido.PENDIENTE, nombre="Persona Ficticia Dos")
    await db.close()
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)

    docs = c.get("/api/web/actas/documentos", headers=adm).json()["programas"]
    assert docs[0]["acta_propuesta"] == "001"
    abierta = c.get(f"/api/web/actas/actas-comite/{PROG}/abierta", headers=adm).json()
    assert abierta["numero_propuesto"] == "001" and abierta["caso_ids"] == [caso]

    base = f"/api/web/actas/actas-comite/{PROG}/cerrar"
    pedido = {"numero": "004", "fecha_sesion": "2026-11-05", "caso_ids": [caso]}
    assert c.post(base, json=pedido, headers=adm).status_code == 400
    malo = {**pedido, "numero": "cuatro", "confirmo": True}
    assert c.post(base, json=malo, headers=adm).status_code == 422
    comite = await _token("comite@unal.edu.co", "comite", DIR)
    assert (
        c.post(base, json={**pedido, "confirmo": True}, headers=comite).status_code
        == 403
    )

    r = c.post(base, json={**pedido, "confirmo": True}, headers=adm)
    assert r.status_code == 200, r.text
    hecha = r.json()
    assert hecha["numero"] == "004" and hecha["acta_siguiente"] == "005"
    # Doble clic: ya no hay casos que cerrar.
    assert (
        c.post(base, json={**pedido, "confirmo": True}, headers=adm).status_code == 409
    )

    [fila] = c.get("/api/web/actas/actas-comite", headers=adm).json()["actas"]
    assert fila["numero"] == "004" and fila["caso_ids"] == [caso]
    [archivo] = fila["archivos"]
    r = c.get("/api/web" + archivo["ruta"], headers=adm)
    assert r.status_code == 200
    db = await connect()
    guardada = await actas_comite.obtener(db, fila["id"])
    await db.close()
    assert guardada and hashlib.sha256(r.content).hexdigest() == guardada.docx_sha256

    otra = await _token("otra@unal.edu.co", "administrativa", "ciencias_naturales")
    assert c.get("/api/web" + archivo["ruta"], headers=otra).status_code == 404
    assert c.get("/api/web/actas/actas-comite", headers=otra).json()["actas"] == []


async def test_bot_cerrar_acta_anuncia_la_siguiente(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _registrar_matematicas(db, monkeypatch)
    caso = await _caso(db, chat_id=USUARIO)
    await bot.manejar_update(db, _update(text="/cerrar_acta"))
    [[boton]] = tg.mensajes[-1]["botones"]
    assert boton["text"].endswith("acta 001")
    assert boton["callback_data"] == f"cerrar:{PROG}:1"
    await bot.manejar_update(db, _callback(boton["callback_data"]))
    assert "Cerré el acta 001" in tg.textos()[-1]
    assert "La siguiente acta es la 002" in tg.textos()[-1]
    [acta] = await actas_comite.de_la_direccion(db, DIR)
    assert acta.caso_ids == [caso] and acta.canal == "telegram"
    # Un segundo toque no cierra otra acta.
    await bot.manejar_update(db, _callback(boton["callback_data"]))
    assert len(await actas_comite.de_la_direccion(db, DIR)) == 1
