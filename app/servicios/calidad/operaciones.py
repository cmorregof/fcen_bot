"""Operaciones del plan que comparten Telegram y la web.

Cada canal solo traduce: recibe el archivo o el texto, llama aquí y presenta
el resultado a su manera.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from app.servicios.calidad import plan, reloj


@dataclass
class VistaPrevia:
    errores: list[str]
    filas: list[plan.FilaPlan]
    resumen: plan.Resumen | None


async def previsualizar(db: aiosqlite.Connection, contenido: bytes) -> VistaPrevia:
    """Lee el Excel y compara con lo guardado, sin guardar nada."""
    lectura = plan.leer_plan(contenido)
    if lectura.errores:
        return VistaPrevia(lectura.errores, [], None)
    return VistaPrevia([], lectura.filas, await plan.resumir(db, lectura.filas))


async def guardar_plan(
    db: aiosqlite.Connection,
    filas: list[plan.FilaPlan],
    *,
    archivo: str,
    usuario_id: int,
) -> plan.Resumen:
    """Guarda el plan ya revisado por la persona. Devuelve lo que cambió."""
    resumen = await plan.resumir(db, filas)
    await plan.aplicar_importacion(
        db,
        filas,
        archivo=archivo,
        usuario_id=usuario_id,
        creado=reloj.ahora().isoformat(),
    )
    return resumen


def mensaje_guardado(resumen: plan.Resumen) -> str:
    return (
        f"Plan guardado: {len(resumen.nuevas)} nuevas, "
        f"{len(resumen.actualizadas)} actualizadas, {resumen.sin_cambios} sin cambios. "
        "El historial conserva lo que cambió."
    )


def es_enlace(texto: str) -> bool:
    return texto.strip().lower().startswith(("http://", "https://"))
