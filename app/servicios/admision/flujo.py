"""Preguntas y revisión de documentos, sin depender del canal.

Telegram y la web llaman a estas funciones y presentan el resultado a su
manera. Aquí se cuentan las métricas; nunca se guarda texto ni contenido.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import aiosqlite

from app.servicios.admision import almacen, archivo, chequeo, filtro, fuentes
from app.servicios.admision.modelo import ItemChequeo, Modelo, RevisionDocumento

logger = logging.getLogger(__name__)


@dataclass
class Respuesta:
    estado: Literal["ok", "sin_respuesta", "sin_fuentes", "error", "vacia"]
    credenciales: bool = False
    texto: str = ""
    citas: list[str] = field(default_factory=list)


async def credenciales(db: aiosqlite.Connection, texto: str) -> filtro.Filtrado:
    """Filtra correo y contraseña; si los encuentra, lo cuenta."""
    filtrado = filtro.filtrar(texto)
    if filtrado.credenciales:
        await almacen.contar(db, "credenciales_bloqueadas")
    return filtrado


async def responder(db: aiosqlite.Connection, modelo: Modelo, texto: str) -> Respuesta:
    filtrado = await credenciales(db, texto)
    if filtrado.credenciales and not filtro.tiene_contenido(filtrado.texto):
        return Respuesta("vacia", credenciales=True)
    await almacen.contar(db, "preguntas")
    try:
        contexto = await fuentes.cargar()
    except (OSError, RuntimeError):
        logger.exception("No se pudieron leer las fuentes")
        return Respuesta("sin_fuentes", filtrado.credenciales)
    resp = await modelo.responder(contexto, filtrado.texto)
    if resp is None:
        return Respuesta("error", filtrado.credenciales)
    if not resp.cubierta or not resp.citas:
        await almacen.contar(db, "preguntas_sin_respuesta")
        return Respuesta("sin_respuesta", filtrado.credenciales)
    return Respuesta("ok", filtrado.credenciales, resp.respuesta, list(resp.citas))


@dataclass
class Revision:
    estado: Literal["ok", "problemas", "sin_fuentes", "error", "tipo_desconocido"]
    nombre: str = ""
    problemas: list[str] = field(default_factory=list)
    bien: list[ItemChequeo] = field(default_factory=list)
    corregir: list[ItemChequeo] = field(default_factory=list)


async def _registrar_errores(
    db: aiosqlite.Connection, resultado: RevisionDocumento
) -> None:
    corregir = [i for i in resultado.items if i.estado != "ok"]
    if corregir:
        await almacen.contar(db, "documentos_con_errores")
    for item in corregir:
        await almacen.contar(db, f"error_{item.tipo_error or 'otro'}")


async def revisar(
    db: aiosqlite.Connection, modelo: Modelo, datos: bytes, clave: str
) -> Revision:
    """Revisa un documento en memoria. Los bytes no se guardan."""
    doc = chequeo.cargar().buscar(clave)
    if doc is None:
        return Revision("tipo_desconocido")
    revisado = archivo.revisar(datos)
    if revisado.problemas:
        await almacen.contar(db, "documentos_revisados")
        for p in revisado.problemas:
            await almacen.contar(db, f"error_{p.tipo}")
        return Revision(
            "problemas", doc.nombre, [p.mensaje for p in revisado.problemas]
        )
    try:
        contexto = await fuentes.cargar()
    except (OSError, RuntimeError):
        logger.exception("No se pudieron leer las fuentes")
        return Revision("sin_fuentes", doc.nombre)
    resultado = await modelo.revisar(contexto, doc, revisado)
    revisado.datos = b""
    await almacen.contar(db, "documentos_revisados")
    if resultado is None:
        return Revision("error", doc.nombre)
    await _registrar_errores(db, resultado)
    return Revision(
        "ok",
        doc.nombre,
        bien=[i for i in resultado.items if i.estado == "ok"],
        corregir=[i for i in resultado.items if i.estado != "ok"],
    )


AVISO_REVISION = (
    "Esto es una revisión visual: no puedo decir si el documento es "
    "auténtico ni válido. La revisión oficial es la de la Universidad."
)
