"""Índice de las descripciones de soportes por programa, dentro de la caché.

La caché de `describir` se indexa por hash y no dice a qué programa ni a qué
acción pertenece cada descripción. Al terminar de describir, el revisor deja
aquí una lista por programa (ID del inventario, acción y descripción, sin el
nombre del archivo) para que otros servicios, como el borrador de avance de un
corte, puedan citar los soportes por su ID. Se reescribe en cada corrida y se
borra junto con la caché.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.servicios.calidad.plantilla import plegar
from app.servicios.calidad.soportes.describir import Cache
from app.servicios.calidad.soportes.modelos import (
    Archivo,
    Descripcion,
    DescripcionArchivo,
)

SUBCARPETA = "indices"


def _ruta(cache: Cache, programa: str) -> Path:
    clave = hashlib.sha256(plegar(programa).encode()).hexdigest()[:16]
    return cache.carpeta / SUBCARPETA / f"{clave}.json"


def guardar_indice(
    cache: Cache,
    programa: str,
    descripciones: dict[str, Descripcion],
    archivos: list[Archivo],
) -> None:
    filas: list[dict[str, Any]] = []
    for a in archivos:
        d = descripciones.get(a.id)
        if d is None or d.datos is None or a.tipo == "zip":
            continue
        filas.append(
            {"id": a.id, "accion": a.accion, "datos": d.datos.model_dump(mode="json")}
        )
    ruta = _ruta(cache, programa)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps({"programa": programa, "soportes": filas}, ensure_ascii=False),
        encoding="utf-8",
    )


def leer_indice(
    cache: Cache, programa: str
) -> dict[str, list[tuple[str, DescripcionArchivo]]]:
    """Acción -> [(ID del soporte, descripción)]; «» agrupa los generales."""
    try:
        crudo = json.loads(_ruta(cache, programa).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    salida: dict[str, list[tuple[str, DescripcionArchivo]]] = {}
    for fila in crudo.get("soportes", []):
        try:
            datos = DescripcionArchivo.model_validate(fila["datos"])
        except (ValidationError, KeyError):
            continue
        salida.setdefault(str(fila.get("accion", "")), []).append(
            (str(fila["id"]), datos)
        )
    return salida
