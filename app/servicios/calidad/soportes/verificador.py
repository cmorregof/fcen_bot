"""Verificador determinista de citas.

Una cita [S012] (o un grupo [S012, S013]) es válida solo si:
1. el ID está en el inventario;
2. el archivo se le mostró al modelo en esa llamada (soportes de la acción o
   documentos generales), y
3. el modelo vio su contenido (el archivo tiene descripción).

Las que no cumplen se marcan (no se borran) para que la oficina de calidad las
vea, y no cuentan como evidencia: no aparecen como citas válidas y en el
borrador salen con ⚠.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.servicios.calidad.soportes.modelos import Archivo, Cruce, EstadoCita, Veredicto

PATRON_ID = re.compile(r"\bS\d{3,}\b")
# Un corchete con uno o varios IDs: [S012], [S012, S013], [S012; S013].
PATRON_CITA = re.compile(r"\[([^\[\]]*?\bS\d{3,}\b[^\[\]]*?)\]")

NO_INVENTARIO = "no está en el inventario"
NO_MOSTRADO = "no se le mostró al modelo en esta acción"
SIN_CONTENIDO = "el modelo no vio su contenido (sin descripción)"


def citas_en_texto(texto: str) -> list[str]:
    ids: list[str] = []
    for grupo in PATRON_CITA.findall(texto or ""):
        ids += PATRON_ID.findall(grupo)
    return ids


def verificar_citas(
    citas: Iterable[str],
    inventario: dict[str, Archivo],
    accion: str | None = None,
    visibles: set[str] | None = None,
    sin_contenido: set[str] | None = None,
) -> list[EstadoCita]:
    estados: list[EstadoCita] = []
    vistas: set[str] = set()
    for crudo in citas:
        cita = crudo.strip().strip("[]").strip()
        if cita in vistas:
            continue
        vistas.add(cita)
        archivo = inventario.get(cita)
        if archivo is None:
            estados.append(EstadoCita(cita, False, None, NO_INVENTARIO))
            continue
        if visibles is not None and cita not in visibles:
            estados.append(EstadoCita(cita, False, archivo, NO_MOSTRADO))
            continue
        if sin_contenido and cita in sin_contenido:
            estados.append(EstadoCita(cita, False, archivo, SIN_CONTENIDO))
            continue
        nota = ""
        if accion is not None and archivo.accion != accion:
            nota = (
                "documento general del plan"
                if not archivo.accion
                else f"soporte de otra acción ({archivo.accion})"
            )
        estados.append(EstadoCita(cita, True, archivo, nota))
    return estados


def verificar_cruce(
    cruce: Cruce,
    inventario: dict[str, Archivo],
    visibles: set[str] | None = None,
    sin_contenido: set[str] | None = None,
) -> None:
    """Llena `verificacion` y `alertas` del cruce."""
    p = cruce.propuesta
    if p is None:
        return
    todas = [c for crudo in p.citas for c in (PATRON_ID.findall(crudo) or [crudo])]
    for texto in (p.justificacion, p.falta, p.parrafo_cierre):
        todas += citas_en_texto(texto)
    cruce.verificacion = verificar_citas(
        todas, inventario, cruce.accion.codigo, visibles, sin_contenido
    )
    invalidas = [e for e in cruce.verificacion if not e.valida]
    por_motivo: dict[str, list[str]] = {}
    for e in invalidas:
        por_motivo.setdefault(e.nota, []).append(e.cita)
    if NO_INVENTARIO in por_motivo:
        cruce.alertas.append(
            "Citas que no están en el inventario: "
            + ", ".join(por_motivo[NO_INVENTARIO])
        )
    if NO_MOSTRADO in por_motivo:
        cruce.alertas.append(
            "Citas de archivos que el modelo no tenía para esta acción: "
            + ", ".join(por_motivo[NO_MOSTRADO])
        )
    if SIN_CONTENIDO in por_motivo:
        cruce.alertas.append(
            "Citas de archivos sin descripción (el modelo no vio su contenido): "
            + ", ".join(por_motivo[SIN_CONTENIDO])
        )
    if invalidas:
        cruce.alertas.append("Las citas no verificadas no cuentan como evidencia.")
    validas = [e for e in cruce.verificacion if e.valida]
    if p.veredicto != Veredicto.SIN_EVIDENCIA and not validas:
        cruce.alertas.append("El veredicto propuesto no tiene ninguna cita válida.")
    if p.veredicto == Veredicto.SIN_EVIDENCIA and p.avance_propuesto > 0:
        cruce.alertas.append(
            "Sin evidencia pero con avance mayor que 0 %: revisar la coherencia."
        )
    if p.veredicto == Veredicto.SUFICIENTE and p.avance_propuesto < 100:
        cruce.alertas.append(
            "Evidencia suficiente con avance menor que 100 %: revisar la coherencia."
        )
    if not citas_en_texto(p.parrafo_cierre):
        cruce.alertas.append("El párrafo de cierre no cita ningún soporte.")
