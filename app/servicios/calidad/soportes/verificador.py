"""Verificador determinista de citas.

Cada cita [S012] debe apuntar a un archivo del inventario. Las que no cumplen
se marcan (no se borran) para que la oficina de calidad las vea.
"""

from __future__ import annotations

import re

from app.servicios.calidad.soportes.modelos import Archivo, Cruce, EstadoCita, Veredicto

PATRON_CITA = re.compile(r"\[\s*(S\d{3,})\s*\]")


def citas_en_texto(texto: str) -> list[str]:
    return PATRON_CITA.findall(texto or "")


def verificar_citas(
    citas: list[str], inventario: dict[str, Archivo], accion: str | None = None
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
            estados.append(EstadoCita(cita, False, None, "no está en el inventario"))
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


def verificar_cruce(cruce: Cruce, inventario: dict[str, Archivo]) -> None:
    """Llena `verificacion` y `alertas` del cruce."""
    p = cruce.propuesta
    if p is None:
        return
    todas = list(p.citas)
    for texto in (p.justificacion, p.falta, p.parrafo_cierre):
        todas += citas_en_texto(texto)
    cruce.verificacion = verificar_citas(todas, inventario, cruce.accion.codigo)
    invalidas = [e.cita for e in cruce.verificacion if not e.valida]
    if invalidas:
        cruce.alertas.append(
            "Citas que no están en el inventario: " + ", ".join(invalidas)
        )
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
