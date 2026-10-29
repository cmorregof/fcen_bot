from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from app.servicios.calidad import plantilla as P
from tests.calidad.conftest import ALFA, BETA, leer, plantilla


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("1 de enero de 2023", [date(2023, 1, 1)]),
        ("30 de agosto 2028", [date(2028, 8, 30)]),
        ("01/02/2025\n\n30/07/2025", [date(2025, 2, 1), date(2025, 7, 30)]),
        ("DESCRIPCIÓN DE AVANCE ACTUAL (03-12-2025)", [date(2025, 12, 3)]),
        ("EVIDENCIAS (10 de diciembre de 2025)", [date(2025, 12, 10)]),
        ("2026-05-21", [date(2026, 5, 21)]),
        ("EVIDENCIAS (PENDIENTE)", []),
        ("31/02/2025", []),
    ],
)
def test_fechas_en_texto(texto: str, esperado: list[date]) -> None:
    assert P.fechas_en_texto(texto) == esperado


@pytest.mark.parametrize(
    ("valor", "formato", "esperado"),
    [
        (0.6, "0%", 60.0),  # celda con formato de porcentaje: 0–1
        (1.0, "0%", 100.0),
        (20.0, "General", 20.0),  # sin formato: la plantilla escribe 0–100
        ("100 %", "General", 100.0),
        ("80%", "General", 80.0),
        ("Tener en cuenta las fechas", "General", None),
        (None, "General", None),
        (True, "General", None),
    ],
)
def test_como_porcentaje(valor: object, formato: str, esperado: float | None) -> None:
    assert P.como_porcentaje(valor, formato) == esperado


@pytest.mark.parametrize(
    ("texto", "codigo", "marcas"),
    [
        ("1.1.1. Elaboración de piezas", "1.1.1", []),
        ("1.2.2.Vinculación de la dirección", "1.2.2", []),
        ("NO FUNCIONÓ 1.1. Revisión del tiempo", "1.1", ["NO FUNCIONÓ"]),
        (" 2.1.1. Creación de canales", "2.1.1", []),
        ("9.1.1 Diseño de un formato", "9.1.1", []),
        ("4. Fortalecer los seminarios", "4", []),
        ("Descripción de actividades que se deben ejecutar", "", []),
        ("Incumplimiento - reprogramar", "", ["reprogramación"]),
    ],
)
def test_separar_codigo(texto: str, codigo: str, marcas: list[str]) -> None:
    assert P.separar_codigo(texto)[:2] == (codigo, marcas)


def test_alfa_encabezados_porcentajes_y_fechas() -> None:
    plan = leer(ALFA)
    assert plan.programa == "Ejemplo Alfa (ficticio)"
    acciones = {a.codigo: a for a in plan.acciones}
    assert list(acciones) == [
        "1.1.1",
        "1.1.2",
        "1.1.3",
        "1.2.1",
        "1.2.2",
        "2.1.1",
        "2.1.2",
    ]
    assert [o.codigo for o in plan.objetivos] == ["1.1", "1.2", "2.1"]
    # % en tres formatos: 0–1 con formato %, 0–100 General y el texto «100 %».
    assert acciones["1.1.1"].avance == 60
    assert acciones["1.1.2"].avance == 50
    assert acciones["1.2.2"].avance == 100
    # La fecha de fin escrita dos veces en la celda es una reprogramación.
    assert acciones["1.2.2"].fecha_fin == date(2025, 7, 30)
    assert acciones["1.2.2"].fechas_fin_anteriores == [date(2025, 2, 1)]
    assert acciones["1.2.2"].reprogramada
    assert acciones["1.1.1"].fecha_inicio == date(2025, 2, 1)
    assert acciones["1.1.1"].responsables == "Dirección del programa (ejemplo)"
    # Los cortes salen de los encabezados con fecha.
    assert [k.rotulo for k in acciones["1.1.1"].cortes] == ["2025-12-03", "2026-05-21"]
    assert acciones["1.1.1"].enlaces == ["https://ejemplo.invalid/drive/alfa-111"]
    # Filas de promedio al pie y la leyenda no son acciones ni alertas.
    assert plan.alertas == []


