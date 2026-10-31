"""API web del servicio de oportunidades. Solo se monta con BOT_SERVICIO=oportunidades.

Toda acción que cambia el estado de una oferta o publica el boletín la hace una
persona con rol «oportunidades» (o admin). La decanatura solo consulta.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field, HttpUrl

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.core.programas import PROGRAMAS
from app.services.indicadores import hoy_local
from app.servicios.oportunidades import (
    almacen,
    boletin,
    buscador,
    fuentes,
    verificador,
)
from app.servicios.oportunidades.config import config
from app.servicios.oportunidades.db import init_oportunidades
from app.servicios.oportunidades.modelo import (
    ESTADOS,
    NOMBRE_ESTADO,
    NOMBRE_TIPO,
    Modalidad,
    TipoOferta,
)

router = APIRouter(prefix="/oportunidades")

_Responsable = Annotated[Usuario, Depends(auth.requiere("oportunidades", "admin"))]
_Lectura = Annotated[
    Usuario, Depends(auth.requiere("oportunidades", "admin", "decanatura"))
]


async def _db(db: Db) -> Db:
    await init_oportunidades(db)
    return db


_Base = Annotated[Any, Depends(_db)]


def _hoy() -> date:
    return hoy_local()


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, str(exc))
    return HTTPException(409, str(exc))


# ---------------------------------------------------------------------------
# Catálogos y resumen
# ---------------------------------------------------------------------------


@router.get("/catalogos")
async def catalogos(_: _Lectura) -> dict[str, object]:
    return {
        "programas": {k: p.nombre for k, p in PROGRAMAS.items()},
        "tipos": NOMBRE_TIPO,
        "estados": NOMBRE_ESTADO,
        "tipos_entidad": list(almacen.TIPOS_ENTIDAD),
        "vigia_activa": config.vigia_activa,
    }


@router.get("/resumen")
async def resumen(_: _Lectura, db: _Base) -> dict[str, object]:
    """Cifras agregadas: insumo del informe estudiantes–empresas."""
    ofertas = await almacen.listar(db)
    vivas = [o for o in ofertas if o["estado"] != "descartada"]
    por_programa: Counter[str] = Counter()
    for o in vivas:
        por_programa.update(o["programas"] or ["sin_programa"])
    return {
        "por_estado": {e: sum(o["estado"] == e for o in ofertas) for e in ESTADOS},
        "por_tipo": dict(Counter(o["tipo"] for o in vivas)),
        "por_programa": dict(por_programa),
        "por_entidad": dict(Counter(o["entidad"] for o in vivas).most_common(15)),
        "por_fuente": dict(Counter(o["fuente"] for o in vivas)),
    }


@router.get("/tablero")
async def tablero(_: _Lectura, db: _Base) -> dict[str, object]:
    """Para el tablero de la Facultad: cifras, sin nombres."""
    ofertas = await almacen.listar(db)
    estados = ("encontrada", "verificada", "aprobada", "publicada")
    return {
        "servicio": "oportunidades",
        "titulo": "Oportunidades (vigía semanal)",
        "total": {
            NOMBRE_ESTADO[e]: sum(o["estado"] == e for o in ofertas) for e in ESTADOS
        },
        "por_programa": [
            {
                "nombre": p.nombre,
                "conteo": {
                    NOMBRE_ESTADO[e]: sum(
                        o["estado"] == e and clave in o["programas"] for o in ofertas
                    )
                    for e in estados
                },
            }
            for clave, p in PROGRAMAS.items()
        ],
    }


# ---------------------------------------------------------------------------
# Ofertas y cola de revisión
# ---------------------------------------------------------------------------


@router.get("/cola")
async def cola(_: _Lectura, db: _Base) -> dict[str, object]:
    """Lo que el verificador no pudo dar por bueno, con sus motivos."""
    return {"ofertas": await almacen.listar(db, estado="encontrada")}


@router.get("/ofertas")
async def ofertas(
    _: _Lectura,
    db: _Base,
    estado: str | None = None,
    programa: str | None = None,
) -> dict[str, object]:
    if estado and estado not in ESTADOS:
        raise HTTPException(400, "Estado no válido.")
    return {"ofertas": await almacen.listar(db, estado=estado, programa=programa)}


@router.get("/ofertas/{oferta_id}")
async def oferta(oferta_id: int, _: _Lectura, db: _Base) -> dict[str, object]:
    datos = await almacen.obtener(db, oferta_id)
    if datos is None:
        raise HTTPException(404, "No existe esa oferta.")
    return {"oferta": datos, "historial": await almacen.historial(db, oferta_id)}


class OfertaManual(BaseModel):
    titulo: str = Field(min_length=3, max_length=300)
    entidad: str = Field(min_length=2, max_length=200)
    tipo: TipoOferta
    url: HttpUrl
    programas: list[str] = Field(default_factory=list)
    resumen: str = Field(default="", max_length=1000)
    requisitos: str = Field(default="", max_length=2000)
    fecha_cierre: date | None = None
    modalidad: Modalidad = "sin_dato"
    lugar: str = Field(default="", max_length=200)


@router.post("/ofertas")
async def registrar(
    cuerpo: OfertaManual, usuario: _Responsable, db: _Base
) -> dict[str, object]:
    """Una oferta que llegó por otro medio (correo de una empresa aliada…)."""
    desconocidos = [p for p in cuerpo.programas if p not in PROGRAMAS]
    if desconocidos:
        raise HTTPException(400, f"Programas desconocidos: {desconocidos}")
    oferta_id = await almacen.insertar(
        db,
        almacen.NuevaOferta(
            fuente="manual",
            url=str(cuerpo.url),
            titulo=cuerpo.titulo.strip(),
            entidad=cuerpo.entidad.strip(),
            tipo=cuerpo.tipo,
            programas=cuerpo.programas,
            areas=[],
            resumen=cuerpo.resumen.strip(),
            requisitos=cuerpo.requisitos.strip(),
            fecha_cierre=cuerpo.fecha_cierre.isoformat()
            if cuerpo.fecha_cierre
            else None,
            modalidad=cuerpo.modalidad,
            lugar=cuerpo.lugar.strip(),
            dudas=[],
        ),
        usuario.correo,
    )
    await db.commit()
    motivos = await verificador.revisar(db, oferta_id, _hoy(), None)
    return {"id": oferta_id, "motivos": motivos}


class Edicion(BaseModel):
    titulo: str | None = Field(default=None, min_length=3, max_length=300)
    entidad: str | None = Field(default=None, min_length=2, max_length=200)
    tipo: TipoOferta | None = None
    url: HttpUrl | None = None
    programas: list[str] | None = None
    resumen: str | None = Field(default=None, max_length=1000)
    requisitos: str | None = Field(default=None, max_length=2000)
    fecha_cierre: date | None = None
    modalidad: Modalidad | None = None
    lugar: str | None = Field(default=None, max_length=200)


@router.put("/ofertas/{oferta_id}")
async def editar(
    oferta_id: int, cuerpo: Edicion, usuario: _Responsable, db: _Base
) -> dict[str, object]:
    """Corrige datos; la oferta vuelve a la cola y se revisa otra vez (sin red)."""
    cambios = cuerpo.model_dump(exclude_none=True)
    if "url" in cambios:
        cambios["url"] = str(cambios["url"])
    if "fecha_cierre" in cambios:
        cambios["fecha_cierre"] = cambios["fecha_cierre"].isoformat()
    try:
        await almacen.editar(db, oferta_id, cambios, usuario.correo)
        await db.commit()
    except (LookupError, almacen.ErrorEstado) as exc:
        raise _error(exc) from None
    motivos = await verificador.revisar(db, oferta_id, _hoy(), None)
    return {"ok": True, "motivos": motivos}


class Nota(BaseModel):
    nota: str = Field(default="", max_length=1000)


class MotivoDescarte(BaseModel):
    motivo: str = Field(min_length=3, max_length=500)


@router.post("/ofertas/{oferta_id}/verificar")
async def verificar(
    oferta_id: int, cuerpo: Nota, usuario: _Responsable, db: _Base
) -> dict[str, bool]:
    try:
        await almacen.verificar_manual(db, oferta_id, usuario.correo, cuerpo.nota)
        await db.commit()
    except (LookupError, almacen.ErrorEstado) as exc:
        raise _error(exc) from None
    return {"ok": True}


@router.post("/ofertas/{oferta_id}/aprobar")
async def aprobar(oferta_id: int, usuario: _Responsable, db: _Base) -> dict[str, bool]:
    try:
        await almacen.aprobar(db, oferta_id, usuario.correo)
        await db.commit()
    except (LookupError, almacen.ErrorEstado) as exc:
        raise _error(exc) from None
    return {"ok": True}


@router.post("/ofertas/{oferta_id}/descartar")
async def descartar(
    oferta_id: int, cuerpo: MotivoDescarte, usuario: _Responsable, db: _Base
) -> dict[str, bool]:
    try:
        await almacen.descartar(db, oferta_id, usuario.correo, cuerpo.motivo)
        await db.commit()
    except (LookupError, almacen.ErrorEstado) as exc:
        raise _error(exc) from None
    return {"ok": True}


# ---------------------------------------------------------------------------
# Entidades y empresas
# ---------------------------------------------------------------------------


class Entidad(BaseModel):
    nombre: str = Field(min_length=2, max_length=200)
    tipo: Literal["empresa", "entidad_publica", "ong", "universidad", "otra"] = (
        "empresa"
    )
    sector: str = Field(default="", max_length=200)
    sitio_web: str = Field(default="", max_length=300)
    aliada: bool = False
    convenio: str = Field(default="", max_length=500)
    notas: str = Field(default="", max_length=1000)


@router.get("/entidades")
async def entidades(_: _Lectura, db: _Base) -> dict[str, object]:
    return {"entidades": await almacen.listar_entidades(db)}


@router.post("/entidades")
async def crear_entidad(
    cuerpo: Entidad, usuario: _Responsable, db: _Base
) -> dict[str, object]:
    try:
        entidad_id = await almacen.guardar_entidad(
            db, cuerpo.model_dump(), usuario.correo
        )
        await db.commit()
    except almacen.ErrorEstado as exc:
        raise _error(exc) from None
    return {"id": entidad_id}


@router.put("/entidades/{entidad_id}")
async def editar_entidad(
    entidad_id: int, cuerpo: Entidad, usuario: _Responsable, db: _Base
) -> dict[str, bool]:
    try:
        await almacen.guardar_entidad(
            db, cuerpo.model_dump(), usuario.correo, entidad_id
        )
        await db.commit()
    except (LookupError, almacen.ErrorEstado) as exc:
        raise _error(exc) from None
    return {"ok": True}


# ---------------------------------------------------------------------------
# Boletín
# ---------------------------------------------------------------------------


@router.get("/boletin")
async def ver_boletin(
    _: _Lectura, db: _Base, semana: str | None = None
) -> dict[str, object]:
    clave = semana or boletin.semana(_hoy())
    return {
        "semana": clave,
        "boletin": await boletin.obtener(db, de_semana=clave),
        "anteriores": await boletin.listar(db),
    }


@router.post("/boletin/borrador")
async def rehacer_borrador(usuario: _Responsable, db: _Base) -> dict[str, object]:
    return await boletin.generar(db, _hoy(), usuario.correo)


@router.post("/boletin/{boletin_id}/aprobar")
async def aprobar_y_publicar(
    boletin_id: int, usuario: _Responsable, db: _Base
) -> dict[str, object]:
    """«Aprobar y publicar»: no envía nada; queda listo para exportar."""
    try:
        hoja = await boletin.aprobar_y_publicar(db, boletin_id, usuario.correo)
    except (LookupError, boletin.ErrorBoletin, almacen.ErrorEstado) as exc:
        raise _error(exc) from None
    return {"boletin": hoja}


@router.get("/boletin/{boletin_id}/exportar", response_model=None)
async def exportar(
    boletin_id: int,
    _: _Lectura,
    db: _Base,
    formato: Literal["texto", "html"] = "texto",
) -> Response:
    hoja = await boletin.obtener(db, boletin_id=boletin_id)
    if hoja is None:
        raise HTTPException(404, "No existe ese boletín.")
    nombre = f"boletin-oportunidades-{hoja['semana']}"
    if formato == "html":
        return Response(
            hoja["html"],
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nombre}.html"'},
        )
    return PlainTextResponse(
        hoja["texto"],
        headers={"Content-Disposition": f'attachment; filename="{nombre}.txt"'},
    )


# ---------------------------------------------------------------------------
# Fuentes y vigía
# ---------------------------------------------------------------------------


@router.get("/fuentes")
async def ver_fuentes(_: _Lectura, db: _Base) -> dict[str, object]:
    lista = fuentes.cargar()
    return {
        "vigia_activa": config.vigia_activa,
        "fuentes": [f.model_dump() for f in lista.fuentes],
        "excluidas": lista.excluidas,
        "corridas": await buscador.corridas(db),
    }


@router.post("/vigia")
async def correr_vigia(
    usuario: _Responsable, db: _Base, tareas: BackgroundTasks
) -> dict[str, object]:
    """Corre la vigía ahora (en segundo plano). Usa las fuentes activas."""
    try:
        corrida_id = await buscador.iniciar(db, f"web: {usuario.correo}")
    except buscador.CorridaEnCurso as exc:
        raise HTTPException(409, str(exc)) from None
    tareas.add_task(_vigia_en_fondo, corrida_id, _hoy())
    return {"corrida": corrida_id}


async def _vigia_en_fondo(corrida_id: int, hoy: date) -> None:
    try:
        await buscador.ejecutar(corrida_id, hoy)
    except Exception:  # ya quedó registrada como fallida
        pass


@router.get("/corridas")
async def ver_corridas(_: _Lectura, db: _Base) -> dict[str, object]:
    return {"corridas": await buscador.corridas(db)}
