"""Comité único de los posgrados de Ciencias Exactas: una sola acta para todos
sus programas, con consecutivo de la dirección (sigue a la 029), el encabezado
del acta real y la firma del director (app/core/programas.py, COMITES).

Los integrantes y el cargo son institucionales y públicos; los estudiantes y la
imagen de firma son ficticios.
"""

from __future__ import annotations

from datetime import date

import aiosqlite
import pytest

from app.core.programas import (
    COMITES,
    DIRECCIONES,
    PROGRAMAS,
    comite_de,
    comites_de,
    integrantes_con_nombre,
    programas_de,
)
from app.db.session import connect
from app.services import actas_comite, borrador, bot, firma, firmas
from app.services.documento import DatosOficio, construir_acta
from app.services.drive import archivo
from tests.conftest import TelegramFalso, png_bytes
from tests.test_bot import _callback, _update
from tests.test_firma import _caso, _imagenes, _texto
from tests.test_firma import carpeta_firmas as carpeta_firmas  # noqa: F401
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

POS = "posgrados_matematicas"
HOY = date(2026, 11, 10)
SESION = firma.DatosSesion("030", date(2026, 11, 10), "2:00 p. m.", "Sala ficticia")
RADICADO = "Mz.FCEN.1.067-001-26"  # ficticio


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch: pytest.MonkeyPatch) -> None:
    # La última acta conocida es de 2026: las pruebas corren en ese año.
    monkeypatch.setattr(firma, "hoy_local", lambda: HOY)


async def _tres_casos(db: aiosqlite.Connection, chat_id: int = 0) -> list[int]:
    """Casos de tres programas distintos del área de posgrados."""
    return [
        await _caso(
            db, programa=programa, direccion=POS, chat_id=chat_id, nombre=nombre
        )
        for programa, nombre in (
            ("esp_actuaria", "Persona Ficticia Uno"),
            ("mecen", "Persona Ficticia Dos"),
            ("dcm", "Persona Ficticia Tres"),
        )
    ]


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


def test_nombres_oficiales_y_claves_internas() -> None:
    direccion = DIRECCIONES[POS]
    assert direccion.nombre == "Área Curricular de Posgrados de Ciencias Exactas"
    assert direccion.comite_unico
    assert PROGRAMAS["esp_actuaria"].nombre == "Especialización en Actuaría y Finanzas"
    # Pregrado sigue con un comité por programa.
    assert not DIRECCIONES["matematicas"].comite_unico
    assert comites_de("matematicas") == programas_de("matematicas")
    assert comite_de("estadistica") == PROGRAMAS["estadistica"]


def test_un_comite_para_todos_los_programas_del_area() -> None:
    comite = COMITES[POS]
    assert comites_de(POS) == [comite]
    assert set(comite.programas) == {
        "esp_actuaria",
        "esp_estadistica",
        "mecen",
        "mcma",
        "dcm",
    }
    assert all(comite_de(p) == comite for p in comite.programas)
    assert comite_de(POS) == comite
    assert comite.comite == (
        "Comité Asesor de Posgrados del Área Curricular de Ciencias Exactas"
    )
    assert comite.nivel == "posgrado"
    assert comite.ultima_acta is not None and comite.ultima_acta.numero == 29
    # El comité no es un programa: no se elige como programa de un caso.
    assert POS not in PROGRAMAS


def test_integrantes_y_firmante() -> None:
    comite = COMITES[POS]
    director = comite.miembros[0]
    assert director.nombre == "David Leonardo Ocampo Rodríguez"
    assert director.cargo_bajo_firma == (
        "Director Área Curricular Posgrados Ciencias Exactas Naturales"
    )
    assert firma.firmante_de(comite) == director
    nubia = next(m for m in comite.miembros if m.nombre == "Nubia Esteban Duarte")
    assert nubia.tratamiento == "La profesora"
    assert len(comite.miembros) == 6
    # El director también coordina Actuaría y Finanzas: un solo botón de concepto.
    nombres = [m.nombre for m in integrantes_con_nombre(comite)]
    assert len(nombres) == 5 and len(set(nombres)) == 5
    assert [m.nombre for m in integrantes_con_nombre(comite_de("mcma"))] == nombres


# ---------------------------------------------------------------------------
# Acta y firma
# ---------------------------------------------------------------------------


