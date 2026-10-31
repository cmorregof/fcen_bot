"""Buscador, verificador y boletín de punta a punta, sin red y sin modelo real."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.conexion import Conexion
from app.servicios.oportunidades import almacen, boletin, buscador, fuentes, verificador
from app.servicios.oportunidades.config import RAIZ, config
from app.servicios.oportunidades.db import init_oportunidades
from app.servicios.oportunidades.texto import a_texto, clave_url, sin_contactos
from app.servicios.oportunidades.transporte import Bloqueado
from tests.oportunidades.conftest import (
    HOY,
    LectorFalso,
    TransporteFalso,
    cortes,
    dia,
    leida,
    ofertas_alfa,
)


async def _correr(
    db: Conexion, lector: LectorFalso | None, t: TransporteFalso | None = None
) -> dict[str, object]:
    await init_oportunidades(db)
    corrida = await buscador.iniciar(db, "prueba")
    return await buscador.correr(
        db, corrida, cortes=cortes(t or TransporteFalso()), lector=lector, hoy=HOY
    )


# ---------------------------------------------------------------------------
# Fuentes y texto
# ---------------------------------------------------------------------------


def test_lista_real_de_fuentes_valida_y_apagada() -> None:
    """config/oportunidades.yaml carga y nada se consulta sin aprobación."""
    lista = fuentes.cargar(RAIZ / "config" / "oportunidades.yaml")
    assert lista.fuentes
    assert all(not f.activa for f in lista.fuentes)
    assert all(f.justificacion for f in lista.fuentes)
    assert lista.excluidas


def test_fuente_con_programa_desconocido_no_carga(tmp_path: Path) -> None:
    ruta = tmp_path / "f.yaml"
    ruta.write_text(
        "fuentes:\n  - {clave: x, nombre: X, url: 'https://x.invalid', "
        "programas: [no_existe]}\n"
    )
    with pytest.raises(ValueError, match="no_existe"):
        fuentes.cargar(ruta)


def test_html_a_texto_conserva_enlaces_y_omite_scripts() -> None:
    texto, enlaces = a_texto(
        '<script>malo()</script><p><a href="/o/1#x">Oferta</a></p>'
        '<a href="mailto:a@b.invalid">correo</a>',
        "https://alfa.invalid/lista",
    )
    assert "malo" not in texto
    assert "Oferta <https://alfa.invalid/o/1>" in texto
    assert enlaces == {"https://alfa.invalid/o/1"}


def test_sin_contactos_quita_correos_y_telefonos_pero_no_cifras() -> None:
    limpio = sin_contactos(
        "Escriba a persona@ejemplo.invalid o al 300 123 4567 o (606) 887 0000. "
        "Salario $ 2.500.000. Cierra 2026-11-30. NIT 900123456."
    )
    assert "@" not in limpio and "300 123" not in limpio and "887 0000" not in limpio
    assert "2.500.000" in limpio and "2026-11-30" in limpio


def test_clave_url_ignora_www_barra_y_rastreo() -> None:
    assert clave_url("https://www.alfa.invalid/o/1/?utm_source=x&b=2") == clave_url(
        "http://alfa.invalid/o/1?b=2"
    )


# ---------------------------------------------------------------------------
# Transporte respetuoso
# ---------------------------------------------------------------------------


async def test_robots_prohibe_y_no_se_pide_la_pagina() -> None:
    t = TransporteFalso()
    with pytest.raises(Bloqueado, match="robots"):
        await cortes(t).obtener("https://beta.invalid/empleos")
    assert t.pedidos == ["https://beta.invalid/robots.txt"]


async def test_robots_que_falla_bloquea_el_sitio() -> None:
    t = TransporteFalso({"https://caido.invalid/robots.txt": (503, "")})
    with pytest.raises(Bloqueado):
        await cortes(t).obtener("https://caido.invalid/x")
    assert "https://caido.invalid/x" not in t.pedidos


async def test_403_no_se_reintenta() -> None:
    t = TransporteFalso()
    with pytest.raises(Bloqueado, match="403"):
        await cortes(t).obtener("https://gamma.invalid/")
    assert t.pedidos.count("https://gamma.invalid/") == 1


async def test_robots_se_lee_una_vez_por_sitio() -> None:
    t = TransporteFalso()
    c = cortes(t)
    await c.obtener("https://alfa.invalid/ofertas")
    await c.obtener("https://alfa.invalid/ofertas/101")
    assert t.pedidos.count("https://alfa.invalid/robots.txt") == 1


# ---------------------------------------------------------------------------
# Vigía completa
# ---------------------------------------------------------------------------


async def test_vigia_busca_verifica_y_deja_la_cola(
    db: Conexion, fuentes_falsas: Path
) -> None:
    lector = LectorFalso({"portal_alfa": ofertas_alfa()})
    r = await _correr(db, lector)

    estados = {f["clave"]: f["estado"] for f in r["fuentes"]}  # type: ignore[attr-defined]
    assert estados == {
        "portal_alfa": "ok",
        "portal_beta": "bloqueada",
        "portal_gamma": "bloqueada",
    }
    assert lector.lecturas == ["portal_alfa"]  # la apagada ni se mira
    assert "var x" not in lector.textos[0]
    assert r["nuevas"] == 4 and r["verificadas"] == 1 and r["en_revision"] == 3

    ofertas = {o["titulo"]: o for o in await almacen.listar(db)}
    buena = ofertas["Practicante de estadística"]
    assert buena["estado"] == "verificada"
    assert buena["verificado_por"] == almacen.SISTEMA
    # Sin datos de contacto de personas.
    assert "@" not in buena["resumen"]

    analista = ofertas["Analista junior"]
    assert analista["estado"] == "encontrada"
    assert analista["programas"] == ["ciencias_computacion"]
    assert any("no son de la FCEN" in m for m in analista["motivos"])

    vencida = ofertas["Pasantía vencida"]
    assert any(m.startswith("cierre: cerró") for m in vencida["motivos"])
    assert any(m.startswith("enlace_vivo") for m in vencida["motivos"])

    inventada = ofertas["Beca inventada"]
    assert inventada["url"] == "https://alfa.invalid/ofertas"
    assert any("no está en la página" in m for m in inventada["motivos"])

    # El verificador nunca aprueba ni publica.
    assert not [o for o in ofertas.values() if o["estado"] in ("aprobada", "publicada")]
    # El borrador del boletín existe pero está vacío: nadie aprobó nada aún.
    assert r["boletin"]["ofertas"] == 0  # type: ignore[index]


async def test_segunda_vigia_no_duplica(db: Conexion, fuentes_falsas: Path) -> None:
    lector = LectorFalso({"portal_alfa": ofertas_alfa()})
    await _correr(db, lector)
    r = await _correr(db, lector)
    assert r["nuevas"] == 0
    assert len(await almacen.listar(db)) == 4


async def test_duplicado_por_entidad_y_titulo(
    db: Conexion, fuentes_falsas: Path
) -> None:
    repetida = leida(url="https://alfa.invalid/ofertas/102")  # otro enlace
    await _correr(db, LectorFalso({"portal_alfa": [leida(), repetida]}))
    ofertas = await almacen.listar(db)
    primera, segunda = sorted(ofertas, key=lambda o: o["id"])
    assert primera["estado"] == "verificada"
    assert any("duplicado" in m for m in segunda["motivos"])


async def test_sin_api_key_no_busca(db: Conexion, fuentes_falsas: Path) -> None:
    r = await _correr(db, None)
    assert {f["estado"] for f in r["fuentes"]} == {"omitida"}  # type: ignore[attr-defined]
    assert r["nuevas"] == 0


async def test_tope_de_gasto_corta_la_corrida(
    db: Conexion, fuentes_falsas: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "tope_usd_corrida", 0.01)
    lector = LectorFalso({"portal_alfa": []}, tokens_in=100_000)
    r = await _correr(db, lector)
    estados = [f["estado"] for f in r["fuentes"]]  # type: ignore[attr-defined]
    assert estados == ["ok", "tope", "tope"]
    assert r["costo_usd"] == pytest.approx(0.215)


async def test_no_corren_dos_vigias_a_la_vez(db: Conexion) -> None:
    await init_oportunidades(db)
    await buscador.iniciar(db, "una")
    with pytest.raises(buscador.CorridaEnCurso):
        await buscador.iniciar(db, "otra")


# ---------------------------------------------------------------------------
# Revisión humana y boletín
# ---------------------------------------------------------------------------


async def test_flujo_humano_hasta_publicar(db: Conexion, fuentes_falsas: Path) -> None:
    await _correr(db, LectorFalso({"portal_alfa": ofertas_alfa()}))
    ofertas = {o["titulo"]: o["id"] for o in await almacen.listar(db)}
    buena, analista = ofertas["Practicante de estadística"], ofertas["Analista junior"]

    # Con motivos pendientes hay que escribir qué se revisó.
    with pytest.raises(almacen.ErrorEstado, match="escriba"):
        await almacen.verificar_manual(db, analista, "rev@unal.edu.co", "")
    await almacen.verificar_manual(db, analista, "rev@unal.edu.co", "Revisé el enlace.")
    # No se aprueba lo que no está verificado.
    vencida = ofertas["Pasantía vencida"]
    with pytest.raises(almacen.ErrorEstado):
        await almacen.aprobar(db, vencida, "rev@unal.edu.co")
    await almacen.descartar(db, vencida, "rev@unal.edu.co", "Ya cerró.")
    for oferta_id in (buena, analista):
        await almacen.aprobar(db, oferta_id, "rev@unal.edu.co")
    await db.commit()

    hoja = await boletin.generar(db, HOY, "rev@unal.edu.co")
    assert hoja["ofertas"] == 2
    datos = await boletin.obtener(db, boletin_id=hoja["id"])
    assert datos is not None
    assert (
        "Estadística" in datos["texto"]
        and "Ciencias de la Computación" in datos["texto"]
    )
    assert datos["texto"].index("Estadística") > 0

    publicado = await boletin.aprobar_y_publicar(db, hoja["id"], "rev@unal.edu.co")
    assert publicado["estado"] == "publicado"
    assert publicado["aprobado_por"] == "rev@unal.edu.co"
    final = await almacen.obtener(db, buena)
    assert final is not None and final["estado"] == "publicada"
    assert final["boletin_id"] == hoja["id"]
    pasos = [h["a_estado"] for h in await almacen.historial(db, buena)]
    assert pasos == ["encontrada", "verificada", "aprobada", "publicada"]

    with pytest.raises(boletin.ErrorBoletin):
        await boletin.aprobar_y_publicar(db, hoja["id"], "rev@unal.edu.co")
    # Un boletín publicado no se rehace.
    otra = await boletin.generar(db, HOY, "rev@unal.edu.co")
    assert otra["estado"] == "publicado"


async def test_publicar_pide_rehacer_si_cambio_una_oferta(
    db: Conexion, fuentes_falsas: Path
) -> None:
    await _correr(db, LectorFalso({"portal_alfa": [leida()]}))
    (oferta,) = await almacen.listar(db)
    await almacen.aprobar(db, oferta["id"], "rev@unal.edu.co")
    await db.commit()
    hoja = await boletin.generar(db, HOY, "rev@unal.edu.co")
    await almacen.descartar(
        db, oferta["id"], "rev@unal.edu.co", "La retiró la empresa."
    )
    await db.commit()
    with pytest.raises(boletin.ErrorBoletin, match="Rehaga"):
        await boletin.aprobar_y_publicar(db, hoja["id"], "rev@unal.edu.co")


async def test_boletin_no_incluye_ofertas_que_ya_cerraron(
    db: Conexion, fuentes_falsas: Path
) -> None:
    await _correr(db, LectorFalso({"portal_alfa": [leida()]}))
    (oferta,) = await almacen.listar(db)
    await almacen.aprobar(db, oferta["id"], "rev@unal.edu.co")
    await db.commit()
    hoja = await boletin.generar(db, dia(25), "rev@unal.edu.co")
    assert hoja["ofertas"] == 0


def test_html_del_boletin_escapa_el_contenido() -> None:
    oferta = {
        "titulo": "<script>alert(1)</script>",
        "entidad": "Empresa & Cía",
        "tipo": "empleo",
        "modalidad": "remota",
        "lugar": "",
        "fecha_cierre": None,
        "resumen": "",
        "requisitos": "",
        "url": "javascript:alert(1)",
        "programas": [],
    }
    salida = boletin.a_html("Boletín", boletin.agrupar([oferta]))
    assert "<script>" not in salida and "&lt;script&gt;" in salida
    assert 'href="#"' in salida
    assert boletin.TODOS in salida


async def test_edicion_vuelve_a_la_cola_y_reverifica(
    db: Conexion, fuentes_falsas: Path
) -> None:
    await _correr(db, LectorFalso({"portal_alfa": [leida(programas=[])]}))
    (oferta,) = await almacen.listar(db)
    assert any(m.startswith("programa") for m in oferta["motivos"])
    await almacen.editar(
        db, oferta["id"], {"programas": ["estadistica"]}, "rev@unal.edu.co"
    )
    await db.commit()
    motivos = await verificador.revisar(db, oferta["id"], HOY, None)
    # El programa ya está; solo falta comprobar el enlace (revisión sin red).
    assert motivos == ["enlace_vivo: sin comprobar (revisión sin red)"]


async def test_entidad_aliada_liga_sus_ofertas(
    db: Conexion, fuentes_falsas: Path
) -> None:
    await _correr(db, LectorFalso({"portal_alfa": [leida()]}))
    entidad_id = await almacen.guardar_entidad(
        db, {"nombre": "empresa ficticia UNO", "aliada": True}, "rev@unal.edu.co"
    )
    await db.commit()
    (oferta,) = await almacen.listar(db)
    assert oferta["entidad_id"] == entidad_id
    (entidad,) = await almacen.listar_entidades(db)
    assert entidad["aliada"] is True and entidad["ofertas"] == 1


async def test_siembra_de_practica(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app import practica
    from app.core.config import settings
    from app.db.session import connect

    monkeypatch.setattr(settings, "memoria_practica", True)
    monkeypatch.setattr(settings, "bot_servicio", "oportunidades")
    monkeypatch.setattr(settings, "db_path", tmp_path / "practica" / "fcen.db")
    monkeypatch.setattr(settings, "media_dir", tmp_path / "practica" / "media")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "practica" / "out")
    r = await practica.reiniciar()
    assert r["registros"] == 5
    db = await connect()
    try:
        ofertas = await almacen.listar(db)
        assert len(ofertas) == 3
        assert all(o["url"].startswith("https://ejemplo.invalid/") for o in ofertas)
        assert {o["estado"] for o in ofertas} == {"encontrada"}
    finally:
        await db.close()
