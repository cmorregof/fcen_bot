"""Corrida del revisor de soportes pedida desde la web.

Una sola corrida a la vez por servicio. Todo vive en el volumen del servicio
(`calidad_settings.revisor_dir`, por defecto junto a la base):

    cache/              descripciones y cruces ya pagados; sobrevive al borrado
    actual/subida.zip   el zip mientras llega; se borra al descomprimirlo
    actual/soportes/    los soportes; se borran al terminar la corrida
    actual/salidas/     xlsx y docx para descargar, hasta «Borrar soportes»
    actual/estado.json  en qué va la corrida

Nada sale a otro servicio que no sea la API de Anthropic. El modelo no decide:
veredictos y porcentajes son propuestas para revisión humana.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.servicios.calidad import reloj
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.soportes.carga import ZipNoValido, extraer
from app.servicios.calidad.soportes.cliente import ClienteAnthropic, ClienteModelo
from app.servicios.calidad.soportes.describir import Cache
from app.servicios.calidad.soportes.inventario import inventariar
from app.servicios.calidad.soportes.modelos import Accion, Archivo, Uso
from app.servicios.calidad.soportes.revisor import (
    PASOS,
    estimar,
    excede_tope,
    revisar,
)

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DESCARGAS: dict[str, tuple[str, str]] = {
    "inventario": ("inventario_soportes.xlsx", XLSX),
    "cruce": ("cruce_acciones.xlsx", XLSX),
    "borrador": ("borrador_cierre.docx", DOCX),
}

_tarea: asyncio.Task[None] | None = None
_ocupado = False  # una carga, un lanzamiento o un borrado en curso


class Ocupado(Exception):
    """Ya hay una corrida o una carga en curso en este servicio."""


class NoSePuede(Exception):
    """La acción no aplica en el estado actual; el mensaje es para la persona."""


# ---------------------------------------------------------------------------
# Rutas y estado
# ---------------------------------------------------------------------------


def base() -> Path:
    return calidad_settings.revisor_dir or settings.db_path.parent / "revisor"


def _actual() -> Path:
    return base() / "actual"


def _soportes() -> Path:
    return _actual() / "soportes"


def _salidas() -> Path:
    return _actual() / "salidas"


def cache() -> Cache:
    return Cache(base() / "cache")


def corriendo() -> bool:
    return _tarea is not None and not _tarea.done()


def _guardar(estado: dict[str, Any]) -> None:
    ruta = _actual() / "estado.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    temporal.replace(ruta)


def leer_estado() -> dict[str, Any]:
    ruta = _actual() / "estado.json"
    try:
        estado: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        estado = {"estado": "vacio"}
    if estado.get("estado") == "corriendo" and not corriendo():
        # El servicio se reinició a mitad de la corrida.
        estado["estado"] = "interrumpido"
    estado["soportes_presentes"] = _soportes().is_dir()
    carpeta_cache = base() / "cache"
    estado["en_cache"] = (
        sum(1 for _ in carpeta_cache.glob("*.json")) if carpeta_cache.is_dir() else 0
    )
    estado["descargas"] = [
        clave
        for clave, (nombre, _) in DESCARGAS.items()
        if (_salidas() / nombre).exists()
    ]
    return estado


def descarga(clave: str) -> tuple[Path, str, str] | None:
    """(ruta, nombre, tipo) de una salida, si existe."""
    if clave not in DESCARGAS or corriendo():
        return None
    nombre, tipo = DESCARGAS[clave]
    ruta = _salidas() / nombre
    return (ruta, nombre, tipo) if ruta.exists() else None


# ---------------------------------------------------------------------------
# Carga y estimación
# ---------------------------------------------------------------------------


def _estimacion(archivos: list[Archivo], acciones: list[Accion]) -> dict[str, Any]:
    est = estimar(archivos, acciones, cache())
    codigos = {a.codigo for a in acciones}
    con_soportes = {a.accion for a in archivos if a.accion}
    tope = calidad_settings.revisor_tope_usd
    return {
        "archivos": len(archivos),
        "acciones": len(acciones),
        "al_modelo": est.archivos_al_modelo,
        "en_cache": est.en_cache,
        "generales": sum(1 for a in archivos if not a.accion),
        "acciones_sin_soportes": sorted(codigos - con_soportes),
        "carpetas_sin_accion": sorted(con_soportes - codigos),
        "costo_usd": round(est.costo, 2),
        "tope_usd": tope,
        "excede_tope": excede_tope(est, tope),
    }


async def recibir(
    trozos: AsyncIterator[bytes],
    programa: str,
    acciones: list[Accion],
    usuario: str,
) -> dict[str, Any]:
    """Guarda el zip en el volumen, lo descomprime y estima el costo.

    Reemplaza la carga anterior (soportes y salidas), nunca la caché.
    """
    global _ocupado
    if corriendo() or _ocupado:
        raise Ocupado
    _ocupado = True
    try:
        shutil.rmtree(_actual(), ignore_errors=True)
        _actual().mkdir(parents=True)
        zip_ = _actual() / "subida.zip"
        maximo = calidad_settings.revisor_max_mb * 1_000_000
        recibido = 0
        with zip_.open("wb") as salida:
            async for trozo in trozos:
                recibido += len(trozo)
                if recibido > maximo:
                    raise ZipNoValido(
                        f"El zip pesa más de {calidad_settings.revisor_max_mb} MB."
                    )
                salida.write(trozo)
        if recibido == 0:
            raise ZipNoValido("No llegó ningún archivo.")
        return await asyncio.to_thread(_preparar, zip_, programa, acciones, usuario)
    except BaseException:
        shutil.rmtree(_actual(), ignore_errors=True)
        raise
    finally:
        _ocupado = False


def _preparar(
    zip_: Path, programa: str, acciones: list[Accion], usuario: str
) -> dict[str, Any]:
    try:
        extraer(
            zip_,
            _soportes(),
            max_bytes=calidad_settings.revisor_max_descomprimido_mb * 1_000_000,
            max_archivos=calidad_settings.revisor_max_archivos,
        )
    finally:
        zip_.unlink(missing_ok=True)
    archivos = inventariar(_soportes())
    if not archivos:
        raise ZipNoValido("El zip no trae soportes.")
    estado: dict[str, Any] = {
        "estado": "cargado",
        "programa": programa,
        "cargado_por": usuario,
        "cargado": reloj.ahora().isoformat(timespec="seconds"),
        "estimacion": _estimacion(archivos, acciones),
    }
    _guardar(estado)
    return leer_estado()


# ---------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------


def crear_cliente() -> ClienteModelo:
    """Cliente real de la API. Las pruebas lo reemplazan por uno falso."""
    if not settings.anthropic_api_key:
        raise NoSePuede("El servicio no tiene configurada la API de Anthropic.")
    return ClienteAnthropic(settings.anthropic_api_key, settings.anthropic_workspace_id)


async def lanzar(acciones: list[Accion], cliente: ClienteModelo, usuario: str) -> None:
    """Revisa de nuevo la estimación y deja la corrida en segundo plano."""
    global _tarea, _ocupado
    if corriendo() or _ocupado:
        raise Ocupado
    estado = leer_estado()
    if (
        estado["estado"] not in ("cargado", "interrumpido")
        or not estado["soportes_presentes"]
    ):
        raise NoSePuede("Primero suba el zip de soportes.")
    _ocupado = True
    try:
        archivos = await asyncio.to_thread(inventariar, _soportes())
        estimacion = _estimacion(archivos, acciones)
        if estimacion["excede_tope"]:
            raise NoSePuede(estimacion["excede_tope"])
        estado.update(
            estado="corriendo",
            estimacion=estimacion,
            lanzado_por=usuario,
            inicio=reloj.ahora().isoformat(timespec="seconds"),
            costo_usd=0.0,
            pasos=[
                {
                    "clave": c,
                    "titulo": t,
                    "hechos": 0,
                    "total": 0,
                    "estado": "pendiente",
                }
                for c, t in PASOS
            ],
            error="",
            resumen=None,
        )
        for k in ("soportes_presentes", "descargas", "en_cache"):
            estado.pop(k, None)
        _guardar(estado)
        _tarea = asyncio.create_task(_correr(estado, archivos, acciones, cliente))
    finally:
        _ocupado = False


async def _correr(
    estado: dict[str, Any],
    archivos: list[Archivo],
    acciones: list[Accion],
    cliente: ClienteModelo,
) -> None:
    uso = Uso()
    claves = [c for c, _ in PASOS]

    def paso(clave: str, hechos: int, total: int) -> None:
        i = claves.index(clave)
        for j, p in enumerate(estado["pasos"]):
            if j < i:
                p["estado"] = "hecho"
        actual = estado["pasos"][i]
        actual.update(hechos=hechos, total=total)
        actual["estado"] = "hecho" if total and hechos >= total else "en curso"
        estado["costo_usd"] = round(uso.costo(), 2)
        _guardar(estado)

    try:
        informe = await revisar(
            _soportes(),
            None,
            _salidas(),
            cliente,
            str(estado.get("programa") or "Programa"),
            preparado=(archivos, acciones),
            cache=cache(),
            uso=uso,
            tope_usd=calidad_settings.revisor_tope_usd,
            paso=paso,
        )
        estado.update(estado="terminado", resumen=informe.resumen())
    except Exception as exc:
        logger.exception("Falló la corrida del revisor de soportes")
        estado.update(
            estado="fallido",
            error=f"La revisión no terminó ({type(exc).__name__}). "
            "Lo ya pagado quedó en la caché: puede volver a subir el zip.",
        )
    finally:
        estado["costo_usd"] = round(uso.costo(), 2)
        estado["fin"] = reloj.ahora().isoformat(timespec="seconds")
        # Los soportes no se quedan en el volumen después de la corrida.
        shutil.rmtree(_soportes(), ignore_errors=True)
        _guardar(estado)


# ---------------------------------------------------------------------------
# Borrado
# ---------------------------------------------------------------------------


def borrar(*, con_cache: bool = False) -> None:
    """Borra soportes, salidas y estado; con `con_cache`, también la caché."""
    if corriendo() or _ocupado:
        raise Ocupado
    shutil.rmtree(_actual(), ignore_errors=True)
    if con_cache:
        shutil.rmtree(base() / "cache", ignore_errors=True)


async def esperar() -> None:
    """Para las pruebas: espera a que termine la corrida en curso."""
    if _tarea is not None:
        await _tarea
