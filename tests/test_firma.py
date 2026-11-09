"""Firma del oficio y del acta de un programa (app/services/firma.py).

Datos ficticios y una imagen de firma generada en la prueba: las firmas reales
nunca entran al repositorio.
"""

from __future__ import annotations

import hashlib
import io
from datetime import date
from pathlib import Path

import aiosqlite
import pytest
from docx import Document

from app.core.config import settings
from app.db import repo
from app.db.session import connect
from app.schemas.caso import EstadoCaso, Sentido
from app.services import bot, firma, firmas, flujo
from app.services.flujo import Accion, Etapa
from tests.conftest import TelegramFalso, extraccion_ejemplo, png_bytes
from tests.test_bot import USUARIO, _callback, _update
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

HOY = date(2026, 11, 9)
DIR = "matematicas"
PROG = "ciencias_computacion"
ADM = flujo.ADMINISTRATIVA


@pytest.fixture(autouse=True)
def carpeta_firmas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    carpeta = tmp_path / "firmas"
    monkeypatch.setattr(settings, "firmas_dir", carpeta)
    return carpeta


def _con_imagen() -> None:
    firmas.guardar_firma(PROG, png_bytes())


async def _caso(
    db: aiosqlite.Connection,
    sentido: Sentido = Sentido.APROBAR,
    *,
    programa: str = PROG,
    direccion: str = DIR,
    chat_id: int = 0,
    nombre: str = "Persona Ficticia Uno",
) -> int:
    """Un caso leído del programa, con la recomendación del comité."""
    caso = await repo.crear_caso(
        db, chat_id=chat_id, user_id=chat_id, direccion=direccion, canal="web"
    )
    await repo.guardar_extraccion(
        db, caso, extraccion_ejemplo(nombre_estudiante=nombre), programa
    )
    await flujo.lectura_lista(db, caso)
    if sentido != Sentido.PENDIENTE:
        await flujo.recomendar(db, caso, sentido, rol=ADM, persona="Adm", canal="web")
    return caso


SESION = firma.DatosSesion("019", date(2026, 11, 5), "10:00 a. m.", "Sala ficticia")


def _texto(docx: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(docx)).paragraphs)


def _imagenes(docx: bytes) -> int:
    return len(Document(io.BytesIO(docx)).inline_shapes)


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


