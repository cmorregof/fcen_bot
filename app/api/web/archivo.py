"""Archivo oficial en Drive: la persona sube la versión firmada (PDF) y la
confirma con un botón. MemorIA no firma ni decide; solo guarda lo que la
persona le entrega, en la carpeta que corresponde. Ver docs/respaldo-drive.md.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.core.config import settings
from app.core.programas import DIRECCIONES, PROGRAMAS
from app.db import repo
from app.services import flujo
from app.services.drive import archivo
from app.services.drive import cliente as drive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/actas", tags=["archivo"])

_Area = Annotated[Usuario, Depends(auth.requiere("administrativa"))]
_Secretaria = Annotated[Usuario, Depends(auth.requiere("secretaria", "admin"))]
_Cualquiera = Annotated[
    Usuario, Depends(auth.requiere("administrativa", "secretaria", "admin"))
]


@router.get("/archivo")
async def estado(usuario: _Cualquiera) -> dict[str, object]:
    """La web muestra los botones de archivar solo si Drive está configurado.
    Al área le dice además a qué programas puede archivar actas."""
    return {
        "activo": drive.configurado(),
        "programas": [
            {"clave": p.clave, "nombre": p.nombre}
            for p in PROGRAMAS.values()
            if p.direccion == usuario.direccion
        ],
    }


async def _leer(subido: UploadFile) -> bytes:
    return await subido.read(archivo.MAX_BYTES + 1)


async def _archivar(doc: archivo.Documento) -> dict[str, object]:
    cliente = drive.obtener()
    if cliente is None:
        raise HTTPException(503, "El archivo en Drive no está configurado.")
    try:
        ruta = await archivo.archivar(cliente, settings.drive_carpeta_id, doc)
    except archivo.DocumentoNoValido as exc:
        raise HTTPException(422, str(exc)) from exc
    except archivo.YaArchivado as exc:
        raise HTTPException(409, str(exc)) from exc
    except drive.ErrorDrive as exc:
        logger.exception("Drive rechazó el archivo")
        raise HTTPException(
            502, "Drive no recibió el archivo. Intente de nuevo."
        ) from exc
    return {"archivado": True, "ruta": ruta}


@router.post("/archivo/acta")
async def acta_firmada(
    usuario: _Area,
    programa: Annotated[str, Form()],
    numero: Annotated[str, Form()],
    fecha: Annotated[date, Form()],
    pdf: Annotated[UploadFile, File()],
) -> dict[str, object]:
    """El acta del comité, ya firmada, de un programa del área de la persona."""
    if usuario.direccion not in DIRECCIONES:
        raise HTTPException(403, "Su usuario no tiene área curricular asignada.")
    if programa not in PROGRAMAS or PROGRAMAS[programa].direccion != usuario.direccion:
        raise HTTPException(404, "Ese programa no es de su área.")
    return await _archivar(
        archivo.Documento(
            tipo="acta",
            numero=numero,
            fecha=fecha,
            programa=programa,
            contenido=await _leer(pdf),
            archivado_por=usuario.correo,
        )
    )


@router.post("/secretaria/casos/{caso_id}/archivo")
async def oficio_firmado(
    caso_id: int,
    usuario: _Secretaria,
    db: Db,
    pdf: Annotated[UploadFile, File()],
) -> dict[str, object]:
    """El oficio o la resolución firmados de un caso. Tipo, número y fecha
    salen de lo que la Secretaría registró (acto, número y expedición)."""
    caso = await repo.get_caso(db, caso_id)
    if caso is None or caso.programa not in PROGRAMAS:
        raise HTTPException(404, "No encontré ese caso o no tiene programa.")
    cur = await db.execute(
        "SELECT acto, numero, fecha_expedicion FROM notificaciones WHERE caso_id = ?",
        (caso_id,),
    )
    fila = await cur.fetchone()
    if fila is None or not fila[1] or not fila[2]:
        raise HTTPException(
            409,
            "Registre y guarde primero el número y la fecha de expedición; "
            "con eso queda expedido y se puede archivar.",
        )
    tipo: archivo.TipoDocumento = "resolucion" if fila[0] == "resolucion" else "oficio"
    resultado = await _archivar(
        archivo.Documento(
            tipo=tipo,
            numero=str(fila[1]),
            fecha=date.fromisoformat(str(fila[2])),
            programa=caso.programa,
            contenido=await _leer(pdf),
            archivado_por=usuario.correo,
        )
    )
    # Ya está en Drive: la línea del caso lo registra (app/services/flujo.py).
    try:
        await flujo.archivar(
            db,
            caso_id,
            rol=usuario.rol,
            persona=usuario.correo,
            detalle=str(resultado.get("ruta") or ""),
        )
    except flujo.TransicionNoPermitida:
        logger.warning("El caso #%s se archivó en Drive fuera de la línea", caso_id)
    return resultado
