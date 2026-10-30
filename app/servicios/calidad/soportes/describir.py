"""Descripción de cada archivo con el modelo (multimodal), con caché por hash.

La caché guarda la respuesta por (hash del archivo, modelo, versión del
prompt, acción). Repetir la corrida sobre los mismos archivos no cuesta.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.servicios.calidad.soportes import contenido
from app.servicios.calidad.soportes.cliente import ClienteModelo
from app.servicios.calidad.soportes.inventario import leer_bytes
from app.servicios.calidad.soportes.modelos import (
    Accion,
    Archivo,
    Descripcion,
    DescripcionArchivo,
    Uso,
)

logger = logging.getLogger(__name__)

MODELO_DESCRIPCION = "claude-sonnet-5-5"
VERSION_PROMPT = "desc-v1"
# Los xlsx llevan conteos por periodo; si cambia cómo se cuentan, solo ellos se
# vuelven a describir. v3: el año ya no sale de cédulas o teléfonos.
VERSION_XLSX = "xlsx-v3"

SISTEMA = """Eres asistente de la oficina de calidad académica de una facultad \
universitaria. Describes soportes (evidencias) de un plan de mejoramiento de un \
programa de posgrado para que una persona los revise.

Reglas:
- Describe solo lo que se ve en el archivo. No inventes fechas, cifras ni hechos.
- No copies nombres de personas, documentos de identidad, correos ni teléfonos: \
di «un estudiante», «un docente», «el director», etc.
- «que_prueba» dice qué hecho del plan podría respaldar el archivo, no si la \
acción se cumplió: eso lo decide una persona.
- Si el archivo está ilegible, en blanco, cortado o es solo una portada, márcalo.
- Escribe en español, frases cortas.
Registra tu respuesta con la herramienta `registrar_descripcion`."""


class Cache:
    def __init__(self, carpeta: Path) -> None:
        self.carpeta = carpeta
        carpeta.mkdir(parents=True, exist_ok=True)

    def _ruta(self, clave: str) -> Path:
        return self.carpeta / f"{clave}.json"

    def leer(self, clave: str) -> dict[str, Any] | None:
        ruta = self._ruta(clave)
        if not ruta.exists():
            return None
        try:
            datos: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return datos

    def guardar(self, clave: str, datos: dict[str, Any]) -> None:
        self._ruta(clave).write_text(
            json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8"
        )


def clave_descripcion(
    archivo: Archivo, modelo: str, accion: Accion | None = None
) -> str:
    """La clave incluye lo que el texto al modelo dice de la acción
    (descripción e indicador): el mismo archivo y el mismo código en otro
    programa o en otro plan no reutilizan una descripción hecha con otro
    contexto."""
    version = VERSION_PROMPT
    if archivo.tipo == "xlsx":
        version += "|" + VERSION_XLSX
    contexto = f"{accion.descripcion}|{accion.indicador}" if accion else ""
    base = f"{archivo.sha256}|{modelo}|{version}|{archivo.accion}|{contexto}"
    return "desc-" + hashlib.sha256(base.encode()).hexdigest()[:32]


def texto_para_modelo(
    archivo: Archivo, accion: Accion | None, preparado: contenido.Contenido
) -> str:
    partes = [
        f"Archivo: {archivo.nombre}",
        f"Tipo: {archivo.tipo}. {preparado.nota}",
    ]
    if archivo.fecha:
        partes.append(
            f"Fecha en los metadatos ({archivo.fuente_fecha}): {archivo.fecha}"
        )
    if accion:
        partes += [
            f"Está en la carpeta de soportes de la acción {accion.codigo}: "
            f"«{accion.descripcion}»",
            f"Indicador de la acción: «{accion.indicador}»",
        ]
    else:
        partes.append(
            "Es un documento general del plan (no está en una carpeta de acción)."
        )
    if preparado.texto:
        partes.append(
            "Texto extraído del archivo (puede estar incompleto):\n<<<\n"
            + preparado.texto
            + "\n>>>"
        )
    partes.append("Describe el archivo.")
    return "\n".join(partes)


def descripcion_zip(archivo: Archivo) -> DescripcionArchivo:
    """Los zip no se mandan al modelo: se describen por su lista de archivos."""
    if archivo.dentro_de_zip:
        return DescripcionArchivo(
            que_es="Archivo comprimido dentro de otro comprimido; no se abrió.",
            fecha_documento="",
            que_prueba="",
            ilegible_o_incompleto=True,
            observacion="Descomprímalo en la carpeta de la acción para revisarlo.",
        )
    return DescripcionArchivo(
        que_es=f"Archivo comprimido con {len(archivo.miembros)} archivos; cada uno "
        "se describe aparte en este inventario.",
        fecha_documento="",
        que_prueba="Ver los archivos internos.",
        ilegible_o_incompleto=not archivo.miembros,
        observacion="" if archivo.miembros else "El zip está vacío o dañado.",
    )


def _preparar(archivo: Archivo, carpeta: Path) -> contenido.Contenido:
    return contenido.preparar(archivo, leer_bytes(carpeta, archivo))


async def describir_uno(
    archivo: Archivo,
    carpeta: Path,
    accion: Accion | None,
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso,
    modelo: str = MODELO_DESCRIPCION,
) -> Descripcion:
    if archivo.tipo == "zip":
        return Descripcion(archivo.id, descripcion_zip(archivo))
    clave = clave_descripcion(archivo, modelo, accion)
    guardado = cache.leer(clave)
    if guardado and guardado.get("datos"):
        try:
            datos = DescripcionArchivo.model_validate(guardado["datos"])
            return Descripcion(archivo.id, datos, desde_cache=True)
        except ValidationError:
            pass
    try:
        # pypdf, PIL, openpyxl y python-docx son síncronos: van en un hilo
        # para no frenar las demás peticiones del servicio.
        preparado = await asyncio.to_thread(_preparar, archivo, carpeta)
    except Exception as exc:
        return Descripcion(archivo.id, None, f"no se pudo leer ({type(exc).__name__})")
    if not preparado.enviable:
        return Descripcion(archivo.id, None, preparado.nota)
    resp = await cliente.llamar(
        modelo=modelo,
        sistema=SISTEMA,
        bloques=preparado.bloques,
        texto=texto_para_modelo(archivo, accion, preparado),
        salida=DescripcionArchivo,
        nombre_herramienta="registrar_descripcion",
        esfuerzo="low",
        max_tokens=4000,
    )
    uso.registrar(modelo, resp)
    if resp.entrada is None:
        return Descripcion(archivo.id, None, resp.error)
    try:
        datos = DescripcionArchivo.model_validate(resp.entrada)
    except ValidationError:
        return Descripcion(archivo.id, None, "el modelo devolvió datos no válidos")
    cache.guardar(
        clave,
        {
            "datos": datos.model_dump(mode="json"),
            "modelo": modelo,
            "tokens": [resp.tokens_entrada, resp.tokens_salida],
        },
    )
    return Descripcion(archivo.id, datos)


async def describir_todos(
    archivos: list[Archivo],
    carpeta: Path,
    acciones: dict[str, Accion],
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso,
    concurrencia: int = 4,
    modelo: str = MODELO_DESCRIPCION,
    progreso: Callable[[Archivo, Descripcion], None] | None = None,
) -> dict[str, Descripcion]:
    semaforo = asyncio.Semaphore(concurrencia)

    async def una(archivo: Archivo) -> Descripcion:
        async with semaforo:
            desc = await describir_uno(
                archivo,
                carpeta,
                acciones.get(archivo.accion),
                cliente,
                cache,
                uso,
                modelo,
            )
        if progreso:
            progreso(archivo, desc)
        return desc

    resultados = await asyncio.gather(*(una(a) for a in archivos))
    return {d.archivo_id: d for d in resultados}