async def test_resumen_firma_y_registro(db: aiosqlite.Connection) -> None:
    _con_imagen()
    aprobado = await _caso(db, Sentido.APROBAR)
    no_aprobado = await _caso(db, Sentido.NO_APROBAR, nombre="Persona Ficticia Dos")
    pendiente = await _caso(db, Sentido.PENDIENTE, nombre="Persona Ficticia Tres")

    prep = await firma.preparar(db, direccion=DIR, clave=PROG, hoy=HOY)
    assert prep.caso_ids == [aprobado, no_aprobado]
    assert [c.id for c in prep.pendientes] == [pendiente]
    assert prep.firmante and prep.firmante.nombre == "Fabián Fernando Serrano Suarez"
    assert prep.tiene_imagen and not prep.bloqueos
    assert prep.radicado_propuesto == "Mz.FCEN.1.065-001-26"
    assert any(f"#{pendiente}" in a for a in prep.avisos)
    assert any("LibreOffice" in a for a in prep.avisos)

    hecha = await firma.firmar(
        db,
        direccion=DIR,
        clave=PROG,
        radicado="mz.fcen.1.065-1-26",
        sesion=SESION,
        caso_ids=prep.caso_ids,
        persona="Persona Administrativa",
        rol=ADM,
        canal="web",
        hoy=HOY,
    )
    assert hecha.radicado == "Mz.FCEN.1.065-001-26"
    assert hecha.firmante == "Fabián Fernando Serrano Suarez"
    assert hecha.firmado_por == "Persona Administrativa" and hecha.con_imagen
    assert hecha.caso_ids == [aprobado, no_aprobado] and hecha.firmado
    # Sin LibreOffice en las pruebas: solo los .docx, cada uno con su hash.
    assert {(a.documento, a.formato) for a in hecha.archivos} == {
        ("oficio", "docx"),
        ("acta", "docx"),
    }
    for a in hecha.archivos:
        assert a.sha256 == hashlib.sha256(a.ruta.read_bytes()).hexdigest()
        assert firma.leer_verificado(a) == a.ruta.read_bytes()

    oficio = hecha.archivo("oficio", "docx")
    acta = hecha.archivo("acta", "docx")
    assert oficio and acta
    texto_oficio = _texto(oficio.ruta.read_bytes())
    assert "BORRADOR" not in texto_oficio
    assert "[MZ.FCEN.1.065-001-26]" in texto_oficio
    assert (
        "Acta 019 de 2026" in texto_oficio and "05 de noviembre de 2026" in texto_oficio
    )
    assert "FABIÁN FERNANDO SERRANO SUAREZ" in texto_oficio
    assert _imagenes(oficio.ruta.read_bytes()) == 1
    texto_acta = _texto(acta.ruta.read_bytes())
    assert "ACTA 019 DE 2026" in texto_acta
    assert "10:00 a. m." in texto_acta and "Sala ficticia" in texto_acta
    assert "Persona Ficticia Tres" not in texto_acta  # el pendiente no entra
    assert _imagenes(acta.ruta.read_bytes()) == 1

    # Registro en la base.
    guardada = await firma.obtener(db, hecha.id)
    assert guardada == hecha
    assert [f.id for f in await firma.de_la_direccion(db, DIR)] == [hecha.id]
    assert await firma.de_la_direccion(db, "ciencias_naturales") == []

    # Los casos firmados pasan al Consejo y salen del borrador; el pendiente no.
    for caso_id in (aprobado, no_aprobado):
        caso = await repo.get_caso(db, caso_id)
        assert caso and caso.estado == EstadoCaso.CERRADO
        assert caso.etapa == Etapa.EN_CONSEJO
        ultimo = (await flujo.eventos(db, caso_id))[-1]
        assert ultimo.accion == Accion.ENVIAR_CONSEJO
        assert ultimo.persona == "Persona Administrativa"
        assert "Mz.FCEN.1.065-001-26" in (ultimo.detalle or "")
    caso = await repo.get_caso(db, pendiente)
    assert caso and caso.estado == EstadoCaso.LISTO

    # El siguiente radicado de la dirección; el mismo no se puede volver a usar.
    assert await firma.proponer_radicado(db, prep.programa, HOY) == (
        "Mz.FCEN.1.065-002-26"
    )
    otro = await _caso(db, nombre="Persona Ficticia Cuatro")
    with pytest.raises(firma.FirmaNoPermitida, match="ya se usó"):
        await firma.firmar(
            db,
            direccion=DIR,
            clave=PROG,
            radicado="Mz.FCEN.1.065-001-26",
            sesion=SESION,
            caso_ids=[otro],
            persona="x",
            rol=ADM,
            canal="web",
            hoy=HOY,
        )


async def test_el_consejo_decide_despues_de_la_firma(db: aiosqlite.Connection) -> None:
    """La firma no rompe la línea: el caso en el Consejo sigue su camino."""
    caso = await _caso(db)
    await firma.firmar(
        db,
        direccion=DIR,
        clave=PROG,
        radicado="Mz.FCEN.1.065-007-26",
        sesion=SESION,
        caso_ids=[caso],
        persona="Adm",
        rol=ADM,
        canal="web",
        hoy=HOY,
    )
    assert flujo.puede(Accion.DECIDIR, Etapa.EN_CONSEJO, ADM)
    assert flujo.puede(Accion.VOLVER_AL_COMITE, Etapa.EN_CONSEJO, ADM)
    # El rol «comite» nunca firma ni hace transiciones.
    with pytest.raises(flujo.TransicionNoPermitida):
        await flujo.transicionar(
            db, caso, Accion.ENVIAR_CONSEJO, rol="comite", persona="x", canal="web"
        )


async def test_sin_imagen_de_firma_avisa_y_marca_en_amarillo(
    db: aiosqlite.Connection,
) -> None:
    caso = await _caso(db)
    prep = await firma.preparar(db, direccion=DIR, clave=PROG, hoy=HOY)
    assert not prep.tiene_imagen
    assert any("Falta la imagen de firma" in a for a in prep.avisos)
    hecha = await firma.firmar(
        db,
        direccion=DIR,
        clave=PROG,
        radicado="Mz.FCEN.1.065-010-26",
        sesion=SESION,
        caso_ids=[caso],
        persona="Adm",
        rol=ADM,
        canal="telegram",
        hoy=HOY,
    )
    assert not hecha.con_imagen
    oficio = hecha.archivo("oficio", "docx")
    assert oficio and "[falta la imagen de la firma]" in _texto(
        oficio.ruta.read_bytes()
    )