async def test_acta_unica_con_casos_de_varios_programas(
    db: aiosqlite.Connection,
) -> None:
    firmas.guardar_firma(POS, png_bytes())
    casos = await _tres_casos(db)

    prep = await firma.preparar(db, direccion=POS, clave=POS, hoy=HOY)
    assert prep.programa == COMITES[POS]
    assert sorted(prep.caso_ids) == sorted(casos)
    assert prep.numero_acta_propuesto == "030"  # sigue a la 029
    assert prep.tiene_imagen and prep.bloqueos == []
    # Desde cualquiera de sus programas se llega al mismo comité.
    desde_mcma = await firma.preparar(db, direccion=POS, clave="mcma", hoy=HOY)
    assert desde_mcma.programa.clave == POS

    hecha = await firma.firmar(
        db,
        direccion=POS,
        clave=POS,
        radicado=RADICADO,
        sesion=SESION,
        caso_ids=prep.caso_ids,
        persona="Persona Administrativa",
        rol=firma.flujo.ADMINISTRATIVA,
        canal="web",
        hoy=HOY,
    )
    assert hecha.programa == POS and sorted(hecha.caso_ids) == sorted(casos)
    assert hecha.firmante == "David Leonardo Ocampo Rodríguez" and hecha.con_imagen

    acta_docx = firma.leer_verificado(hecha.archivo("acta", "docx"))  # type: ignore[arg-type]
    texto = _texto(acta_docx)
    for linea in (
        "UNIVERSIDAD NACIONAL DE COLOMBIA",
        "SEDE MANIZALES",
        "COMITÉ ASESOR DE POSGRADOS DEL ÁREA CURRICULAR DE CIENCIAS EXACTAS",
        "ACTA-030",
    ):
        assert linea in texto.splitlines()
    assert "PREGRADO" not in texto
    assert "COMITÉ ASESOR PROGRAMA CURRICULAR" not in texto
    assert (
        "Profesor DAVID LEONARDO OCAMPO RODRÍGUEZ, en calidad de Director de Área "
        "Curricular Posgrados del Área de Ciencias Exactas;"
    ) in texto
    assert (
        "Profesora NUBIA ESTEBAN DUARTE, en calidad de coordinadora de la "
        "Especialización en Estadística;"
    ) in texto
    assert (
        "Profesor SIMEÓN CASANOVA TRUJILLO, en calidad de miembro del personal "
        "académico de la respectiva área."
    ) in texto
    # Cada caso dice de qué programa es.
    assert "Persona Ficticia Uno (Especialización en Actuaría y Finanzas)" in texto
    assert "estudiante del Doctorado en Ciencias - Matemáticas" in texto
    # Firma: imagen del comité, nombre y cargo oficial.
    lineas = texto.splitlines()
    i = lineas.index("DAVID LEONARDO OCAMPO RODRÍGUEZ")
    assert lineas[i + 1] == (
        "Director Área Curricular Posgrados Ciencias Exactas Naturales"
    )
    assert _imagenes(acta_docx) == 1

    oficio = _texto(firma.leer_verificado(hecha.archivo("oficio", "docx")))  # type: ignore[arg-type]
    assert (
        "Asunto: Comité Asesor de Posgrados del Área Curricular de Ciencias Exactas "
        "Acta 030 de 2026"
    ) in oficio
    assert "estudiante de la Maestría en Enseñanza de las Ciencias Exactas" in oficio

    [acta] = await actas_comite.de_la_direccion(db, POS)
    assert acta.programa == POS and acta.numero == 30
    assert await actas_comite.proponer_numero(db, POS, 2026) == 31


async def test_consecutivo_desde_la_029(db: aiosqlite.Connection) -> None:
    await _tres_casos(db)
    assert await actas_comite.proponer_numero(db, POS, 2026) == 30
    # Otro año no hereda la 029.
    assert await actas_comite.proponer_numero(db, POS, 2027) == 1
    # Un número ya usado por fuera de MemorIA no se puede cerrar.
    acta = await actas_comite.abierta(db, direccion=POS, clave=POS, hoy=HOY)
    assert acta.numero_propuesto == 30 and len(acta.casos) == 3
    for usado in (29, 12):
        with pytest.raises(actas_comite.ActaNoPermitida, match="029"):
            await actas_comite.cerrar_sin_firma(
                db,
                direccion=POS,
                clave=POS,
                numero=usado,
                fecha_sesion=HOY,
                caso_ids=acta.caso_ids,
                persona="x",
                rol=firma.flujo.ADMINISTRATIVA,
                canal="web",
                hoy=HOY,
            )
    cerrada = await actas_comite.cerrar_sin_firma(
        db,
        direccion=POS,
        clave="dcm",  # un programa del área: cierra el acta de todo el comité
        numero=30,
        fecha_sesion=HOY,
        caso_ids=acta.caso_ids,
        persona="x",
        rol=firma.flujo.ADMINISTRATIVA,
        canal="web",
        hoy=HOY,
    )
    assert cerrada.programa == POS and len(cerrada.caso_ids) == 3
    assert (
        cerrada.docx_ruta and cerrada.docx_ruta.name == "Acta_030_2026_" + POS + ".docx"
    )
    assert await actas_comite.proponer_numero(db, POS, 2026) == 31


async def test_sin_imagen_avisa_con_la_clave_del_comite(
    db: aiosqlite.Connection,
) -> None:
    firmas.guardar_firma("matematicas", png_bytes())  # la del pregrado no sirve
    await _tres_casos(db)
    prep = await firma.preparar(db, direccion=POS, clave=POS, hoy=HOY)
    assert not prep.tiene_imagen
    assert any(f"({POS})" in a for a in prep.avisos)


