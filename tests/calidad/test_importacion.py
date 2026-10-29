from __future__ import annotations

from collections.abc import Callable
from datetime import date

import aiosqlite

from app.servicios.calidad import plan
from tests.calidad.conftest import ENCABEZADO, Chat_, fila, xlsx


def test_columnas_faltantes() -> None:
    sin = [c for c in ENCABEZADO if c not in ("programa", "responsable_cargo")]
    lectura = plan.leer_plan(xlsx([], encabezado=sin))
    assert lectura.filas == []
    assert (
        "programa" in lectura.errores[0] and "responsable_cargo" in lectura.errores[0]
    )


def test_no_es_xlsx() -> None:
    assert "xlsx" in plan.leer_plan(b"no soy un excel").errores[0]


def test_filas_invalidas_se_reportan_con_su_numero() -> None:
    lectura = plan.leer_plan(
        xlsx([fila(), fila(codigo="UNO-02", limite="mañana"), fila(codigo="UNO-01")])
    )
    assert len(lectura.filas) == 1
    assert any("Fila 3" in e and "fecha_limite" in e for e in lectura.errores)
    assert any("Fila 4" in e and "UNO-01" in e for e in lectura.errores)


def test_acepta_fechas_de_texto_y_columnas_opcionales() -> None:
    lectura = plan.leer_plan(xlsx([fila(limite="15/11/2026")]))
    assert not lectura.errores
    assert lectura.filas[0].fecha_limite == date(2026, 11, 15)
    assert lectura.filas[0].factor_cna == ""


async def test_importacion_pide_confirmacion_y_no_guarda_antes(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(xlsx([fila(), fila(codigo="UNO-02")]))
    resumen = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "Nuevas: 2" in resumen
    assert await plan.listar_tareas(db) == []

    assert "2 nuevas" in await chat.boton("cal:imp:ok")
    assert len(await plan.listar_tareas(db)) == 2


async def test_cancelar_no_guarda(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(xlsx([fila()]))
    await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "cancelada" in await chat.boton("cal:imp:no")
    assert await plan.listar_tareas(db) == []


async def test_importar_con_errores_no_ofrece_guardar(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(xlsx([fila(tarea="")]))
    respuesta = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "No guardé nada" in respuesta and "Fila 2" in respuesta
    assert "no hay una importación" in (await chat.boton("cal:imp:ok")).lower()


async def test_reimportar_no_duplica_y_guarda_historial(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(xlsx([fila(), fila(codigo="UNO-02")]))
    await chat.documento("plan.xlsx", caption="/importar_plan")
    await chat.boton("cal:imp:ok")

    # Mismo archivo: nada cambia.
    resumen = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "Sin cambios: 2" in resumen and "Nuevas: 0" in resumen
    await chat.boton("cal:imp:ok")
    assert len(await plan.listar_tareas(db)) == 2

    # Cambia una fecha y llega una tarea nueva; UNO-02 no viene y se conserva.
    servir_excel(xlsx([fila(limite=date(2026, 12, 1)), fila(codigo="UNO-03")]))
    resumen = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "Nuevas: 1" in resumen and "Actualizadas: 1" in resumen
    assert "UNO-02" in resumen and "No se borran" in resumen
    await chat.boton("cal:imp:ok")

    tareas = {t.codigo: t for t in await plan.listar_tareas(db)}
    assert set(tareas) == {"UNO-01", "UNO-02", "UNO-03"}
    assert tareas["UNO-01"].fecha_limite == date(2026, 12, 1)

    cur = await db.execute(
        "SELECT cambios_json FROM cal_historial WHERE accion = 'actualizada'"
    )
    filas = await cur.fetchall()
    assert (
        len(filas) == 1 and "2026-11-10" in filas[0][0] and "2026-12-01" in filas[0][0]
    )
    cur = await db.execute("SELECT COUNT(*) FROM cal_importaciones")
    fila_n = await cur.fetchone()
    assert fila_n is not None and fila_n[0] == 3


async def test_programa_con_otra_escritura_es_el_mismo(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(xlsx([fila(programa="Programa Único")]))
    await chat.documento("a.xlsx", caption="/importar_plan")
    await chat.boton("cal:imp:ok")
    servir_excel(xlsx([fila(programa="  programa unico ")]))
    assert "Nuevas: 0" in await chat.documento("b.xlsx", caption="/importar_plan")
