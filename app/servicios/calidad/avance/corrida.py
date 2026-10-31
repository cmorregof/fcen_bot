"""Corrida del borrador de avance pedida desde la web.

Una sola a la vez. Vive en el volumen del revisor (`soportes.corrida.base()`):

    avance/estado.json            en qué va
    avance/borrador_avance.docx   el borrador, para leer
    avance/revision_avance.xlsx   la hoja para aprobar, editar o descartar
    cache/avance/                 propuestas ya pagadas (se borra con la caché)

Estimar no llama al modelo. Generar vuelve a estimar y no corre si la
estimación pasa del tope. El modelo no decide: todo es propuesta.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast

from app.servicios.calidad import reloj
from app.servicios.calidad.avance import borrador as bor
from app.servicios.calidad.avance import fuentes, salidas
from app.servicios.calidad.avance.fuentes import AccionCorte
from app.servicios.calidad.avance.nombres import nombres_en_plan
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.plan import PlanGuardado
from app.servicios.calidad.soportes import corrida as revisor
from app.servicios.calidad.soportes.cliente import ClienteModelo
from app.servicios.calidad.soportes.describir import Cache
from app.servicios.calidad.soportes.indice import leer_indice
from app.servicios.calidad.soportes.modelos import Uso

logger = logging.getLogger(__name__)

DESCARGAS: dict[str, tuple[str, str]] = {
    "docx": ("borrador_avance.docx", revisor.DOCX),
    "xlsx": ("revision_avance.xlsx", revisor.XLSX),
}

_tarea: asyncio.Task[None] | None = None
_ocupado = False  # un lanzamiento o un borrado en curso (antes de crear la tarea)


class Ocupado(Exception):
    """Ya hay un borrador en curso."""


class NoSePuede(Exception):
    """La acción no aplica; el mensaje es para la persona."""


def base() -> Path:
    return revisor.base() / "avance"


def _cache() -> Cache:
    return Cache(revisor.base() / "cache" / "avance")


def corriendo() -> bool:
    return _tarea is not None and not _tarea.done()


def _guardar(estado: dict[str, Any]) -> None:
    ruta = base() / "estado.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    temporal.replace(ruta)


def leer_estado() -> dict[str, Any]:
    try:
        estado: dict[str, Any] = json.loads(
            (base() / "estado.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        estado = {"estado": "vacio"}
    if estado.get("estado") == "corriendo" and not corriendo():
        estado["estado"] = "interrumpido"
    estado["descargas"] = [
        k for k, (nombre, _) in DESCARGAS.items() if (base() / nombre).exists()
    ]
    return estado


def descarga(clave: str) -> tuple[Path, str, str] | None:
    if clave not in DESCARGAS or corriendo():
        return None
    nombre, tipo = DESCARGAS[clave]
    ruta = base() / nombre
    return (ruta, nombre, tipo) if ruta.exists() else None


def borrar() -> None:
    if corriendo() or _ocupado:
        raise Ocupado
    shutil.rmtree(base(), ignore_errors=True)


def cortes_disponibles(pg: PlanGuardado) -> dict[str, Any]:
    """Cortes que el plan ya conoce y el siguiente que le tocaría."""
    from app.servicios.calidad import plan

    proximo = plan.proximo_corte(pg.plan, reloj.hoy())
    return {
        "cortes": [f.isoformat() for f in fuentes.fechas_de_corte(pg)],
        "proximo": (
            {"fecha": proximo[0].isoformat(), "estimado": proximo[1]}
            if proximo
            else None
        ),
    }


def preparar(pg: PlanGuardado, corte: date) -> tuple[list[AccionCorte], set[str]]:
    nombres = nombres_en_plan(pg)
    soportes = leer_indice(revisor.cache(), pg.programa)
    return fuentes.armar(pg, corte, soportes, nombres), nombres


def estimacion(acciones: list[AccionCorte]) -> dict[str, Any]:
    est = bor.estimar(acciones, _cache())
    tope = calidad_settings.avance_tope_usd
    return {
        "acciones": est.acciones,
        "sin_evidencia_nueva": est.sin_evidencia_nueva,
        "al_modelo": est.al_modelo,
        "en_cache": est.en_cache,
        "costo_usd": round(est.costo, 2),
        "tope_usd": tope,
        "excede_tope": bor.excede_tope(est, tope),
    }


class _SinModelo:
    """Cuando ninguna acción va al modelo no hace falta la API key."""

    async def llamar(self, **_: Any) -> Any:
        raise RuntimeError("esta corrida no debía llamar al modelo")


async def lanzar(
    pg: PlanGuardado,
    corte: date,
    crear_cliente: Callable[[], ClienteModelo],
    usuario: str,
    costo_confirmado: float,
) -> None:
    """`costo_confirmado`: la cifra que la persona vio y aceptó. Si la
    estimación de ahora es otra, no corre. El cliente se crea al final, ya
    validados el tope y la corrida en curso."""
    global _tarea, _ocupado
    # Se marca antes del primer `await`: dos peticiones simultáneas no pasan.
    if corriendo() or _ocupado:
        raise Ocupado
    _ocupado = True
    try:
        acciones, nombres = await asyncio.to_thread(preparar, pg, corte)
        est = await asyncio.to_thread(estimacion, acciones)
        if est["excede_tope"]:
            raise NoSePuede(est["excede_tope"])
        if abs(est["costo_usd"] - costo_confirmado) > 0.005:
            raise NoSePuede(
                f"La estimación cambió ({est['costo_usd']:.2f} USD, no "
                f"{costo_confirmado:.2f}). Vuelva a estimar y confirmar."
            )
        cliente: ClienteModelo = (
            crear_cliente() if est["al_modelo"] else cast(ClienteModelo, _SinModelo())
        )
        await asyncio.to_thread(shutil.rmtree, base(), True)
        estado: dict[str, Any] = {
            "estado": "corriendo",
            "programa": pg.programa,
            "corte": corte.isoformat(),
            "lanzado_por": usuario,
            "inicio": reloj.ahora().isoformat(timespec="seconds"),
            "estimacion": est,
            "hechas": 0,
            "total": len(acciones),
            "costo_usd": 0.0,
            "resumen": None,
            "error": "",
        }
        _guardar(estado)
        _tarea = asyncio.create_task(_correr(estado, pg, acciones, nombres, cliente))
    finally:
        _ocupado = False


async def _correr(
    estado: dict[str, Any],
    pg: PlanGuardado,
    acciones: list[AccionCorte],
    nombres: set[str],
    cliente: ClienteModelo,
) -> None:
    uso = Uso()

    def progreso(hechas: int, total: int) -> None:
        estado.update(hechas=hechas, total=total, costo_usd=round(uso.costo(), 2))
        _guardar(estado)

    try:
        borrador = await bor.generar(
            pg.programa,
            str(estado["corte"]),
            acciones,
            nombres,
            cliente,
            _cache(),
            uso,
            calidad_settings.avance_tope_usd,
            progreso=progreso,
        )
        # Escribir los archivos es trabajo síncrono: fuera del event loop.
        await asyncio.to_thread(
            salidas.borrador_docx, base() / DESCARGAS["docx"][0], borrador
        )
        await asyncio.to_thread(
            salidas.revision_xlsx, base() / DESCARGAS["xlsx"][0], borrador
        )
        estado.update(estado="terminado", resumen=borrador.resumen())
    except Exception as exc:
        logger.exception("Falló el borrador de avance")
        estado.update(
            estado="fallido",
            error=f"El borrador no terminó ({type(exc).__name__}). "
            "Lo ya pagado quedó en la caché: puede volver a generarlo.",
        )
    finally:
        estado["costo_usd"] = round(uso.costo(), 2)
        estado["fin"] = reloj.ahora().isoformat(timespec="seconds")
        _guardar(estado)


async def esperar() -> None:
    """Para las pruebas: espera a que termine el borrador en curso."""
    if _tarea is not None:
        await _tarea


def crear_cliente() -> ClienteModelo:
    """Cliente real de la API. Las pruebas lo reemplazan por uno falso."""
    return revisor.crear_cliente()