async def test_un_solo_borrador_para_la_direccion(db: aiosqlite.Connection) -> None:
    await _tres_casos(db)
    borradores, sin_programa = await borrador.armar_borradores(
        db, direccion=POS, elaboro="Persona Administrativa", solo_con_cambios=False
    )
    assert sin_programa == []
    [uno] = borradores
    assert uno.programa.clave == POS and len(uno.caso_ids) == 3
    assert "[la firma se agrega al firmar]" in _texto(uno.acta.docx)


def test_pregrado_conserva_su_encabezado() -> None:
    texto = _texto(
        construir_acta(
            DatosOficio(
                programa=PROGRAMAS["estadistica"],
                fecha=HOY,
                casos=[],
                numero_acta="019",
                miembros=PROGRAMAS["estadistica"].miembros,
            ),
            "2026-2S",
        )
    )
    assert "COMITÉ ASESOR PROGRAMA CURRICULAR ESTADÍSTICA" in texto
    assert "ACTA 019 DE 2026" in texto and "PREGRADO" in texto
    assert "Nubia Esteban Duarte, Coordinadora programa curricular" in texto


# ---------------------------------------------------------------------------
# Bot, web y Drive
# ---------------------------------------------------------------------------


async def test_bot_firmar_ofrece_un_solo_comite(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_bot import USUARIO
    from tests.test_firma import _respuesta

    monkeypatch.setattr(bot.settings, "invite_code", "CLAVE")
    await bot.manejar_update(db, _update(text="/start CLAVE"))
    await bot.manejar_update(db, _callback(f"dir:{POS}"))
    await _tres_casos(db, chat_id=USUARIO)

    await bot.manejar_update(db, _update(text="/firmar"))
    assert tg.mensajes[-1]["botones"] == [
        [{"text": "Firmar Comité de posgrados", "callback_data": f"fir:{POS}"}]
    ]
    await bot.manejar_update(db, _update(text="/firmar mecen"))
    resumen, pedido = tg.mensajes[-2]["texto"], tg.mensajes[-1]["texto"]
    assert "Comité Asesor de Posgrados del Área Curricular" in resumen
    assert "Director Área Curricular Posgrados Ciencias Exactas Naturales" in resumen
    assert "(Especialización en Actuaría y Finanzas)" in resumen
    assert "Acta: 030" in pedido and f"({POS})" in pedido

    await bot.manejar_update(db, _update(text="/cerrar_acta"))
    assert tg.mensajes[-1]["botones"] == [
        [
            {
                "text": "Cerrar Comité de posgrados · acta 030",
                "callback_data": f"cerrar:{POS}:30",
            }
        ]
    ]
    assert _respuesta  # el flujo de datos es el mismo de pregrado (test_firma)


async def test_web_documentos_y_firma(cliente: Cliente) -> None:  # noqa: F811
    db = await connect()
    await _tres_casos(db)
    await db.close()
    c = cliente("actas")
    adm = await _token("pos.ficticia@unal.edu.co", "administrativa", POS)

    datos = c.get("/api/web/actas/documentos", headers=adm).json()
    [comite] = datos["programas"]
    assert comite["clave"] == POS and comite["acta_propuesta"] == "030"
    assert comite["casos"] == 3 and comite["con_recomendacion"] == 3
    assert "Especialización en Actuaría y Finanzas" in comite["programas"]
    assert comite["comite"].startswith("Comité Asesor de Posgrados")

    r = c.get(f"/api/web/actas/documentos/{POS}/acta", headers=adm)
    assert r.status_code == 200, r.text

    prep = c.get(f"/api/web/actas/firmar/{POS}", headers=adm).json()
    assert prep["numero_acta_propuesto"] == "030"
    assert prep["firmante"]["cargo"] == (
        "Director Área Curricular Posgrados Ciencias Exactas Naturales"
    )
    assert {x["programa"] for x in prep["casos"]} == {
        "Especialización en Actuaría y Finanzas",
        "Maestría en Enseñanza de las Ciencias Exactas y Naturales",
        "Doctorado en Ciencias - Matemáticas",
    }


def test_drive_archiva_el_acta_en_la_carpeta_del_comite() -> None:
    doc = archivo.Documento(
        tipo="acta",
        numero="030",
        fecha=HOY,
        programa=POS,
        contenido=b"%PDF-",
        archivado_por="x",
    )
    assert archivo.ruta(doc) == [
        archivo.CARPETA_TIPO["acta"],
        "2026",
        "Posgrados de Ciencias Exactas",
        "Comité Asesor de Posgrados del Área Curricular de Ciencias Exactas",
    ]
    assert archivo.nombre_archivo(doc) == f"Acta_030_{POS}_20261110.pdf"
    # El oficio de un caso sigue en la carpeta de su programa.
    oficio = archivo.Documento(
        tipo="oficio",
        numero="1",
        fecha=HOY,
        programa="mcma",
        contenido=b"%PDF-",
        archivado_por="x",
    )
    assert archivo.ruta(oficio)[-1] == PROGRAMAS["mcma"].nombre
