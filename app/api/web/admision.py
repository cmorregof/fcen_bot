"""API web del servicio de admisión. Solo se monta con BOT_SERVICIO=admision.

Los admitidos no tienen cuenta: aceptan el aviso de datos y reciben una sesión
anónima. Los documentos se revisan en memoria; solo se cuentan métricas.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.api.web import auth
from app.api.web.auth import Admitido, Db, Usuario
from app.api.web.config import web_settings
from app.servicios import admision
from app.servicios.admision import almacen, chequeo, flujo
from app.servicios.admision.config import config

router = APIRouter(prefix="/admision")

_Responsable = Annotated[Usuario, Depends(auth.requiere("admision", "admin"))]
_Lectura = Annotated[Usuario, Depends(auth.requiere("admision", "admin", "decanatura"))]
_AdmitidoDep = Annotated[Admitido, Depends(auth.admitido_actual)]


def _lista() -> list[dict[str, object]]:
    return [d.model_dump() for d in chequeo.cargar().documentos]


# ---------------------------------------------------------------------------
# Límite de uso de la parte pública (cada pregunta o revisión llama al modelo)
# ---------------------------------------------------------------------------

LIMITES_POR_HORA = {"consentimiento": 30, "preguntar": 20, "revisar": 10}
_usos: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _ip(request: Request) -> str:
    # En Railway la petición llega por un proxy: la IP real es la primera.
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada.strip():
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


def limitar(accion: str, request: Request) -> None:
    """Corta con 429 si una IP supera el límite por hora de esa acción."""
    ahora = time.monotonic()
    usos = _usos[(accion, _ip(request))]
    while usos and ahora - usos[0] > 3600:
        usos.popleft()
    if len(usos) >= LIMITES_POR_HORA[accion]:
        raise HTTPException(
            429, "Hizo muchas consultas seguidas. Intente de nuevo en un rato."
        )
    usos.append(ahora)


def reiniciar_limites() -> None:
    _usos.clear()


# ---------------------------------------------------------------------------
# Admitidos (sin cuenta)
# ---------------------------------------------------------------------------


@router.get("/aviso")
async def aviso() -> dict[str, object]:
    return {
        "aviso": config.aviso_path.read_text(encoding="utf-8").strip(),
        "proposito": admision.PROPOSITO,
        "contacto": config.contacto,
        "documentos": [
            {"clave": d.clave, "nombre": d.nombre} for d in chequeo.cargar().documentos
        ],
        "max_mb": config.max_bytes // 1_000_000,
    }


class Consentimiento(BaseModel):
    acepto: bool
    menor: bool
    acudiente: bool = False


@router.post("/consentimiento")
async def consentimiento(
    cuerpo: Consentimiento, db: Db, request: Request
) -> dict[str, object]:
    limitar("consentimiento", request)
    await almacen.asegurar_tablas(db)
    if not cuerpo.acepto:
        await almacen.contar(db, "rechazos")
        return {"token": None}
    await almacen.contar(db, "consentimientos")
    if cuerpo.menor:
        await almacen.contar(db, "menores")
    token = auth.firmar(
        {"tipo": "admitido", "menor": cuerpo.menor, "acudiente": cuerpo.acudiente},
        web_settings.admitido_horas,
    )
    return {"token": token, "puede_revisar": not cuerpo.menor or cuerpo.acudiente}


class Pregunta(BaseModel):
    texto: str


@router.post("/preguntar")
async def preguntar(
    cuerpo: Pregunta, _: _AdmitidoDep, db: Db, request: Request
) -> dict[str, object]:
    await almacen.asegurar_tablas(db)
    texto = cuerpo.texto.strip()[:2000]
    if not texto:
        raise HTTPException(400, "Escriba su pregunta.")
    limitar("preguntar", request)
    resp = await flujo.responder(db, admision.modelo(), texto)
    return {
        "estado": resp.estado,
        "credenciales": resp.credenciales,
        "respuesta": resp.texto,
        "citas": resp.citas,
        "contacto": config.contacto,
    }


@router.post("/revisar")
async def revisar(
    admitido: _AdmitidoDep,
    db: Db,
    clave: Annotated[str, Form()],
    archivo: Annotated[UploadFile, File()],
    request: Request,
) -> dict[str, object]:
    await almacen.asegurar_tablas(db)
    if admitido.menor and not admitido.acudiente:
        raise HTTPException(
            403, "Para revisar documentos se necesita la aceptación de su acudiente."
        )
    limitar("revisar", request)
    datos = await archivo.read(config.max_bytes + 1)
    if len(datos) > config.max_bytes:
        await almacen.contar(db, "error_peso")
        raise HTTPException(
            400,
            f"El archivo pesa demasiado; el máximo es {config.max_bytes // 1_000_000} MB.",
        )
    resultado = await flujo.revisar(db, admision.modelo(), datos, clave)
    del datos
    if resultado.estado == "tipo_desconocido":
        raise HTTPException(400, "Elija el tipo de documento de la lista.")
    return {
        "estado": resultado.estado,
        "documento": resultado.nombre,
        "problemas": resultado.problemas,
        "bien": [{"punto": i.punto, "detalle": i.detalle} for i in resultado.bien],
        "corregir": [
            {"punto": i.punto, "detalle": i.detalle} for i in resultado.corregir
        ],
        "aviso": flujo.AVISO_REVISION,
    }


# ---------------------------------------------------------------------------
# Responsable del proceso
# ---------------------------------------------------------------------------


@router.get("/metricas")
async def metricas(_: _Responsable, db: Db) -> dict[str, object]:
    await almacen.asegurar_tablas(db)
    return {"metricas": await almacen.totales(db)}


@router.get("/chequeo")
async def lista_chequeo(_: _Responsable) -> dict[str, object]:
    return {"documentos": _lista()}


@router.get("/tablero")
async def tablero(_: _Lectura, db: Db) -> dict[str, object]:
    await almacen.asegurar_tablas(db)
    m = await almacen.totales(db)
    claves = (
        "consentimientos",
        "preguntas",
        "preguntas_sin_respuesta",
        "documentos_revisados",
        "documentos_con_errores",
    )
    return {
        "servicio": "admision",
        "titulo": "Admisión: documentos de admitidos",
        "total": {k: m.get(k, 0) for k in claves},
        "por_programa": [],
    }
