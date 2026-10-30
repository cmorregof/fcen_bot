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

La corrida en curso y el cerrojo viven en variables de este módulo: exigen un
solo proceso de uvicorn (como en el Dockerfile). Con varios workers, dos
procesos podrían correr a la vez y cada uno vería un estado distinto.

Retención: los soportes se borran al terminar la corrida y al arrancar si
quedaron de una corrida cortada; salidas y caché, a los
`CALIDAD_REVISOR_RETENCION_DIAS`. Con el interruptor apagado se borra todo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
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
_ultima_limpieza = 0.0


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
        await asyncio.to_thread(shutil.rmtree, _actual(), True)
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
        await asyncio.to_thread(shutil.rmtree, _actual(), True)
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
        # La confirmación de costo queda atada a esta carga (ver `lanzar`).
        "carga_id": uuid.uuid4().hex,
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


def _inventario_y_estimacion(
    acciones: list[Accion],
) -> tuple[list[Archivo], dict[str, Any]]:
    archivos = inventariar(_soportes())
    return archivos, _estimacion(archivos, acciones)


async def lanzar(
    acciones: list[Accion],
    cliente: ClienteModelo,
    usuario: str,
    *,
    programa: str,
    carga_id: str,
    costo_visto: float,
) -> None:
    """Revisa de nuevo la estimación y deja la corrida en segundo plano.

    Solo corre la carga que la persona vio (`carga_id`) y solo si el costo no
    subió respecto al que confirmó (`costo_visto`). Todo se verifica con el
    cerrojo tomado: otra carga no puede colarse en medio.
    """
    global _tarea, _ocupado
    if corriendo() or _ocupado:
        raise Ocupado
    _ocupado = True
    try:
        estado = leer_estado()
        if (
            estado["estado"] != "cargado"
            or not estado["soportes_presentes"]
            or estado.get("carga_id") != carga_id
            or estado.get("programa") != programa
        ):
            raise NoSePuede(
                "Los soportes cambiaron desde que usted vio el costo. "
                "Revise la nueva estimación y confirme otra vez."
            )
        archivos, estimacion = await asyncio.to_thread(
            _inventario_y_estimacion, acciones
        )
        if estimacion["excede_tope"]:
            raise NoSePuede(estimacion["excede_tope"])
        if estimacion["costo_usd"] > costo_visto + 0.005:
            estado["estimacion"] = estimacion
            _guardar(_sin_derivados(estado))
            raise NoSePuede(
                f"El costo estimado subió a {estimacion['costo_usd']:.2f} USD. "
                "Revíselo y confirme otra vez."
            )
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
        estado = _sin_derivados(estado)
        _guardar(estado)
        _tarea = asyncio.create_task(_correr(estado, archivos, acciones, cliente))
    finally:
        _ocupado = False


def _sin_derivados(estado: dict[str, Any]) -> dict[str, Any]:
    """Quita lo que `leer_estado` calcula al leer."""
    return {
        k: v
        for k, v in estado.items()
        if k not in ("soportes_presentes", "descargas", "en_cache")
    }


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
        # Solo el tipo: el mensaje o la traza podrían traer nombres de archivos.
        logger.error("Falló la corrida del revisor de soportes: %s", type(exc).__name__)
        estado.update(
            estado="fallido",
            error=f"La revisión no terminó ({type(exc).__name__}). "
            "Lo ya pagado quedó en la caché: puede volver a subir el zip.",
        )
    finally:
        estado["costo_usd"] = round(uso.costo(), 2)
        estado["fin"] = reloj.ahora().isoformat(timespec="seconds")
        # Los soportes no se quedan en el volumen después de la corrida.
        await asyncio.to_thread(shutil.rmtree, _soportes(), True)
        _guardar(estado)


# ---------------------------------------------------------------------------
# Borrado
# ---------------------------------------------------------------------------


async def borrar(*, con_cache: bool = False) -> None:
    """Borra soportes, salidas y estado; con `con_cache`, también la caché."""
    global _ocupado
    if corriendo() or _ocupado:
        raise Ocupado
    _ocupado = True
    try:
        await asyncio.to_thread(shutil.rmtree, _actual(), True)
        if con_cache:
            await asyncio.to_thread(shutil.rmtree, base() / "cache", True)
    finally:
        _ocupado = False


def limpiar(*, al_arrancar: bool = False) -> None:
    """Retención de datos en el volumen. Síncrona: llamarla en un hilo.

    - Interruptor apagado: borra todo lo del revisor.
    - Al arrancar: si la corrida quedó cortada («corriendo») o no hay estado,
      borra los soportes y el zip a medio subir.
    - Siempre: borra la carga (salidas incluidas) y las entradas de la caché
      con más de `revisor_retencion_dias`.
    """
    global _ultima_limpieza
    _ultima_limpieza = time.monotonic()
    if not calidad_settings.revisor_activo:
        if base().exists():
            shutil.rmtree(base(), ignore_errors=True)
        return
    if corriendo() or _ocupado:
        return
    ruta_estado = _actual() / "estado.json"
    if al_arrancar:
        try:
            cortada = (
                json.loads(ruta_estado.read_text(encoding="utf-8")).get("estado")
                == "corriendo"
            )
        except (OSError, json.JSONDecodeError):
            cortada = True
        if cortada:
            shutil.rmtree(_soportes(), ignore_errors=True)
            (_actual() / "subida.zip").unlink(missing_ok=True)
    limite = time.time() - calidad_settings.revisor_retencion_dias * 86400
    try:
        if ruta_estado.stat().st_mtime < limite:
            shutil.rmtree(_actual(), ignore_errors=True)
    except OSError:
        pass
    carpeta_cache = base() / "cache"
    if carpeta_cache.is_dir():
        for entrada in carpeta_cache.glob("*.json"):
            try:
                if entrada.stat().st_mtime < limite:
                    entrada.unlink()
            except OSError:
                continue


async def limpiar_de_vez_en_cuando() -> None:
    """La limpieza por retención, como mucho una vez por hora."""
    if time.monotonic() - _ultima_limpieza > 3600 or not _ultima_limpieza:
        await asyncio.to_thread(limpiar)


async def esperar() -> None:
    """Para las pruebas: espera a que termine la corrida en curso."""
    if _tarea is not None:
        await _tarea
