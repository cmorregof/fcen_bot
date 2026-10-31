"""Secretaría de Facultad: fechas de los actos, tiempos de notificación y
estadísticas del Consejo para Calidad."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.db import repo
from app.services import (
    estadisticas_consejo,
    flujo,
    indicadores,
    notificaciones,
    oficio_consejo,
)

router = APIRouter(prefix="/actas/secretaria", tags=["secretaria"])

_Registra = Annotated[Usuario, Depends(auth.requiere("secretaria", "admin"))]
_Consulta = Annotated[
    Usuario, Depends(auth.requiere("secretaria", "decanatura", "admin"))
]


def _semestre(texto: str) -> notificaciones.Semestre:
    try:
        return notificaciones.semestre_de(texto, indicadores.hoy_local())
    except notificaciones.PeriodoInvalido as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/notificaciones")
async def ver(_: _Registra, db: Db, semestre: str = "") -> dict[str, object]:
    elegido = _semestre(semestre)
    return notificaciones.a_json(elegido, await notificaciones.listar(db, elegido))


@router.put("/notificaciones/{caso_id}")
async def guardar(
    caso_id: int, cuerpo: notificaciones.Registro, usuario: _Registra, db: Db
) -> dict[str, object]:
    if not await notificaciones.decidido_por_facultad(db, caso_id):
        raise HTTPException(
            404, "Ese caso no tiene una decisión del Consejo de Facultad confirmada."
        )
    error = cuerpo.error(indicadores.hoy_local())
    if error:
        raise HTTPException(422, error)
    try:
        await notificaciones.guardar(
            db, caso_id, cuerpo, usuario.correo, rol=usuario.rol
        )
    except flujo.TransicionNoPermitida as exc:
        raise HTTPException(409, str(exc)) from None
    return {"guardado": True}


@router.get("/notificaciones/xlsx")
async def descargar(_: _Consulta, db: Db, semestre: str = "") -> Response:
    elegido = _semestre(semestre)
    filas = await notificaciones.listar(db, elegido)
    return Response(
        content=notificaciones.xlsx(elegido, filas, indicadores.hoy_local()),
        media_type=notificaciones.MIME_XLSX,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{notificaciones.nombre_xlsx(elegido)}"'
            )
        },
    )


@router.get("/estadisticas/xlsx")
async def estadisticas(_: _Consulta, db: Db, semestre: str = "") -> Response:
    """Solicitudes decididas por el Consejo de Facultad, para Calidad. Acepta
    un semestre (2026-1S, 2026-2S) o un año completo (2026)."""
    hoy = indicadores.hoy_local()
    try:
        periodo = estadisticas_consejo.periodo_de(semestre, hoy)
    except notificaciones.PeriodoInvalido as exc:
        raise HTTPException(422, str(exc)) from None
    r = await estadisticas_consejo.calcular(db, periodo, hoy)
    return Response(
        content=estadisticas_consejo.xlsx(r),
        media_type=estadisticas_consejo.MIME_XLSX,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{estadisticas_consejo.nombre_xlsx(r)}"'
            )
        },
    )


@router.get("/casos/{caso_id}/oficio-consejo")
async def oficio(caso_id: int, usuario: _Registra, db: Db) -> Response:
    """El borrador del oficio o resolución del Consejo, para la Secretaría, que
    es quien lo expide (de cualquier área)."""
    caso = await repo.get_caso(db, caso_id)
    if caso is None:
        raise HTTPException(404, "No encontré ese caso.")
    motivo = oficio_consejo.motivo_sin_oficio(caso)
    if motivo:
        raise HTTPException(409, motivo)
    return Response(
        oficio_consejo.construir_oficio_consejo(caso, elaboro=usuario.nombre or ""),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{oficio_consejo.nombre_archivo(caso)}"'
            )
        },
    )
