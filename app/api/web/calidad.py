"""API web del servicio de calidad. Solo se monta con BOT_SERVICIO=calidad."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.servicios.calidad import directorio, operaciones, plan, reloj, reporte, textos
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.db import init_calidad
from app.servicios.calidad.plan import Estado, Tarea

router = APIRouter(prefix="/calidad")

_Calidad = Annotated[Usuario, Depends(auth.requiere("calidad", "admin"))]
_Lectura = Annotated[Usuario, Depends(auth.requiere("calidad", "admin", "decanatura"))]
_MAX_XLSX = 5_000_000


def _tarea(t: Tarea, hoy: date) -> dict[str, object]:
    return {
        "id": t.id,
        "programa": t.programa,
        "codigo": t.codigo,
        "tarea": t.tarea,
        "responsable": textos.responsable(t),
        "fecha_limite": t.fecha_limite.isoformat(),
        "evidencia_esperada": t.evidencia_esperada,
        "estado": t.estado(hoy).value,
        "evidencias": [
            {
                "tipo": e.tipo,
                "valor": e.valor,
                "por": e.registrado_nombre,
                "fecha": e.creado,
            }
            for e in t.evidencias
        ],
    }


def _conteo(tareas: list[Tarea], hoy: date) -> dict[str, int]:
    conteo = {e.value: 0 for e in Estado}
    for t in tareas:
        conteo[t.estado(hoy).value] += 1
    return conteo


@router.get("/programas")
async def programas(_: _Calidad, db: Db) -> dict[str, object]:
    await init_calidad(db)
    hoy = reloj.hoy()
    tareas = await plan.listar_tareas(db)
    return {
        "programas": [
            {
                "programa": p,
                "conteo": _conteo([t for t in tareas if t.programa == p], hoy),
            }
            for p in await plan.listar_programas(db)
        ]
    }


@router.get("/plan")
async def ver_plan(programa: str, _: _Calidad, db: Db) -> dict[str, object]:
    await init_calidad(db)
    encontrado = await plan.buscar_programa(db, programa)
    if encontrado is None:
        raise HTTPException(404, f"No encontré el programa «{programa}».")
    hoy = reloj.hoy()
    tareas = await plan.listar_tareas(db, encontrado)
    return {
        "programa": encontrado,
        "hoy": hoy.isoformat(),
        "conteo": _conteo(tareas, hoy),
        "tareas": [_tarea(t, hoy) for t in tareas],
    }


async def _leer_xlsx(archivo: UploadFile) -> bytes:
    if not (archivo.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "El archivo debe ser un .xlsx.")
    contenido = await archivo.read(_MAX_XLSX + 1)
    if len(contenido) > _MAX_XLSX:
        raise HTTPException(400, "El archivo pesa más de 5 MB.")
    return contenido


@router.post("/importar")
async def importar(
    _: _Calidad,
    db: Db,
    archivo: Annotated[UploadFile, File()],
    confirmar: Annotated[bool, Form()] = False,
) -> dict[str, object]:
    """Sin `confirmar` solo muestra qué cambiaría. Con `confirmar` guarda."""
    await init_calidad(db)
    vista = await operaciones.previsualizar(db, await _leer_xlsx(archivo))
    if vista.resumen is None:
        return {"guardado": False, "errores": vista.errores}
    r = vista.resumen
    datos: dict[str, object] = {
        "errores": [],
        "nuevas": [f"{f.programa} · {f.codigo}" for f in r.nuevas],
        "actualizadas": [
            {"tarea": f"{f.programa} · {f.codigo}", "cambios": list(c)}
            for f, c in r.actualizadas
        ],
        "sin_cambios": r.sin_cambios,
        "ausentes": [f"{p} · {c}" for p, c in r.ausentes],
    }
    if not confirmar:
        return {"guardado": False, **datos}
    await operaciones.guardar_plan(
        db, vista.filas, archivo=archivo.filename or "plan.xlsx", usuario_id=0
    )
    return {"guardado": True, **datos}


class NuevaEvidencia(BaseModel):
    tarea_id: int
    enlace: str


@router.post("/evidencia")
async def evidencia(
    cuerpo: NuevaEvidencia, usuario: _Calidad, db: Db
) -> dict[str, bool]:
    await init_calidad(db)
    if not operaciones.es_enlace(cuerpo.enlace):
        raise HTTPException(400, "El enlace debe empezar por http:// o https://.")
    if not any(t.id == cuerpo.tarea_id for t in await plan.listar_tareas(db)):
        raise HTTPException(404, "No encontré esa tarea.")
    await plan.registrar_evidencia(
        db,
        cuerpo.tarea_id,
        tipo="enlace",
        valor=cuerpo.enlace.strip(),
        referencia=None,
        usuario_id=0,
        usuario_nombre=usuario.correo,
        creado=reloj.ahora().isoformat(),
    )
    return {"ok": True}


@router.get("/alertas")
async def alertas(_: _Calidad, db: Db) -> dict[str, object]:
    """Vista previa: lo que recibiría cada programa. No envía nada."""
    await init_calidad(db)
    hoy = reloj.hoy()
    tareas = await plan.listar_tareas(db)
    return {
        "envio_activo": calidad_settings.alertas_activas,
        "programas": [
            {
                "programa": p,
                "tareas": [
                    _tarea(t, hoy)
                    for t in tareas
                    if t.programa == p
                    and t.estado(hoy) in (Estado.VENCIDA, Estado.PROXIMA)
                ],
            }
            for p in sorted({t.programa for t in tareas})
        ],
    }


@router.get("/reporte")
async def descargar_reporte(programa: str, _: _Calidad, db: Db) -> Response:
    await init_calidad(db)
    encontrado = await plan.buscar_programa(db, programa)
    if encontrado is None:
        raise HTTPException(404, f"No encontré el programa «{programa}».")
    hoy = reloj.hoy()
    contenido = reporte.generar_reporte(
        encontrado, await plan.listar_tareas(db, encontrado), hoy
    )
    return Response(
        contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="reporte-plan-{hoy.isoformat()}.xlsx"'
        },
    )


@router.get("/a-quien")
async def a_quien(q: str, _: _Calidad) -> dict[str, object]:
    tramites = directorio.cargar()
    return {
        "resultados": [
            {
                "tema": t.tema,
                "dependencia": t.dependencia,
                "cargo": t.cargo,
                "correo": t.correo,
                "vigencia": t.vigencia,
            }
            for t in directorio.buscar(q, tramites)
        ],
        "temas": [t.tema for t in tramites],
    }


@router.get("/tablero")
async def tablero(_: _Lectura, db: Db) -> dict[str, object]:
    """Cifras agregadas para la Decana: solo conteos, sin nombres."""
    await init_calidad(db)
    hoy = reloj.hoy()
    tareas = await plan.listar_tareas(db)
    return {
        "servicio": "calidad",
        "titulo": "Plan de mejoramiento",
        "total": _conteo(tareas, hoy),
        "por_programa": [
            {
                "nombre": p,
                "conteo": _conteo([t for t in tareas if t.programa == p], hoy),
            }
            for p in await plan.listar_programas(db)
        ],
    }
