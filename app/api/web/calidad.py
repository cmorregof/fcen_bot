"""API web del servicio de calidad. Solo se monta con BOT_SERVICIO=calidad."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.servicios.calidad import directorio, plan, plantilla, reloj, reporte
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.db import init_calidad
from app.servicios.calidad.plan import Estado, PlanGuardado
from app.servicios.calidad.plantilla import Accion

router = APIRouter(prefix="/calidad")

_Calidad = Annotated[Usuario, Depends(auth.requiere("calidad", "admin"))]
_Lectura = Annotated[Usuario, Depends(auth.requiere("calidad", "admin", "decanatura"))]
_MAX_XLSX = 5_000_000


def _fecha(f: date | None) -> str | None:
    return f.isoformat() if f else None


def _accion(pg: PlanGuardado, a: Accion, hoy: date) -> dict[str, object]:
    return {
        "codigo": a.codigo,
        "descripcion": a.descripcion,
        "indicador": a.indicador,
        "responsables": a.responsables,
        "fecha_inicio": _fecha(a.fecha_inicio),
        "fecha_fin": _fecha(a.fecha_fin),
        "fechas_fin_anteriores": [f.isoformat() for f in a.fechas_fin_anteriores],
        "avance": a.avance,
        "estado": plan.calcular_estado(a, hoy).value,
        "proxima": plan.proxima_a_vencer(a, hoy),
        "reprogramada": a.reprogramada,
        "marcas": a.marcas,
        "evidencias": a.evidencias,
        "tareas": len(a.tareas),
        "soportes": [
            {
                "tipo": s.tipo,
                "valor": s.valor,
                "por": s.registrado_nombre,
                "fecha": s.creado,
            }
            for s in pg.soportes.get(a.codigo, [])
        ],
    }


def _resumen(pg: PlanGuardado, hoy: date) -> dict[str, object]:
    """Cifras de un plan: solo conteos y porcentajes, sin nombres de personas."""
    acciones = pg.plan.acciones
    conteo = {e.value: 0 for e in Estado}
    for a in acciones:
        conteo[plan.calcular_estado(a, hoy).value] += 1
    corte = plan.proximo_corte(pg.plan, hoy)
    return {
        "programa": pg.programa,
        "acciones": len(acciones),
        "avance": pg.plan.avance_promedio(),
        "conteo": conteo,
        "reprogramadas": sum(a.reprogramada for a in acciones),
        "proximo_corte": (
            {"fecha": corte[0].isoformat(), "estimado": corte[1]} if corte else None
        ),
    }


async def _cargar(db: Db, programa: str) -> PlanGuardado:
    await init_calidad(db)
    encontrado = await plan.buscar_programa(db, programa)
    guardado = await plan.cargar_plan(db, encontrado) if encontrado else None
    if guardado is None:
        raise HTTPException(404, f"No encontré el programa «{programa}».")
    return guardado


@router.get("/programas")
async def programas(_: _Calidad, db: Db) -> dict[str, object]:
    await init_calidad(db)
    hoy = reloj.hoy()
    return {"programas": [_resumen(pg, hoy) for pg in await plan.listar_planes(db)]}


@router.get("/plan")
async def ver_plan(programa: str, _: _Calidad, db: Db) -> dict[str, object]:
    pg = await _cargar(db, programa)
    hoy = reloj.hoy()
    return {
        **_resumen(pg, hoy),
        "hoy": hoy.isoformat(),
        "archivo": pg.archivo,
        "alertas": pg.plan.alertas,
        "objetivos": [
            {
                "codigo": o.codigo,
                "texto": o.texto,
                "meta": o.meta,
                "acciones": [_accion(pg, a, hoy) for a in o.acciones],
            }
            for o in pg.plan.objetivos
        ],
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
    usuario: _Calidad,
    db: Db,
    archivo: Annotated[UploadFile, File()],
    confirmar: Annotated[bool, Form()] = False,
) -> dict[str, object]:
    """Sin `confirmar` solo muestra qué cambiaría. Con `confirmar` guarda."""
    await init_calidad(db)
    lectura = plantilla.leer_plantilla(await _leer_xlsx(archivo))
    if lectura.errores or lectura.plan is None:
        return {
            "guardado": False,
            "errores": lectura.errores or ["No pude leer el plan."],
        }
    if confirmar:
        r = await plan.aplicar_importacion(
            db,
            lectura.plan,
            archivo=archivo.filename or "plan.xlsx",
            usuario_id=0,
            creado=reloj.ahora().isoformat(),
        )
    else:
        r = await plan.resumir(db, lectura.plan)
    return {
        "guardado": confirmar,
        "errores": [],
        "programa": r.programa,
        "plan_nuevo": r.plan_nuevo,
        "objetivos": r.objetivos,
        "acciones": r.acciones,
        "tareas": r.tareas,
        "avance": r.avance,
        "cronogramas": r.cronogramas,
        "alertas": r.alertas,
        "nuevas": r.nuevas,
        "actualizadas": [{"accion": a, "cambios": c} for a, c in r.actualizadas],
        "sin_cambios": r.sin_cambios,
        "ausentes": r.ausentes,
        "cortes_nuevos": r.cortes_nuevos,
        "cortes_cambiados": r.cortes_cambiados,
    }


class NuevaEvidencia(BaseModel):
    programa: str
    codigo: str
    enlace: str


@router.post("/evidencia")
async def evidencia(
    cuerpo: NuevaEvidencia, usuario: _Calidad, db: Db
) -> dict[str, bool]:
    """Queda pendiente de revisión: no cambia el % de avance."""
    enlace = cuerpo.enlace.strip()
    if not enlace.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "El enlace debe empezar por http:// o https://.")
    pg = await _cargar(db, cuerpo.programa)
    accion = pg.accion(cuerpo.codigo)
    if accion is None:
        raise HTTPException(404, f"No hay una acción {cuerpo.codigo} en ese plan.")
    await plan.registrar_soporte(
        db,
        pg.ids[accion.codigo],
        tipo="enlace",
        valor=enlace,
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
    salida = []
    for pg in await plan.listar_planes(db):
        acciones = [
            _accion(pg, a, hoy)
            for a in pg.plan.acciones
            if plan.calcular_estado(a, hoy) in (Estado.VENCIDA, Estado.NO_FUNCIONO)
            or plan.proxima_a_vencer(a, hoy)
        ]
        salida.append({"programa": pg.programa, "acciones": acciones})
    return {"envio_activo": calidad_settings.alertas_activas, "programas": salida}


@router.get("/reporte")
async def descargar_reporte(programa: str, _: _Calidad, db: Db) -> Response:
    pg = await _cargar(db, programa)
    hoy = reloj.hoy()
    return Response(
        reporte.generar_reporte(pg, hoy),
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
    planes = [_resumen(pg, hoy) for pg in await plan.listar_planes(db)]
    total = {e.value: 0 for e in Estado}
    for p in planes:
        for k, v in p["conteo"].items():  # type: ignore[attr-defined]
            total[k] += v
    return {
        "servicio": "calidad",
        "titulo": "Plan de mejoramiento",
        "total": total,
        "reprogramadas": sum(int(p["reprogramadas"]) for p in planes),  # type: ignore[call-overload]
        "por_programa": [
            {
                "nombre": p["programa"],
                "conteo": p["conteo"],
                "avance": p["avance"],
                "acciones": p["acciones"],
                "reprogramadas": p["reprogramadas"],
            }
            for p in planes
        ],
    }