async def test_bloqueos(db: aiosqlite.Connection) -> None:
    # Sin casos con recomendación.
    await _caso(db, Sentido.PENDIENTE)
    prep = await firma.preparar(db, direccion=DIR, clave=PROG)
    assert prep.bloqueos and "recomendación" in prep.bloqueos[0]
    # Un programa sin integrantes del comité no tiene quién firme.
    await _caso(db, programa="ing_biologica", direccion="ciencias_naturales")
    prep = await firma.preparar(
        db, direccion="ciencias_naturales", clave="ing_biologica"
    )
    assert any("no sé quién firma" in b for b in prep.bloqueos)
    with pytest.raises(firma.FirmaNoPermitida, match="no sé quién firma"):
        await firma.firmar(
            db,
            direccion="ciencias_naturales",
            clave="ing_biologica",
            radicado="Mz.FCEN.1.066-001-26",
            sesion=SESION,
            caso_ids=prep.caso_ids,
            persona="x",
            rol=ADM,
            canal="web",
            hoy=HOY,
        )
    # Un programa de otra dirección no existe para esta persona.
    with pytest.raises(firma.FirmaNoPermitida):
        await firma.preparar(db, direccion="ciencias_naturales", clave=PROG)


async def test_no_firma_si_los_casos_cambiaron(db: aiosqlite.Connection) -> None:
    caso = await _caso(db)
    nuevo = await _caso(db, nombre="Persona Ficticia Dos")
    with pytest.raises(firma.FirmaNoPermitida, match="cambiaron"):
        await firma.firmar(
            db,
            direccion=DIR,
            clave=PROG,
            radicado="Mz.FCEN.1.065-001-26",
            sesion=SESION,
            caso_ids=[caso],  # el resumen no tenía el nuevo
            persona="x",
            rol=ADM,
            canal="web",
            hoy=HOY,
        )
    assert await firma.de_la_direccion(db, DIR) == []
    assert (await repo.get_caso(db, nuevo)).estado == EstadoCaso.LISTO  # type: ignore[union-attr]
    assert not list((settings.output_dir / "firmados").glob("**/*.docx"))


async def test_radicado_propuesto_sin_prefijo_del_programa(
    db: aiosqlite.Connection,
) -> None:
    from app.core.programas import PROGRAMAS

    matematicas = PROGRAMAS["matematicas"]
    assert matematicas.radicado_prefijo is None
    # Sin prefijo y sin firmas previas: la persona escribe el radicado entero.
    assert await firma.proponer_radicado(db, matematicas, HOY) is None
    # Con una firma previa de la dirección, se propone ese prefijo y el siguiente.
    caso = await _caso(db)
    await firma.firmar(
        db,
        direccion=DIR,
        clave=PROG,
        radicado="Mz.FCEN.1.065-041-26",
        sesion=SESION,
        caso_ids=[caso],
        persona="x",
        rol=ADM,
        canal="web",
        hoy=HOY,
    )
    assert await firma.proponer_radicado(db, matematicas, HOY) == (
        "Mz.FCEN.1.065-042-26"
    )
    # El consecutivo vuelve a empezar con el año.
    assert await firma.proponer_radicado(db, matematicas, date(2027, 1, 12)) == (
        "Mz.FCEN.1.065-001-27"
    )


def test_radicado_y_datos_de_la_sesion() -> None:
    assert firma.normalizar_radicado(" MZ.FCEN.1.065 - 12 - 26 ", HOY) == (
        "Mz.FCEN.1.065-012-26"
    )
    for malo in ("065-012-26", "Mz.FCEN.1.065-012", "Mz.FCEN.1.065-ABC-26", ""):
        with pytest.raises(ValueError, match="forma"):
            firma.normalizar_radicado(malo, HOY)
    with pytest.raises(ValueError, match="año"):
        firma.normalizar_radicado("Mz.FCEN.1.065-012-25", HOY)

    s = firma.validar_sesion(
        numero_acta=" 019 ",
        fecha_sesion="5/11/2026",
        hora="10 am",
        lugar="Sala",
        hoy=HOY,
    )
    assert s == firma.DatosSesion("019", date(2026, 11, 5), "10 am", "Sala")
    assert firma.leer_fecha("2026-11-05") == date(2026, 11, 5)
    with pytest.raises(ValueError, match="Falta: hora, lugar"):
        firma.validar_sesion(
            numero_acta="1", fecha_sesion="2026-11-05", hora="", lugar=" "
        )
    with pytest.raises(ValueError, match="AAAA-MM-DD"):
        firma.validar_sesion(numero_acta="1", fecha_sesion="ayer", hora="1", lugar="x")
    with pytest.raises(ValueError, match="posterior"):
        firma.validar_sesion(
            numero_acta="1", fecha_sesion="2026-11-10", hora="1", lugar="x", hoy=HOY
        )


