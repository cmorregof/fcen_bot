"""Acciones de un plan para el cruce con los soportes. Lee dos formatos:

1. **Plantilla institucional** (cinco hojas, la de main): si el libro tiene la
   hoja «2. Plan de Mejora», se lee con `plantilla.leer_plantilla`, el mismo
   lector del bot, y cada acción (programa → objetivo → acción → tareas) se
   reduce a la vista que necesita el cruce. Los códigos son los del plan
   (1.1.1), igual que las carpetas «ACCIÓN 1.1.1» de los soportes.
2. **Formato 2016** (una sola hoja), anterior a la plantilla y que el lector
   del bot no lee: columnas «Aspectos a mejorar…», «Objetivo», «Acciones»,
   «Fechas Ejecución» (Inicio/Fin) e «Indicadores de cumplimiento». Las
   acciones se numeran por aspecto: la tercera acción del cuarto aspecto es la
   4.3, igual que las carpetas «ACCION 4.3».

De ninguno de los dos se leen responsables (nombres y correos).
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.servicios.calidad import plantilla
from app.servicios.calidad.soportes.modelos import Accion


def _clave(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or "")).lower()
    return "".join(c for c in texto if not unicodedata.combining(c)).strip()


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime | date):
        return valor.strftime("%Y-%m-%d")
    return " ".join(str(valor).split())


def _iso(valor: date | None) -> str:
    return valor.isoformat() if valor else ""


def desde_plantilla(plan: plantilla.Plan) -> list[Accion]:
    """Programa → objetivo → acción → tareas, reducido a lo que usa el cruce."""
    acciones: list[Accion] = []
    for objetivo in plan.objetivos:
        texto_objetivo = objetivo.texto
        if objetivo.meta:
            texto_objetivo += f" (meta: {objetivo.meta})"
        for a in objetivo.acciones:
            tareas = [
                t.descripcion
                + (f" (soporte esperado: {t.soporte})" if t.soporte else "")
                for t in a.tareas
                if t.descripcion
            ]
            acciones.append(
                Accion(
                    codigo=a.codigo,
                    aspecto=objetivo.oportunidad,
                    objetivo=texto_objetivo,
                    descripcion=a.descripcion,
                    indicador=a.indicador,
                    inicio=_iso(a.fecha_inicio),
                    fin=_iso(a.fecha_fin),
                    tareas=tareas,
                    avance_declarado=a.avance,
                    marcas=list(a.marcas),
                )
            )
    return acciones


def es_plantilla(ruta: Path) -> bool:
    libro = load_workbook(ruta, read_only=True)
    try:
        return any("plan de mejora" in plantilla.plegar(t) for t in libro.sheetnames)
    finally:
        libro.close()


def leer_acciones(ruta: Path) -> list[Accion]:
    if es_plantilla(ruta):
        lectura = plantilla.leer_plantilla(ruta.read_bytes())
        if lectura.plan is None:
            raise ValueError(" ".join(lectura.errores))
        return desde_plantilla(lectura.plan)
    return leer_formato_2016(ruta)


def _hoja_y_encabezado(libro: Any) -> tuple[list[list[Any]], int]:
    """La primera hoja con una fila «Acciones … Indicador» en sus 30 primeras."""
    for hoja in libro.worksheets:
        filas = [list(f) for f in hoja.iter_rows(values_only=True)]
        for i, fila in enumerate(filas[:30]):
            claves = [_clave(c) for c in fila]
            if any(k.startswith("acciones") for k in claves) and any(
                k.startswith("indicador") for k in claves
            ):
                return filas, i
    return [], -1


def leer_formato_2016(ruta: Path) -> list[Accion]:
    libro = load_workbook(ruta, data_only=True)
    filas, fila_enc = _hoja_y_encabezado(libro)

    columnas: dict[str, int] = {}
    if fila_enc >= 0:
        for j, k in enumerate(_clave(c) for c in filas[fila_enc]):
            if k.startswith("aspecto"):
                columnas["aspecto"] = j
            elif k.startswith("objetivo"):
                columnas["objetivo"] = j
            elif k.startswith("acciones"):
                columnas["accion"] = j
            elif k.startswith("fecha"):
                columnas["inicio"] = j
                columnas["fin"] = j + 1
            elif k.startswith("indicador"):
                columnas["indicador"] = j
    if fila_enc < 0 or "accion" not in columnas:
        raise ValueError("No encontré la fila de encabezado del plan (Acciones…).")

    def celda(fila: list[Any], nombre: str) -> str:
        j = columnas.get(nombre)
        return _texto(fila[j]) if j is not None and j < len(fila) else ""

    acciones: list[Accion] = []
    n_aspecto = 0
    n_accion = 0
    actual = {"aspecto": "", "objetivo": "", "inicio": "", "fin": ""}
    for fila in filas[fila_enc + 1 :]:
        texto_accion = celda(fila, "accion")
        if not texto_accion:
            continue
        if celda(fila, "accion").lower() in ("inicio", "fin"):
            continue
        aspecto = celda(fila, "aspecto")
        if aspecto:
            n_aspecto += 1
            n_accion = 0
            actual["aspecto"] = aspecto
            actual["objetivo"] = ""
        # El objetivo puede cambiar dentro de un mismo aspecto.
        objetivo = celda(fila, "objetivo")
        if objetivo:
            actual["objetivo"] = objetivo
        if n_aspecto == 0:
            n_aspecto = 1
        for campo in ("inicio", "fin"):
            valor = celda(fila, campo)
            if valor and valor.lower() not in ("inicio", "fin"):
                actual[campo] = valor
        n_accion += 1
        acciones.append(
            Accion(
                codigo=f"{n_aspecto}.{n_accion}",
                aspecto=actual["aspecto"],
                objetivo=actual["objetivo"],
                descripcion=texto_accion,
                indicador=celda(fila, "indicador"),
                inicio=actual["inicio"],
                fin=actual["fin"],
            )
        )
    return acciones
