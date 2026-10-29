"""Reporte en Excel: estado del plan, detalle y pestaña «fuentes».

Cada cifra de la pestaña «estado» tiene en «fuentes» una fila por cada acción
que la compone, con el registro, la importación y la hoja y fila de origen en
el plan del programa.
"""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from app.servicios.calidad.plan import (
    Estado,
    PlanGuardado,
    calcular_estado,
    proximo_corte,
)
from app.servicios.calidad.plantilla import Accion
from app.servicios.calidad.textos import ORDEN, PLURAL, agrupar


def _hoja(libro: Workbook, titulo: str, columnas: list[str]) -> Worksheet:
    hoja = libro.create_sheet(titulo)
    hoja.append(columnas)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    return hoja


def _iso(f: date | None) -> str:
    return f.isoformat() if f else ""


def cifras(pg: PlanGuardado, hoy: date) -> list[tuple[str, list[Accion]]]:
    """Cada cifra del reporte con las acciones que la componen."""
    acciones = pg.plan.acciones
    grupos = agrupar(acciones, hoy)
    salida: list[tuple[str, list[Accion]]] = [("Acciones", acciones)]
    salida += [(f"Acciones {PLURAL[e]}", grupos[e]) for e in ORDEN]
    salida.append(("Acciones reprogramadas", [a for a in acciones if a.reprogramada]))
    salida.append(
        (
            "Acciones con soportes por revisar",
            [a for a in acciones if pg.soportes.get(a.codigo)],
        )
    )
    return salida


def generar_reporte(pg: PlanGuardado, hoy: date) -> bytes:
    plan = pg.plan
    libro = Workbook()
    resumen = libro.active
    assert resumen is not None
    resumen.title = "estado"
    resumen.append(["Cifra", "Valor", "Fecha de corte", "Programa"])
    for celda in resumen[1]:
        celda.font = Font(bold=True)
    for nombre, lista in cifras(pg, hoy):
        resumen.append([nombre, len(lista), hoy.isoformat(), plan.programa])
    promedio = plan.avance_promedio()
    resumen.append(
        [
            "Avance promedio (%)",
            round(promedio, 1) if promedio is not None else "",
            hoy.isoformat(),
            plan.programa,
        ]
    )
    resumen.append(
        ["Tareas del cronograma", len(plan.tareas), hoy.isoformat(), plan.programa]
    )
    corte = proximo_corte(plan, hoy)
    if corte:
        resumen.append(
            [
                "Próximo corte" + (" (estimado)" if corte[1] else ""),
                corte[0].isoformat(),
                hoy.isoformat(),
                plan.programa,
            ]
        )

    detalle = _hoja(
        libro,
        "acciones",
        [
            "Objetivo", "Código", "Acción", "Indicador", "Responsables", "Inicio",
            "Fin", "Fines anteriores", "% avance", "Estado", "Reprogramada",
            "Estado escrito", "Evidencias", "Tareas", "Origen",
        ],
    )  # fmt: skip
    for a in plan.acciones:
        detalle.append(
            [
                a.objetivo_codigo, a.codigo, a.descripcion, a.indicador,
                a.responsables, _iso(a.fecha_inicio), _iso(a.fecha_fin),
                ", ".join(f.isoformat() for f in a.fechas_fin_anteriores),
                a.avance, calcular_estado(a, hoy).value,
                "sí" if a.reprogramada else "no", ", ".join(a.marcas),
                a.evidencias, len(a.tareas), a.origen,
            ]
        )  # fmt: skip

    tareas = _hoja(
        libro,
        "tareas",
        [
            "Acción", "Año", "Tarea", "Soporte", "Responsable", "Inicio", "Fin",
            "% avance", "OK", "Estado escrito", "Reprogramada", "Enlace", "Origen",
        ],
    )  # fmt: skip
    for a in plan.acciones:
        for t in a.tareas:
            tareas.append(
                [
                    a.codigo, t.anio, t.descripcion, t.soporte, t.responsable,
                    _iso(t.fecha_inicio), _iso(t.fecha_fin), t.avance,
                    "" if t.ok is None else ("sí" if t.ok else "no"),
                    t.estado_texto, "sí" if t.reprogramada else "no", t.enlace,
                    f"«{t.hoja}» fila {t.fila}",
                ]
            )  # fmt: skip

    cortes = _hoja(
        libro,
        "cortes",
        [
            "Acción",
            "Corte",
            "Fecha",
            "Descripción del avance",
            "Evidencias",
            "Id importación",
        ],
    )
    for a in plan.acciones:
        for k in pg.cortes.get(a.codigo, []):
            cortes.append(
                [
                    a.codigo,
                    k.rotulo,
                    _iso(k.fecha),
                    k.descripcion,
                    k.evidencias,
                    k.importacion_id,
                ]
            )

    fuentes = _hoja(
        libro,
        "fuentes",
        [
            "Cifra", "Código de acción", "Id registro acción", "Id importación",
            "Archivo", "Origen en el plan", "Estado calculado", "% avance", "Fin",
            "Soporte registrado", "Registrado por", "Registrado el",
        ],
    )  # fmt: skip
    for nombre, lista in cifras(pg, hoy):
        for a in lista:
            base = [
                nombre, a.codigo, pg.ids.get(a.codigo), pg.importacion_id,
                pg.archivo, a.origen, calcular_estado(a, hoy).value, a.avance,
                _iso(a.fecha_fin),
            ]  # fmt: skip
            soporte = pg.soportes.get(a.codigo, [])
            if soporte:
                s = soporte[-1]
                fuentes.append(
                    [*base, s.valor, s.registrado_nombre or s.registrado_por, s.creado]
                )
            else:
                fuentes.append([*base, "", "", ""])

    for hoja in libro.worksheets:
        for col in hoja.columns:
            ancho = max(len(str(c.value or "")) for c in col)
            hoja.column_dimensions[col[0].column_letter].width = min(ancho + 2, 60)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


__all__ = ["Estado", "cifras", "generar_reporte"]
