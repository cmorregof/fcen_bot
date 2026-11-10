"""Descomprime con cuidado el zip de soportes que sube la oficina de calidad.

Se rechaza el zip entero si alguna entrada:
- sale de la carpeta de destino (`../`, ruta absoluta, unidad de Windows);
- es un enlace simbólico;
- hace pasar el total descomprimido o el número de archivos de los límites
  (un zip pequeño puede traer gigas: «zip bomb»).

Los zip que vienen dentro se copian tal cual: el inventario los lista por
dentro sin descomprimirlos. Las carpetas vacías también se crean: una acción
con sus carpetas vacías debe aparecer en la revisión, no desaparecer.

Drive divide en partes las descargas grandes («…-1-001.zip», «…-2-001.zip»).
`extraer` recibe una o varias partes y las junta en la misma carpeta; los
límites cuentan para todas juntas.
"""

from __future__ import annotations

import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from app.servicios.calidad.soportes.inventario import nombre_miembro_zip, omitido

_UNIDAD = re.compile(r"^[A-Za-z]:")
_BLOQUE = 1024 * 1024


class ZipNoValido(ValueError):
    """El zip no se puede usar; el mensaje es para la persona."""


def _ruta_segura(nombre: str) -> PurePosixPath:
    limpio = nombre.replace("\\", "/")
    ruta = PurePosixPath(limpio)
    if limpio.startswith("/") or _UNIDAD.match(limpio) or ".." in ruta.parts:
        raise ZipNoValido(
            "El zip trae rutas que apuntan fuera de la carpeta. No se usó. "
            "Vuelva a comprimir la carpeta de soportes."
        )
    return ruta


def _es_enlace(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


_PARTE_DRIVE = re.compile(r"-\d+-\d{3}$")


def grupo_de_parte(nombre: str) -> str:
    """«Soportes-20261109T1-2-001.zip» -> «Soportes-20261109T1»: partes de una
    misma descarga de Drive comparten el grupo."""
    return _PARTE_DRIVE.sub("", Path(nombre).stem)


def extraer(
    origen: Path | list[Path], destino: Path, *, max_bytes: int, max_archivos: int
) -> int:
    """Descomprime `origen` (un zip o las partes de uno) en `destino`.

    `destino` debe estar vacía o no existir. Devuelve cuántos archivos
    escribió. Si algo falla, borra `destino`.
    """
    partes = origen if isinstance(origen, list) else [origen]
    destino.mkdir(parents=True, exist_ok=True)
    raiz = destino.resolve()
    try:
        abiertos: list[zipfile.ZipFile] = []
        for parte in partes:
            try:
                abiertos.append(zipfile.ZipFile(parte))
            except zipfile.BadZipFile as exc:
                raise ZipNoValido(
                    "El archivo no es un zip válido."
                    if len(partes) == 1
                    else f"{parte.name} no es un zip válido."
                ) from exc
        try:
            return _extraer(abiertos, raiz, max_bytes, max_archivos)
        finally:
            for zf in abiertos:
                zf.close()
    except ZipNoValido:
        shutil.rmtree(destino, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        # RuntimeError: zip cifrado con contraseña; ValueError: nombre con NUL.
        shutil.rmtree(destino, ignore_errors=True)
        raise ZipNoValido(
            f"No se pudo descomprimir el zip ({type(exc).__name__})."
        ) from exc


def _dentro(raiz: Path, ruta: PurePosixPath) -> Path:
    final = (raiz / Path(*ruta.parts)).resolve()
    if not final.is_relative_to(raiz) or final == raiz:
        raise ZipNoValido("El zip trae rutas que apuntan fuera de la carpeta.")
    return final


def _extraer(
    zips: list[zipfile.ZipFile], raiz: Path, max_bytes: int, max_archivos: int
) -> int:
    entradas: list[tuple[zipfile.ZipFile, zipfile.ZipInfo, PurePosixPath]] = []
    carpetas: list[PurePosixPath] = []
    declarado = 0
    # Se cuentan todas las entradas, también carpetas y omitidas.
    total = sum(len(zf.infolist()) for zf in zips)
    if total > max_archivos:
        raise ZipNoValido(f"El zip trae {total} entradas; el máximo es {max_archivos}.")
    for zf in zips:
        for info in zf.infolist():
            nombre = nombre_miembro_zip(info)
            ruta = _ruta_segura(nombre)
            if _es_enlace(info):
                raise ZipNoValido(
                    "El zip trae enlaces simbólicos. No se usó. "
                    "Comprima solo archivos y carpetas."
                )
            if "__MACOSX" in ruta.parts or (ruta.parts and omitido(ruta.name)):
                continue
            if info.is_dir():
                if ruta.parts:
                    carpetas.append(ruta)
                continue
            entradas.append((zf, info, ruta))
            declarado += info.file_size
    if len(entradas) > max_archivos:
        raise ZipNoValido(
            f"El zip trae {len(entradas)} archivos; el máximo es {max_archivos}."
        )
    if declarado > max_bytes:
        raise ZipNoValido(
            f"Descomprimido, el zip pasa del límite de {max_bytes // 1_000_000} MB."
        )
    for ruta in carpetas:
        _dentro(raiz, ruta).mkdir(parents=True, exist_ok=True)
    escrito = 0
    for zf, info, ruta in entradas:
        final = _dentro(raiz, ruta)
        final.parent.mkdir(parents=True, exist_ok=True)
        # El tamaño declarado puede mentir: se cuenta lo que se escribe.
        with zf.open(info) as fuente, final.open("wb") as salida:
            while bloque := fuente.read(_BLOQUE):
                escrito += len(bloque)
                if escrito > max_bytes:
                    raise ZipNoValido(
                        "Descomprimido, el zip pasa del límite de "
                        f"{max_bytes // 1_000_000} MB."
                    )
                salida.write(bloque)
    return len(entradas)
