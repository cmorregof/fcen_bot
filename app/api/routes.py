from __future__ import annotations

import hmac
import logging
import os
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import JSONResponse

from app.core.conexion import probar_postgres, servidor_sin_credenciales
from app.core.config import settings
from app.db.session import connect
from app.schemas.telegram import Update
from app.services import borrador, indicadores, reporte_mensual, resumen
from app.services.drive import cliente as drive
from app.services.drive import respaldo
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


@router.post("/internal/reporte-mensual")
async def reporte_mensual_ruta(
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
        resultado = await reporte_mensual.enviar(db, indicadores.hoy_local())
    finally:
        await db.close()
    return {"ok": True, **resultado}


@router.post("/internal/vigia-semanal")
async def vigia_semanal(
    x_cron_secret: str | None = Header(None),
) -> dict[str, object]:
    """Vigía de oportunidades: busca, verifica y arma el borrador del boletín.
    No publica nada (docs/oportunidades.md)."""
    if not settings.internal_cron_secret or not hmac.compare_digest(
        (x_cron_secret or "").encode(), settings.internal_cron_secret.encode()
    ):
        raise HTTPException(status_code=403, detail="secreto inválido")
    if settings.bot_servicio != "oportunidades":
        raise HTTPException(status_code=404, detail="no aplica a este servicio")
    from app.servicios.oportunidades import buscador
    from app.servicios.oportunidades.config import config as oportunidades

    if not oportunidades.vigia_activa:
        return {"ok": True, "activo": False}
    db = await connect()
    try:
        from app.servicios.oportunidades.db import init_oportunidades

        await init_oportunidades(db)
        corrida_id = await buscador.iniciar(db, "cron")
    except buscador.CorridaEnCurso as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        await db.close()
    resultado = await buscador.ejecutar(corrida_id, indicadores.hoy_local())
    return {"ok": True, "activo": True, **resultado}


@router.post("/internal/respaldo-drive")
async def respaldo_drive(
    x_cron_secret: str | None = Header(None),
) -> dict[str, object]:
    """Copia nocturna de la base de este servicio en Drive. Sin las variables
    DRIVE_*, responde activo=false y no hace nada (docs/respaldo-drive.md)."""
    if not settings.internal_cron_secret or not hmac.compare_digest(
        (x_cron_secret or "").encode(), settings.internal_cron_secret.encode()
    ):
        raise HTTPException(status_code=403, detail="secreto inválido")
    try:
        resultado = await respaldo.respaldar(drive.obtener(), indicadores.hoy_local())
    except (drive.ErrorDrive, OSError, sqlite3.Error, respaldo.ErrorVolcado) as exc:
        logger.exception("Falló el respaldo en Drive")
        raise HTTPException(status_code=502, detail=f"respaldo fallido: {exc}") from exc
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


@router.get("/health", response_model=None)
async def health() -> dict[str, object] | JSONResponse:
    postgres = bool(settings.database_url)
    sin_volumen = sin_volumen_en_railway()
    base = await _base()
    # Con Postgres la base no vive en el volumen: falta de volumen no tumba el
    # servicio (media y out sí se pierden en cada despliegue; se avisa).
    error = base.get("error") or (
        None
        if postgres or not sin_volumen
        else f"{settings.data_dir} no es un volumen montado."
    )
    cuerpo: dict[str, object] = {
        "ok": error is None,
        "servicio": settings.bot_servicio,
        "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:7],
        "modelo": settings.extraction_model,
        "modelo_configurado": bool(settings.anthropic_api_key),
        "telegram_configurado": bool(settings.telegram_bot_token),
        "periodo": settings.periodo_actual,
        "periodo_inicio": settings.periodo_inicio.isoformat()
        if settings.periodo_inicio
        else None,
        "base": base,
        "almacenamiento": _almacenamiento(),
    }
    if postgres and sin_volumen:
        cuerpo["aviso"] = (
            f"{settings.data_dir} no es un volumen montado: los archivos de media "
            "y out se pierden en cada despliegue."
        )
    if error:
        # Sin volumen (con SQLite), cada despliegue arranca con la base vacía;
        # sin Postgres, el servicio no puede leer ni guardar nada. Al fallar el
        # healthcheck, Railway no reemplaza el despliegue que está corriendo.
        cuerpo["error"] = error
        return JSONResponse(cuerpo, status_code=503)
    return cuerpo


async def _base() -> dict[str, object]:
    """Motor y ubicación de la base, sin credenciales."""
    if not settings.database_url:
        return {"motor": "sqlite", "db_path": str(settings.db_path)}
    fallo = await probar_postgres(settings.database_url, settings.db_schema)
    base: dict[str, object] = {
        "motor": "postgres",
        "esquema": settings.db_schema,
        "servidor": servidor_sin_credenciales(settings.database_url),
        "conectada": fallo is None,
    }
    if fallo:
        base["error"] = f"No hay conexión con Postgres ({fallo})."
    return base


def sin_volumen_en_railway() -> bool:
    """En Railway los datos deben vivir en un volumen montado en DATA_DIR."""
    if not os.environ.get("RAILWAY_ENVIRONMENT"):
        return False
    return not os.path.ismount(settings.data_dir)


def _almacenamiento() -> dict[str, object]:
    """Qué hay en el volumen: las bases SQLite (rutas y tamaños, sin
    contenido) sirven para detectar una base huérfana; con Postgres, la
    SQLite que queda es la de antes del corte."""
    raiz = settings.data_dir
    bases = sorted(
        str(b.relative_to(raiz)) + f" ({b.stat().st_size // 1024} kB)"
        for patron in ("*.db", "*/*.db", "*/*/*.db")
        for b in raiz.glob(patron)
    )
    return {
        "data_dir": str(raiz),
        "volumen_montado": os.path.ismount(raiz),
        "db_path": str(settings.db_path),
        "bases": bases,
    }
