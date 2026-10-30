"""API web del servicio de calidad. Solo se monta con BOT_SERVICIO=calidad."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.servicios.calidad import directorio, plan, plantilla, reloj, reporte
from app.servicios.calidad.avance import corrida as avance
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.db import init_calidad
from app.servicios.calidad.plan import Estado, PlanGuardado
from app.servicios.calidad.plantilla import Accion
from app.servicios.calidad.soportes import corrida
from app.servicios.calidad.soportes.carga import ZipNoValido
from app.servicios.calidad.soportes.plan_acciones import desde_plantilla

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
    return await cifras_tablero(db)


async def cifras_tablero(db: aiosqlite.Connection) -> dict[str, object]:
    """Lo mismo que /tablero; también lo pide actas por /internal/cifras."""
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


# ---------------------------------------------------------------------------
# Revisión de soportes para el cierre del plan (docs/calidad/cierre.md)
# ---------------------------------------------------------------------------

AVISO_APAGADO = (
    "Pendiente del aval de tratamiento de datos. "
    "La revisión de soportes está apagada en este servicio."
)
_OCUPADO = "Hay una revisión en curso. Espere a que termine."


async def _revisor_activo(usuario: _Calidad) -> Usuario:
    # Primero el rol (en `_Calidad`), luego el interruptor. Apagado, además,
    # se borra lo que hubiera quedado en el volumen.
    if not calidad_settings.revisor_activo:
        if corrida.base().exists():
            await asyncio.to_thread(corrida.limpiar)
        raise HTTPException(403, AVISO_APAGADO)
    return usuario


_Revisor = Annotated[Usuario, Depends(_revisor_activo)]


def _estado_revisor() -> dict[str, object]:
    return {
        **corrida.leer_estado(),
        "tope_usd": calidad_settings.revisor_tope_usd,
        "max_mb": calidad_settings.revisor_max_mb,
        "retencion_dias": calidad_settings.revisor_retencion_dias,
    }


@router.get("/revisor")
async def revisor_estado(_: _Revisor) -> dict[str, object]:
    """En qué va la revisión: carga, estimación, pasos y descargas."""
    await corrida.limpiar_de_vez_en_cuando()
    return _estado_revisor()


@router.post("/revisor/soportes")
async def revisor_subir(
    programa: str, request: Request, usuario: _Revisor, db: Db
) -> dict[str, object]:
    """Recibe el zip como cuerpo de la petición (no multipart: así no pasa por
    archivos temporales fuera del volumen) y estima archivos y costo. No
    llama al modelo."""
    pg = await _cargar(db, programa)
    acciones = desde_plantilla(pg.plan)
    maximo = calidad_settings.revisor_max_mb * 1_000_000
    largo = request.headers.get("content-length", "")
    if largo.isdigit() and int(largo) > maximo:
        raise HTTPException(
            413, f"El zip pesa más de {calidad_settings.revisor_max_mb} MB."
        )
    try:
        await corrida.recibir(request.stream(), pg.programa, acciones, usuario.correo)
    except corrida.Ocupado as exc:
        raise HTTPException(409, _OCUPADO) from exc
    except ZipNoValido as exc:
        raise HTTPException(400, str(exc)) from exc
    return _estado_revisor()


class Confirmacion(BaseModel):
    confirmo_costo: bool = False
    # La carga y el costo que la persona vio en pantalla.
    carga_id: str = ""
    costo_usd: float = 0.0


@router.post("/revisor/correr")
async def revisor_correr(
    cuerpo: Confirmacion, usuario: _Revisor, db: Db
) -> dict[str, object]:
    """Lanza la revisión en segundo plano, solo si la persona confirmó el costo
    y la estimación cabe en el tope."""
    if not cuerpo.confirmo_costo or not cuerpo.carga_id:
        raise HTTPException(400, "Confirme el costo estimado antes de iniciar.")
    estado = corrida.leer_estado()
    if not estado.get("programa"):
        raise HTTPException(409, "Primero suba el zip de soportes.")
    pg = await _cargar(db, str(estado["programa"]))
    try:
        # `lanzar` vuelve a comprobar, con el cerrojo, que la carga sigue
        # siendo la que la persona vio y que es de este programa.
        await corrida.lanzar(
            desde_plantilla(pg.plan),
            corrida.crear_cliente(),
            usuario.correo,
            programa=pg.programa,
            carga_id=cuerpo.carga_id,
            costo_visto=cuerpo.costo_usd,
        )
    except corrida.Ocupado as exc:
        raise HTTPException(409, _OCUPADO) from exc
    except corrida.NoSePuede as exc:
        raise HTTPException(409, str(exc)) from exc
    return _estado_revisor()


@router.get("/revisor/descargar/{clave}")
async def revisor_descargar(clave: str, _: _Revisor) -> FileResponse:
    encontrado = corrida.descarga(clave)
    if encontrado is None:
        raise HTTPException(404, "Ese archivo no está listo.")
    ruta, nombre, tipo = encontrado
    return FileResponse(ruta, media_type=tipo, filename=nombre)


@router.delete("/revisor")
async def revisor_borrar(_: _Revisor, cache: bool = False) -> dict[str, object]:
    """Borra soportes y salidas; con `cache=true`, también las descripciones
    guardadas (la próxima corrida las vuelve a pagar)."""
    try:
        await corrida.borrar(con_cache=cache)
    except corrida.Ocupado as exc:
        raise HTTPException(409, _OCUPADO) from exc
    return _estado_revisor()


# ---------------------------------------------------------------------------
# Borrador de la descripción de avance de un corte (docs/calidad/avance-corte.md)
# ---------------------------------------------------------------------------

AVISO_AVANCE_APAGADO = (
    "El borrador de avance del corte está apagado en este servicio: procesa "
    "con el modelo contenido del plan de mejoramiento."
)
_AVANCE_OCUPADO = "Hay un borrador en curso. Espere a que termine."


def _avance_activo(usuario: _Calidad) -> Usuario:
    # Primero el rol (en `_Calidad`), luego el interruptor.
    if not calidad_settings.avance_activo:
        raise HTTPException(403, AVISO_AVANCE_APAGADO)
    return usuario


_Avance = Annotated[Usuario, Depends(_avance_activo)]


def _estado_avance() -> dict[str, object]:
    return {**avance.leer_estado(), "tope_usd": calidad_settings.avance_tope_usd}


def _fecha_corte(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError as exc:
        raise HTTPException(400, "El corte debe ser una fecha AAAA-MM-DD.") from exc


@router.get("/avance")
async def avance_estado(_: _Avance) -> dict[str, object]:
    return _estado_avance()


@router.get("/avance/cortes")
async def avance_cortes(programa: str, _: _Avance, db: Db) -> dict[str, object]:
    return avance.cortes_disponibles(await _cargar(db, programa))


class PedidoAvance(BaseModel):
    programa: str
    corte: str


@router.post("/avance/estimar")
async def avance_estimar(cuerpo: PedidoAvance, _: _Avance, db: Db) -> dict[str, object]:
    """Cuenta qué acciones irían al modelo y cuánto costaría. No lo llama."""
    pg = await _cargar(db, cuerpo.programa)
    acciones, _nombres = await asyncio.to_thread(
        avance.preparar, pg, _fecha_corte(cuerpo.corte)
    )
    est = await asyncio.to_thread(avance.estimacion, acciones)
    return {"programa": pg.programa, **est}


class ConfirmacionAvance(PedidoAvance):
    confirmo_costo: bool = False
    # La cifra que la persona vio en la estimación.
    costo_usd: float | None = None


@router.post("/avance/generar")
async def avance_generar(
    cuerpo: ConfirmacionAvance, usuario: _Avance, db: Db
) -> dict[str, object]:
    """Lanza el borrador en segundo plano, solo si la persona confirmó el costo
    y la estimación cabe en el tope."""
    if not cuerpo.confirmo_costo or cuerpo.costo_usd is None:
        raise HTTPException(400, "Confirme el costo estimado antes de generar.")
    pg = await _cargar(db, cuerpo.programa)
    try:
        await avance.lanzar(
            pg,
            _fecha_corte(cuerpo.corte),
            avance.crear_cliente,
            usuario.correo,
            cuerpo.costo_usd,
        )
    except avance.Ocupado as exc:
        raise HTTPException(409, _AVANCE_OCUPADO) from exc
    except avance.NoSePuede as exc:
        raise HTTPException(409, str(exc)) from exc
    return _estado_avance()


@router.get("/avance/descargar/{clave}")
async def avance_descargar(clave: str, _: _Avance) -> FileResponse:
    encontrado = avance.descarga(clave)
    if encontrado is None:
        raise HTTPException(404, "Ese archivo no está listo.")
    ruta, nombre, tipo = encontrado
    return FileResponse(ruta, media_type=tipo, filename=nombre)


@router.delete("/avance")
async def avance_borrar(_: _Avance) -> dict[str, object]:
    try:
        avance.borrar()
    except avance.Ocupado as exc:
        raise HTTPException(409, _AVANCE_OCUPADO) from exc
    return _estado_avance()
