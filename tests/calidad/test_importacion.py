from __future__ import annotations

from collections.abc import Callable

import aiosqlite
from openpyxl import Workbook

from app.servicios.calidad import plan
from tests.calidad.conftest import ALFA, BETA, Chat_, plantilla


async def _contar(db: aiosqlite.Connection, tabla: str, donde: str = "1=1") -> int:
    cur = await db.execute(f"SELECT COUNT(*) FROM {tabla} WHERE {donde}")
    fila = await cur.fetchone()
    return int(fila[0]) if fila else 0


async def test_muestra_resumen_y_no_guarda_antes_de_confirmar(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(plantilla(ALFA))
    resumen = await chat.documento("plan_alfa.xlsx", caption="/importar_plan")
    assert "Programa: <b>Ejemplo Alfa (ficticio)</b> (nuevo)" in resumen
    assert (
        "Objetivos: 3 · acciones: 7 · tareas del cronograma: 5 (años: 2025, 2026)"
        in resumen
    )
    assert "Avance promedio de las acciones: 54 %" in resumen
    assert "Sin alertas de lectura." in resumen
    assert await plan.listar_programas(db) == []

    assert "7 acciones nuevas" in await chat.boton("cal:imp:ok")
    guardado = await plan.cargar_plan(db, "Ejemplo Alfa (ficticio)")
    assert guardado is not None and len(guardado.plan.acciones) == 7
    assert sum(len(c) for c in guardado.cortes.values()) == 5


async def test_cancelar_no_guarda(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(plantilla(BETA))
    await chat.documento("plan_beta.xlsx", caption="/importar_plan")
    assert "cancelada" in await chat.boton("cal:imp:no")
    assert await plan.listar_programas(db) == []


async def test_resumen_muestra_alertas_de_lectura(
    chat: Chat_, servir_excel: Callable[[bytes], None]
) -> None:
    def romper(libro: Workbook) -> None:
        libro["2. Plan de Mejora"]["O10"] = "pendiente"

    servir_excel(plantilla(ALFA, romper))
    resumen = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "Alertas de lectura (1)" in resumen
    assert "O10: acción 1.1.2 sin % de avance legible" in resumen


async def test_archivo_sin_la_plantilla_no_ofrece_guardar(
    chat: Chat_, servir_excel: Callable[[bytes], None]
) -> None:
    def quitar_plan(libro: Workbook) -> None:
        del libro["2. Plan de Mejora"]

    servir_excel(plantilla(ALFA, quitar_plan))
    respuesta = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "No guardé nada" in respuesta and "2. Plan de Mejora" in respuesta
    assert "no hay una importación" in (await chat.boton("cal:imp:ok")).lower()


async def test_importar_en_dos_pasos(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    assert "plantilla institucional" in await chat.texto("/importar_plan")
    servir_excel(plantilla(BETA))
    assert "Ejemplo Beta" in await chat.documento("plan.xlsx")
    await chat.boton("cal:imp:ok")
    assert await plan.listar_programas(db) == ["Ejemplo Beta (ficticio)"]


async def test_reimportar_no_duplica_y_guarda_el_historial_de_cortes(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(plantilla(ALFA))
    await chat.documento("plan.xlsx", caption="/importar_plan")
    await chat.boton("cal:imp:ok")

    # El mismo archivo: nada cambia.
    resumen = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "ya estaba cargado" in resumen
    assert "nuevas: 0 · actualizadas: 0 · sin cambios: 7" in resumen
    assert "Cortes de avance: 0 nuevos, 0 con cambios" in resumen
    await chat.boton("cal:imp:ok")
    assert await _contar(db, "cal_acciones") == 7
    assert await _contar(db, "cal_cortes") == 5

    # Nuevo corte: cambia el % de 1.1.2, se corrige la descripción de un corte
    # anterior, aparece la columna del corte de diciembre y 2.1.2 ya no viene.
    def siguiente_corte(libro: Workbook) -> None:
        hoja = libro["2. Plan de Mejora"]
        hoja["O10"] = 80
        hoja["Q9"] = "Se publicó una pieza; texto corregido (ficticio)."
        hoja["S5"] = "DESCRIPCIÓN DE AVANCE ACTUAL (16-12-2026)"
        hoja["S9"] = "Tercera pieza publicada (ficticio)."
        hoja["G15"] = None

    servir_excel(plantilla(ALFA, siguiente_corte))
    resumen = await chat.documento("plan.xlsx", caption="/importar_plan")
    assert "actualizadas: 1 · sin cambios: 5" in resumen
    assert "1.1.2: cambia % de avance" in resumen
    assert "Cortes de avance: 1 nuevos, 1 con cambios" in resumen
    assert "no en este archivo: 1 (2.1.2). No se borran." in resumen
    await chat.boton("cal:imp:ok")

    assert await _contar(db, "cal_acciones") == 7  # no duplica
    assert await _contar(db, "cal_cortes") == 6  # el corte nuevo se suma
    guardado = await plan.cargar_plan(db, "Ejemplo Alfa (ficticio)")
    assert guardado is not None
    assert [k.rotulo for k in guardado.cortes["1.1.1"]] == [
        "2025-12-03",
        "2026-05-21",
        "2026-12-16",
    ]
    assert guardado.accion("1.1.2") is not None
    assert guardado.accion("1.1.2").avance == 80  # type: ignore[union-attr]
    ausente = guardado.accion("2.1.2")
    assert ausente is not None and plan.AUSENTE in ausente.marcas
    # El historial guarda el texto anterior del corte y el % anterior.
    cur = await db.execute(
        "SELECT tipo, cambios_json FROM cal_cambios WHERE tipo != 'creada'"
    )
    cambios = {r[0]: r[1] for r in await cur.fetchall()}
    assert set(cambios) == {"actualizada", "corte_cambiado", "ausente"}
    assert "[50.0, 80.0]" in cambios["actualizada"]
    assert "Se publicó una pieza (ficticio)." in cambios["corte_cambiado"]
    assert await _contar(db, "cal_importaciones") == 3


async def test_programa_con_otra_escritura_es_el_mismo(
    chat: Chat_, db: aiosqlite.Connection, servir_excel: Callable[[bytes], None]
) -> None:
    servir_excel(plantilla(ALFA))
    await chat.documento("a.xlsx", caption="/importar_plan")
    await chat.boton("cal:imp:ok")

    def renombrar(libro: Workbook) -> None:
        libro["2. Plan de Mejora"]["C3"] = "  ejemplo ALFA (ficticio) "

    servir_excel(plantilla(ALFA, renombrar))
    assert "ya estaba cargado" in await chat.documento(
        "b.xlsx", caption="/importar_plan"
    )
