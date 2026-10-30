"""Reporte mensual de indicadores del servicio de actas.

El día 1 de cada mes, a las 7:30 a. m. de Bogotá (GitHub Actions), cada área
curricular recibe por Telegram sus cifras del mes anterior y la Vicedecanatura
Académica recibe el consolidado de la Facultad. Solo cifras: sin nombres ni
documentos. Viene apagado: se enciende con REPORTE_MENSUAL_ACTIVO=true.

Se registra por destino (cada área y la Vicedecanatura) a quién ya salió el
reporte de cada mes: un reintento envía solo a los que faltan, y si algo falla
a mitad de camino no se pierde el mes.

El envío y la lista de la decanatura son los del resumen semanal
(`resumen.enviar_a`).
"""

from __future__ import annotations

import logging
from datetime import date
from html import escape

import aiosqlite

from app.core.config import settings
from app.core.programas import DIRECCIONES
from app.db import repo
from app.services import indicadores, resumen

logger = logging.getLogger(__name__)


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


_VICEDECANATURA = "vicedecanatura"


async def _ya_enviados(db: aiosqlite.Connection, mes: str) -> set[str]:
    cur = await db.execute(
        "SELECT destino FROM reportes_mensuales WHERE mes = ?", (mes,)
    )
    return {str(f[0]) for f in await cur.fetchall()}


async def enviar(db: aiosqlite.Connection, hoy: date) -> dict[str, object]:
    """Para el cron del día 1. Cada área recibe solo sus cifras."""
    if not settings.reporte_mensual_activo:
        return {"activo": False, "enviados": 0}
    clave_mes = indicadores.mes_anterior(hoy).desde.strftime("%Y-%m")
    destinos: dict[str, list[int]] = {
        clave: [u.telegram_id for u in await repo.usuarios_de(db, clave)]
        for clave in DIRECCIONES
    }
    destinos[_VICEDECANATURA] = sorted(settings.ids_vicedecanatura)
    hechos = await _ya_enviados(db, clave_mes)
    faltan = [d for d, ids in destinos.items() if ids and d not in hechos]
    if hechos and not faltan:
        return {"activo": True, "mes": clave_mes, "ya_enviado": True, "enviados": 0}

    salida: dict[str, int] = {}
    for destino in faltan:
        direccion = None if destino == _VICEDECANATURA else destino
        try:
            texto = await armar(db, hoy, direccion)
            n = await resumen.enviar_a(destinos[destino], texto)
            if n:
                # Se registra apenas sale: un fallo posterior no lo repite.
                await db.execute(
                    "INSERT OR IGNORE INTO reportes_mensuales (mes, destino,"
                    " enviados) VALUES (?, ?, ?)",
                    (clave_mes, destino, n),
                )
                await db.commit()
        except Exception:
            # Sin registro: el próximo intento lo vuelve a enviar.
            logger.exception("No pude enviar el reporte mensual a %s", destino)
            n = 0
        salida[destino] = n
    areas = {d: salida.get(d, 0) for d in DIRECCIONES}
    consolidado = salida.get(_VICEDECANATURA, 0)
    return {
        "activo": True,
        "mes": clave_mes,
        "areas": areas,
        "vicedecanatura": consolidado,
        "enviados": sum(salida.values()),
        "pendientes": sorted(d for d in faltan if not salida.get(d)),
    }
