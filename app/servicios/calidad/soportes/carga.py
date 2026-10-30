"""Descomprime con cuidado el zip de soportes que sube la oficina de calidad.

Se rechaza el zip entero si alguna entrada:
- sale de la carpeta de destino (`../`, ruta absoluta, unidad de Windows);
- es un enlace simbólico;
- hace pasar el total descomprimido o el número de archivos de los límites
  (un zip pequeño puede traer gigas: «zip bomb»).

Los zip que vienen dentro se copian tal cual: el inventario los lista por
dentro sin descomprimirlos.
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


def extraer(origen: Path, destino: Path, *, max_bytes: int, max_archivos: int) -> int:
    """Descomprime `origen` en `destino` (que debe estar vacía o no existir).

    Devuelve cuántos archivos escribió. Si algo falla, borra `destino`.
    """
    try:
        zf = zipfile.ZipFile(origen)
    except zipfile.BadZipFile as exc:
        raise ZipNoValido("El archivo no es un zip válido.") from exc
    destino.mkdir(parents=True, exist_ok=True)
    raiz = destino.resolve()
    try:
        with zf:
            entradas: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            declarado = 0
            infos = zf.infolist()
            # Se cuentan todas las entradas, también carpetas y omitidas.
            if len(infos) > max_archivos:
                raise ZipNoValido(
                    f"El zip trae {len(infos)} entradas; el máximo es {max_archivos}."
                )
            for info in infos:
                nombre = nombre_miembro_zip(info)
                ruta = _ruta_segura(nombre)
                if _es_enlace(info):
                    raise ZipNoValido(
                        "El zip trae enlaces simbólicos. No se usó. "
                        "Comprima solo archivos y carpetas."
                    )
                if info.is_dir() or "__MACOSX" in ruta.parts or omitido(ruta.name):
                    continue
                entradas.append((info, ruta))
                declarado += info.file_size
            if len(entradas) > max_archivos:
                raise ZipNoValido(
                    f"El zip trae {len(entradas)} archivos; el máximo es {max_archivos}."
                )
            if declarado > max_bytes:
                raise ZipNoValido(
                    "Descomprimido, el zip pasa del límite de "
                    f"{max_bytes // 1_000_000} MB."
                )
            escrito = 0
            for info, ruta in entradas:
                final = (raiz / Path(*ruta.parts)).resolve()
                if not final.is_relative_to(raiz) or final == raiz:
                    raise ZipNoValido(
                        "El zip trae rutas que apuntan fuera de la carpeta."
                    )
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
    except ZipNoValido:
        shutil.rmtree(destino, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        # RuntimeError: zip cifrado con contraseña; ValueError: nombre con NUL.
        shutil.rmtree(destino, ignore_errors=True)
        raise ZipNoValido(
            f"No se pudo descomprimir el zip ({type(exc).__name__})."
        ) from exc
