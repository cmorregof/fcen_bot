"""Operaciones sobre un caso de actas que comparten Telegram y la web.

Procesar y corregir llaman al modelo, que solo extrae datos. El sentido de la
recomendación lo registra una persona con un botón.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.conexion import Conexion
from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.db import repo
from app.schemas.caso import Caso, EstadoCaso
from app.services import extraccion, flujo, reglas

logger = logging.getLogger(__name__)


def analizar(caso: Caso) -> reglas.Analisis | None:
    """Reglas deterministas sobre un caso ya extraído."""
    if caso.extraccion is None:
        return None
    return reglas.analizar(
        caso.extraccion,
        PROGRAMAS.get(caso.programa or ""),
        periodo_inicio=settings.periodo_inicio,
        hay_imagenes=bool(caso.imagenes),
        texto_original=caso.texto,
        jurados_minimo=settings.jurados_minimo,
    )


@dataclass
class Resultado:
    caso: Caso
    error: str | None = None


async def procesar(db: Conexion, caso: Caso) -> Resultado:
    """Lee el caso con el modelo. Si falla, el caso queda abierto con el error."""
    await repo.set_estado_caso(db, caso.id, EstadoCaso.PROCESANDO)
    try:
        salida = await extraccion.extraer_caso(db, caso)
    except Exception as exc:
        logger.exception("Falló la extracción del caso %s", caso.id)
        salida = extraccion.SalidaExtraccion(None, None, f"error inesperado ({exc})")
    if salida.extraccion is None:
        await repo.set_estado_caso(db, caso.id, EstadoCaso.ABIERTO, error=salida.error)
        return Resultado(caso, salida.error or "error desconocido")
    await repo.guardar_extraccion(
        db,
        caso.id,
        salida.extraccion,
        salida.programa.clave if salida.programa else None,
    )
    # Con la lectura lista, el caso entra al comité (si la prerrevisión no es
    # obligatoria): app/services/flujo.py.
    await flujo.lectura_lista(db, caso.id)
    actualizado = await repo.get_caso(db, caso.id)
    assert actualizado is not None
    return Resultado(actualizado)


async def corregir(db: Conexion, caso: Caso, texto: str) -> Resultado:
    """Aplica una corrección en lenguaje natural a un caso ya procesado."""
    salida = await extraccion.corregir_caso(db, caso, texto)
    if salida.extraccion is None:
        return Resultado(caso, salida.error or "error desconocido")
    programa = salida.programa.clave if salida.programa else caso.programa
    await repo.actualizar_extraccion(db, caso.id, salida.extraccion, programa)
    actualizado = await repo.get_caso(db, caso.id)
    assert actualizado is not None
    return Resultado(actualizado)


def tratamiento_de(caso: Caso, miembro: str) -> str | None:
    programa = PROGRAMAS.get(caso.programa or "")
    for m in programa.miembros if programa else ():
        if m.nombre == miembro:
            return m.tratamiento
    return None
