from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from app.core.config import settings
from app.db.session import connect
from app.schemas.telegram import Update
from app.services import borrador, resumen
from app.servicios import despachar_update
from app.servicios.calidad import alertas as alertas_calidad
from app.servicios.calidad import reloj as reloj_calidad

logger = logging.getLogger(__name__)
router = APIRouter()


async def _procesar_en_fondo(update: Update) -> None:
    db = await connect()
    try:
        await despachar_update(db, update)
    except Exception:
        logger.exception("Error procesando el update %s", update.update_id)
    finally:
        await db.close()


@router.post("/webhook", status_code=200)
async def webhook(
    update: Update,
    tareas: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> dict[str, bool]:
    if (
        not settings.telegram_webhook_secret
        or x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=403, detail="secreto inválido")
    # Se responde de inmediato; leer un caso puede tardar más que el plazo
    # de Telegram. Los reintentos se descartan por update_id.
    tareas.add_task(_procesar_en_fondo, update)
    return {"ok": True}


@router.post("/internal/borrador-diario")
async def borrador_diario(
    x_cron_secret: str | None = Header(None),
) -> dict[str, object]:
    if (
        not settings.internal_cron_secret
        or x_cron_secret != settings.internal_cron_secret
    ):
        raise HTTPException(status_code=403, detail="secreto inválido")
    if settings.bot_servicio != "actas":
        # El borrador diario es del servicio de actas; los demás no lo tienen.
        raise HTTPException(status_code=404, detail="no aplica a este servicio")
    db = await connect()
    try:
        enviados = await borrador.entrega_diaria(db)
    finally:
        await db.close()
    return {"ok": True, "borradores": enviados}


@router.post("/internal/alerta-quincenal")
async def alerta_quincenal(
    x_cron_secret: str | None = Header(None),
) -> dict[str, object]:
    if (
        not settings.internal_cron_secret
        or x_cron_secret != settings.internal_cron_secret
    ):
        raise HTTPException(status_code=403, detail="secreto inválido")
    if settings.bot_servicio != "calidad":
        raise HTTPException(status_code=404, detail="no aplica a este servicio")
    db = await connect()
    try:
        resultado = await alertas_calidad.enviar_alertas(db, reloj_calidad.hoy())
    finally:
        await db.close()
    return {"ok": True, **resultado}


@router.post("/internal/resumen-semanal")
async def resumen_semanal(
    x_cron_secret: str | None = Header(None),
) -> dict[str, object]:
    if (
        not settings.internal_cron_secret
        or x_cron_secret != settings.internal_cron_secret
    ):
        raise HTTPException(status_code=403, detail="secreto inválido")
    if settings.bot_servicio != "actas":
        raise HTTPException(status_code=404, detail="no aplica a este servicio")
    db = await connect()
    try:
        resultado = await resumen.enviar_semanal(db)
    finally:
        await db.close()
    return {"ok": True, **resultado}


@router.get("/internal/cifras")
async def cifras(
    x_resumen_secret: str | None = Header(None),
) -> dict[str, object]:
    """Conteos agregados de calidad o admisión para el resumen de actas.

    Lo mismo que muestra /tablero, sin nombres; actas nunca lee otra base.
    """
    if not settings.resumen_secret or not hmac.compare_digest(
        (x_resumen_secret or "").encode(), settings.resumen_secret.encode()
    ):
        raise HTTPException(status_code=403, detail="secreto inválido")
    db = await connect()
    try:
        if settings.bot_servicio == "calidad":
            from app.api.web.calidad import cifras_tablero
        elif settings.bot_servicio == "admision":
            from app.api.web.admision import cifras_tablero
        else:
            raise HTTPException(status_code=404, detail="no aplica a este servicio")
        return await cifras_tablero(db)
    finally:
        await db.close()


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "servicio": settings.bot_servicio,
        "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:7],
        "modelo": settings.extraction_model,
        "modelo_configurado": bool(settings.anthropic_api_key),
        "telegram_configurado": bool(settings.telegram_bot_token),
        "periodo": settings.periodo_actual,
        "periodo_inicio": settings.periodo_inicio.isoformat()
        if settings.periodo_inicio
        else None,
    }
