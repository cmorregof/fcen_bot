"""Reporte mensual de indicadores del servicio de actas.

El día 1 de cada mes, a las 7:30 a. m. de Bogotá (GitHub Actions), cada área
curricular recibe por Telegram sus cifras del mes anterior y la Vicedecanatura
Académica recibe el consolidado de la Facultad. Solo cifras: sin nombres ni
documentos. Se apaga con REPORTE_MENSUAL_ACTIVO=false.

El envío y la lista de la decanatura son los del resumen semanal
(`resumen.enviar_a`).
"""

from __future__ import annotations

from datetime import date
from html import escape

import aiosqlite

from app.core.config import settings
from app.core.programas import DIRECCIONES
from app.db import repo
from app.services import indicadores, resumen


async def armar(
    db: aiosqlite.Connection, hoy: date, direccion: str | None = None
) -> str:
    """Cifras del mes anterior y, si se conoce, el acumulado del periodo."""
    mes = indicadores.mes_anterior(hoy)
    extra: list[str] = []
    periodo = indicadores.periodo_academico(hoy)
    if periodo is not None and periodo.desde < mes.desde:
        acumulado = await indicadores.reporte(db, periodo, hoy, direccion)
        extra = [
            f"<b>Acumulado del {escape(periodo.etiqueta)}</b> (desde el "
            f"{indicadores.fecha_larga(periodo.desde)})",
            *indicadores.lineas_total(acumulado),
        ]
    return indicadores.formatear(
        await indicadores.reporte(db, mes, hoy, direccion),
        titulo="Reporte mensual · indicadores del servicio de actas",
        extra=extra,
    )


async def enviar(db: aiosqlite.Connection, hoy: date) -> dict[str, object]:
    """Para el cron del día 1. Cada área recibe solo sus cifras."""
    if not settings.reporte_mensual_activo:
        return {"activo": False, "enviados": 0}
    mes = indicadores.mes_anterior(hoy)
    areas: dict[str, int] = {}
    for clave in DIRECCIONES:
        ids = [u.telegram_id for u in await repo.usuarios_de(db, clave)]
        areas[clave] = (
            await resumen.enviar_a(ids, await armar(db, hoy, clave)) if ids else 0
        )
    vicedecanatura = sorted(settings.ids_vicedecanatura)
    consolidado = (
        await resumen.enviar_a(vicedecanatura, await armar(db, hoy))
        if vicedecanatura
        else 0
    )
    return {
        "activo": True,
        "mes": mes.desde.strftime("%Y-%m"),
        "areas": areas,
        "vicedecanatura": consolidado,
        "enviados": sum(areas.values()) + consolidado,
    }