def test_alfa_cronogramas_por_anio() -> None:
    plan = leer(ALFA)
    assert plan.cronogramas == [2025, 2026]  # « 3. Cronograma 2025» trae un espacio
    acciones = {a.codigo: a for a in plan.acciones}
    t2025, t2026 = acciones["1.1.1"].tareas
    assert (t2025.anio, t2025.fecha_fin, t2025.avance, t2025.ok) == (
        2025,
        date(2025, 4, 30),
        100,
        True,
    )
    assert t2025.enlace.startswith("https://")
    # 2026: sin columnas de fecha; las fechas salen del Gantt semanal.
    assert (t2026.fecha_inicio, t2026.fecha_fin) == (
        date(2026, 4, 1),
        date(2026, 9, 28),
    )
    assert t2026.estado_texto == "Tercera reprogramación" and t2026.reprogramada
    assert t2026.soporte == "Enlaces a las publicaciones"
    assert len(acciones["2.1.1"].tareas) == 2
    assert acciones["2.1.1"].tareas[0].reprogramada
    assert len(plan.tareas) == 5


def test_beta_otra_variante_de_la_plantilla() -> None:
    plan = leer(BETA)
    assert plan.programa == "Ejemplo Beta (ficticio)"
    acciones = {a.codigo: a for a in plan.acciones}
    assert list(acciones) == ["1.1", "1.2", "2.1", "2.2", "2.3"]
    assert acciones["1.1"].fecha_inicio == date(2023, 1, 1)  # fecha escrita como texto
    assert acciones["1.1"].fecha_fin == date(2028, 8, 30)
    assert acciones["1.1"].no_funciono  # marcado en el cronograma, no en el plan
    assert acciones["2.1"].avance == 75
    assert [k.rotulo for k in acciones["2.1"].cortes] == ["2026-02-23", "2026-06-25"]
    assert plan.cronogramas == [2026]  # hoja «Cronograma 2026», sin «3.»
    assert len(acciones["2.1"].tareas) == 2
    assert [e.fecha for e in plan.evaluaciones] == [date(2026, 2, 23)] * 2
    assert len(plan.oportunidades) == 2
    assert plan.alertas == []


def test_alertas_de_lectura_citan_la_celda_sin_su_contenido() -> None:
    def romper(libro: Workbook) -> None:
        hoja = libro["2. Plan de Mejora"]
        hoja["O10"] = "pendiente de revisar"
        hoja["N11"] = "sin definir"

    lectura = P.leer_plantilla(plantilla(ALFA, romper))
    assert lectura.plan is not None
    assert lectura.plan.alertas == [
        "«2. Plan de Mejora» O10: acción 1.1.2 sin % de avance legible.",
        "«2. Plan de Mejora» N11: acción 1.1.3 sin fecha de fin legible.",
    ]


def test_cronograma_con_accion_que_no_esta_en_el_plan() -> None:
    def agregar(libro: Workbook) -> None:
        hoja = libro["3. Cronograma 2026"]
        hoja["C30"] = "7.7. Acción que no existe"
        hoja["G30"] = "Tarea huérfana"

    plan = P.leer_plantilla(plantilla(ALFA, agregar)).plan
    assert plan is not None
    assert (
        "«3. Cronograma 2026»: la acción 7.7 no está en el plan; sus tareas no se cargaron."
        in plan.alertas
    )


def test_archivo_que_no_es_un_plan() -> None:
    libro = Workbook()
    assert libro.active is not None
    libro.active.title = "CRONOGRAMA"
    salida = io.BytesIO()
    libro.save(salida)
    lectura = P.leer_plantilla(salida.getvalue())
    assert lectura.plan is None and "2. Plan de Mejora" in lectura.errores[0]
    assert "xlsx" in P.leer_plantilla(b"no soy un excel").errores[0]