def test_programa_por_nombre_solo_de_la_direccion() -> None:
    p = firma.programa_de_la_direccion("Ciencias de la Computación", DIR)
    assert p and p.clave == PROG
    assert firma.programa_de_la_direccion("estadistica", DIR)
    assert firma.programa_de_la_direccion("ing_fisica", DIR) is None
    assert firma.programa_de_la_direccion("", DIR) is None


# ---------------------------------------------------------------------------
# Bot: /firmar
# ---------------------------------------------------------------------------


async def _registrar_matematicas(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "invite_code", "CLAVE")
    await bot.manejar_update(db, _update(text="/start CLAVE"))
    await bot.manejar_update(db, _callback("dir:matematicas"))


def _respuesta(texto: str, pedido: str) -> object:
    return _update(
        text=texto,
        reply_to_message={
            "message_id": 99,
            "chat": {"id": USUARIO, "type": "private"},
            "text": pedido,
        },
    )


async def test_bot_firmar(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _registrar_matematicas(db, monkeypatch)
    _con_imagen()
    caso = await _caso(db, chat_id=USUARIO)
    pendiente = await _caso(
        db, Sentido.PENDIENTE, chat_id=USUARIO, nombre="Persona Ficticia Dos"
    )

    # Sin argumento: botones con los programas que tienen recomendaciones.
    await bot.manejar_update(db, _update(text="/firmar"))
    botones = tg.mensajes[-1]["botones"]
    assert botones == [
        [{"text": "Firmar Ciencias de la Computación", "callback_data": f"fir:{PROG}"}]
    ]

    # Resumen y pedido de datos con el radicado propuesto.
    await bot.manejar_update(db, _update(text="/firmar ciencias de la computacion"))
    resumen, pedido = tg.mensajes[-2]["texto"], tg.mensajes[-1]["texto"]
    assert "Serrano Suarez" in resumen and f"#{caso}" in resumen
    assert f"#{pendiente}" in resumen  # aviso: queda fuera
    anio = f"{firma.hoy_local():%y}"
    assert f"Mz.FCEN.1.065-001-{anio}" in pedido
    assert tg.mensajes[-1]["forzar_respuesta"] is True
    assert await firma.de_la_direccion(db, DIR) == []  # nada se firma aún

    # Datos con un error: se explica y no se guarda nada.
    await bot.manejar_update(db, _respuesta("Radicado: 12\nActa: 019", pedido))
    assert "forma" in tg.textos()[-1]
    assert await firma.leer_pendiente(db, USUARIO) is None

    # Datos completos: confirmación explícita con botones.
    datos = (
        f"Radicado: Mz.FCEN.1.065-003-{anio}\nActa: 019\nFecha: 05/11/2026\n"
        "Hora: 10:00 a. m.\nLugar: Sala ficticia"
    )
    await bot.manejar_update(db, _respuesta(datos, pedido))
    confirmar = tg.mensajes[-1]
    assert "¿Confirmas la firma?" in confirmar["texto"]
    assert confirmar["botones"][0][0]["callback_data"] == "fok"
    assert await firma.de_la_direccion(db, DIR) == []

    # Cancelar no firma.
    await bot.manejar_update(db, _callback("fno"))
    assert "No se firmó nada" in tg.textos()[-1]
    await bot.manejar_update(db, _callback("fok"))
    assert tg.callbacks[-1] == "No hay una firma pendiente."
    assert await firma.de_la_direccion(db, DIR) == []

    # Confirmar firma: llegan los documentos finales.
    await bot.manejar_update(db, _respuesta(datos, pedido))
    await bot.manejar_update(db, _callback("fok"))
    [hecha] = await firma.de_la_direccion(db, DIR)
    assert hecha.radicado == f"Mz.FCEN.1.065-003-{anio}"
    assert hecha.canal == "telegram" and hecha.firmado_por == "Ana Prueba"
    assert hecha.caso_ids == [caso]
    nombres = [d["nombre"] for d in tg.documentos]
    assert nombres == [a.ruta.name for a in hecha.archivos]
    assert all(
        d["contenido"] == a.ruta.read_bytes()
        for d, a in zip(tg.documentos, hecha.archivos, strict=True)
    )
    assert "Firmado" in tg.textos()[-1] and hecha.archivos[0].sha256 in tg.textos()[-1]
    assert (await repo.get_caso(db, caso)).etapa == Etapa.EN_CONSEJO  # type: ignore[union-attr]
    assert await firma.leer_pendiente(db, USUARIO) is None

    # Un segundo toque no vuelve a firmar.
    await bot.manejar_update(db, _callback("fok"))
    assert len(await firma.de_la_direccion(db, DIR)) == 1


async def test_bot_firmar_programa_de_otra_direccion(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _registrar_matematicas(db, monkeypatch)
    await bot.manejar_update(db, _update(text="/firmar ing_fisica"))
    assert "No conozco ese programa" in tg.textos()[-1]


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


async def test_web_firmar(cliente: Cliente) -> None:  # noqa: F811
    _con_imagen()
    db = await connect()
    caso = await _caso(db)
    await db.close()
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    base = f"/api/web/actas/firmar/{PROG}"

    r = c.get(base, headers=adm)
    assert r.status_code == 200, r.text
    prep = r.json()
    assert prep["caso_ids"] == [caso] and prep["tiene_imagen"]
    assert prep["firmante"]["nombre"] == "Fabián Fernando Serrano Suarez"
    anio = f"{firma.hoy_local():%y}"
    assert prep["radicado_propuesto"] == f"Mz.FCEN.1.065-001-{anio}"

    pedido = {
        "radicado": prep["radicado_propuesto"],
        "numero_acta": "019",
        "fecha_sesion": "2026-11-05",
        "hora": "10:00 a. m.",
        "lugar": "Sala ficticia",
        "caso_ids": prep["caso_ids"],
    }
    # Sin confirmación explícita no se firma.
    assert c.post(base, json=pedido, headers=adm).status_code == 400
    assert (
        c.post(
            base, json={**pedido, "hora": "", "confirmo": True}, headers=adm
        ).status_code
        == 422
    )
    assert (
        c.post(
            base, json={**pedido, "caso_ids": [], "confirmo": True}, headers=adm
        ).status_code
        == 409
    )

    # El comité no firma.
    comite = await _token("comite@unal.edu.co", "comite", DIR)
    assert c.get(base, headers=comite).status_code == 403
    assert (
        c.post(base, json={**pedido, "confirmo": True}, headers=comite).status_code
        == 403
    )

    r = c.post(base, json={**pedido, "confirmo": True}, headers=adm)
    assert r.status_code == 200, r.text
    hecha = r.json()
    assert hecha["radicado"] == pedido["radicado"] and hecha["canal"] == "web"
    assert hecha["firmado_por"] == "adm@unal.edu.co" and hecha["caso_ids"] == [caso]

    lista = c.get("/api/web/actas/firmas", headers=adm).json()["firmas"]
    assert [f["id"] for f in lista] == [hecha["id"]]
    oficio = next(a for a in hecha["archivos"] if a["documento"] == "oficio")
    ruta = f"/api/web/actas/firmas/{hecha['id']}/oficio/docx"
    r = c.get(ruta, headers=adm)
    assert r.status_code == 200
    assert hashlib.sha256(r.content).hexdigest() == oficio["sha256"]
    assert (
        c.get(
            f"/api/web/actas/firmas/{hecha['id']}/oficio/pdf", headers=adm
        ).status_code
        == 404
    )

    # Otra dirección no ve la firma; un archivo alterado no se entrega.
    otra = await _token("otra@unal.edu.co", "administrativa", "ciencias_naturales")
    assert c.get(ruta, headers=otra).status_code == 404
    assert c.get("/api/web/actas/firmas", headers=otra).json()["firmas"] == []
    db = await connect()
    guardada = await firma.obtener(db, hecha["id"])
    await db.close()
    assert guardada
    archivo = guardada.archivo("oficio", "docx")
    assert archivo
    archivo.ruta.write_bytes(archivo.ruta.read_bytes() + b"x")
    assert c.get(ruta, headers=adm).status_code == 409


async def test_web_admin_de_su_direccion_firma(cliente: Cliente) -> None:  # noqa: F811
    db = await connect()
    caso = await _caso(db)
    await db.close()
    c = cliente("actas")
    base = f"/api/web/actas/firmar/{PROG}"
    # Admin sin dirección no firma; con dirección, sí (de la suya).
    sin = await _token("admin@unal.edu.co", "admin")
    assert c.get(base, headers=sin).status_code == 403
    admin = await _token("admin2@unal.edu.co", "admin", DIR)
    prep = c.get(base, headers=admin).json()
    r = c.post(
        base,
        json={
            "radicado": prep["radicado_propuesto"],
            "numero_acta": "020",
            "fecha_sesion": "2026-11-05",
            "hora": "3:00 p. m.",
            "lugar": "Sesión ad referéndum",
            "caso_ids": [caso],
            "confirmo": True,
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "admin"
    db = await connect()
    ultimo = (await flujo.eventos(db, caso))[-1]
    await db.close()
    assert ultimo.accion == Accion.ENVIAR_CONSEJO and ultimo.rol == flujo.ADMIN
