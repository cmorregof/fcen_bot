"""API web del servicio de admisión. Solo se monta con BOT_SERVICIO=admision.

Los admitidos no tienen cuenta: aceptan el aviso de datos y reciben una sesión
anónima. Los documentos se revisan en memoria; solo se cuentan métricas.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.api.web import auth
from app.api.web.auth import Admitido, Db, Usuario
from app.api.web.config import web_settings
from app.core.conexion import Conexion
from app.servicios import admision
from app.servicios.admision import almacen, chequeo, flujo, fuentes
from app.servicios.admision.config import config

router = APIRouter(prefix="/admision")

_Responsable = Annotated[Usuario, Depends(auth.requiere("admision", "admin"))]
_Lectura = Annotated[Usuario, Depends(auth.requiere("admision", "admin", "decanatura"))]
_AdmitidoDep = Annotated[Admitido, Depends(auth.admitido_actual)]


def _lista() -> list[dict[str, object]]:
    return [d.model_dump() for d in chequeo.cargar().documentos]


def _resumen(d: chequeo.Documento) -> dict[str, object]:
    return {
        "clave": d.clave,
        "nombre": d.nombre,
        "seccion": d.seccion,
        "tipo": d.tipo,
        "condicion": d.condicion,
        "nota": d.nota,
    }


# ---------------------------------------------------------------------------
# Límite de uso de la parte pública (cada pregunta o revisión llama al modelo)
# ---------------------------------------------------------------------------

# Se fijan con ADMISION_LIMITE_*_HORA. En memoria del proceso: se reinician
# con cada despliegue y suponen una sola réplica.
LIMITES_POR_HORA = {
    "consentimiento": config.limite_consentimiento_hora,
    "preguntar": config.limite_preguntar_hora,
    "revisar": config.limite_revisar_hora,
}
_usos: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _ip(request: Request) -> str:
    """IP del cliente detrás de los proxies de confianza.

    El cliente puede escribir lo que quiera al comienzo de X-Forwarded-For;
    solo las últimas entradas las pone la infraestructura. Por eso se toma la
    que añadió el último proxy confiable, no la primera.
    """
    reenviada = [
        p.strip()
        for p in request.headers.get("x-forwarded-for", "").split(",")
        if p.strip()
    ]
    n = config.proxies_confiables
    if n > 0 and reenviada:
        return reenviada[-min(n, len(reenviada))]
    return request.client.host if request.client else "desconocida"


def limitar(accion: str, request: Request) -> None:
    """Corta con 429 si una IP supera el límite por hora de esa acción."""
    ahora = time.monotonic()
    for clave in [k for k, v in _usos.items() if not v or ahora - v[-1] > 3600]:
        del _usos[clave]  # no acumular IP viejas
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
        "documentos": [_resumen(d) for d in chequeo.cargar().documentos],
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


# ---------------------------------------------------------------------------
# Insumos (listado, lista de chequeo, formato y manual en PDF)
# ---------------------------------------------------------------------------

_NOMBRE_INSUMO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.(pdf|txt|md)$")


def _insumos() -> dict[str, object]:
    archivos = fuentes.diagnosticar()
    presentes = {a.nombre for a in archivos}
    return {
        "carpeta": str(config.insumos_dir),
        "archivos": [vars(a) for a in archivos],
        "faltan": [n for n in fuentes.INSUMOS_ESPERADOS if n not in presentes],
    }


@router.get("/insumos")
async def ver_insumos(_: _Responsable) -> dict[str, object]:
    return _insumos()


@router.post("/insumos")
async def subir_insumo(
    _: _Responsable, archivo: Annotated[UploadFile, File()]
) -> dict[str, object]:
    """Guarda un insumo oficial en la carpeta del volumen.

    Solo documentos públicos de la Universidad (nunca de un admitido). Acepta
    también la caché `<nombre>.ocr.txt` de un PDF escaneado.
    """
    nombre = Path(archivo.filename or "").name
    if not _NOMBRE_INSUMO.match(nombre):
        raise HTTPException(
            400, "Nombre no válido: use el nombre del PDF oficial (o su .ocr.txt)."
        )
    datos = await archivo.read(config.max_bytes_insumo + 1)
    if len(datos) > config.max_bytes_insumo:
        raise HTTPException(400, "El archivo pesa demasiado.")
    if nombre.lower().endswith(".pdf") and not datos.startswith(b"%PDF-"):
        raise HTTPException(400, "El archivo no es un PDF.")
    if not nombre.lower().endswith(".pdf"):
        try:
            datos.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(400, "El texto debe estar en UTF-8.") from None
    carpeta = config.insumos_dir
    carpeta.mkdir(parents=True, exist_ok=True)
    # Escritura atómica: nunca queda un PDF a medias en la carpeta.
    fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".subiendo-")
    with os.fdopen(fd, "wb") as f:
        f.write(datos)
    os.replace(tmp, carpeta / nombre)
    fuentes.olvidar()
    return _insumos()


@router.get("/tablero")
async def tablero(_: _Lectura, db: Db) -> dict[str, object]:
    return await cifras_tablero(db)


async def cifras_tablero(db: Conexion) -> dict[str, object]:
    """Solo conteos; también lo pide actas por /internal/cifras."""
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
