"""Organización de las evidencias según el instructivo de la Dirección Académica.

Instructivo «Organización de evidencias digitales — Planes de mejoramiento»
(Dirección Académica, 2026). Por cada acción:

    Soportes de acciones/Acción 1.1/Producto final/              un único PDF
    Soportes de acciones/Acción 1.1/Soportes de producto final/  01 Descripcion 20251015.pdf

Reglas de nombre para los archivos de «Soportes de producto final»: consecutivo
de dos dígitos, descripción breve y fecha AAAAMMDD; máximo 50 caracteres con la
extensión; sin tildes ni caracteres especiales; consecutivo en orden
cronológico.

Todo es determinista y no usa el modelo. MemorIA no renombra ni mueve nada:
señala lo que no cumple y sugiere un nombre. Quien carga los soportes decide.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath

from app.servicios.calidad.soportes.inventario import PATRON_ACCION
from app.servicios.calidad.soportes.modelos import Archivo

MAX_CARACTERES = 50
PRODUCTO_FINAL = "producto final"
SOPORTES = "soportes de producto final"

# Nombre completo: «01 Descripcion breve 20251015.pdf».
_CONSECUTIVO = re.compile(r"^(\d{2,3}) ")
_FECHA_FINAL = re.compile(r" (\d{8})$")
# El instructivo lista / \ : * ? " < > | # % &; también quedan fuera los demás
# signos de sus ejemplos («!!!», «(1)», «_v3», «1.»). Solo letras sin tilde,
# dígitos y espacios en la parte del nombre antes de la extensión.
_PERMITIDO = re.compile(r"[A-Za-z0-9 ]")


def _plegar(texto: str) -> str:
    sin = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin if not unicodedata.combining(c)).casefold().strip()


def _fecha_valida(texto: str) -> date | None:
    try:
        return date(int(texto[:4]), int(texto[4:6]), int(texto[6:8]))
    except ValueError:
        return None


@dataclass
class Revision:
    """Lo que se observa de un archivo y el nombre que se sugiere."""

    archivo: Archivo
    carpeta: str  # "producto final", "soportes", "suelto" o "" (general)
    observaciones: list[str] = field(default_factory=list)
    sugerido: str = ""


@dataclass
class Organizacion:
    archivos: list[Revision]
    acciones: dict[str, list[str]]  # acción -> observaciones de estructura

    @property
    def con_observaciones(self) -> int:
        return sum(1 for r in self.archivos if r.observaciones)

    def resumen(self) -> dict[str, object]:
        return {
            "archivos_con_observaciones": self.con_observaciones,
            "acciones_con_observaciones": sorted(
                (a for a, obs in self.acciones.items() if obs), key=_orden_accion
            ),
        }


def _orden_accion(codigo: str) -> tuple[int, ...]:
    return tuple(int(x) for x in codigo.split("."))


def _partes(archivo: Archivo) -> tuple[str, ...]:
    """Carpetas de la ruta, con los zip abiertos como si fueran carpetas."""
    ruta = archivo.ruta.replace("!/", "/")
    return PurePosixPath(ruta).parent.parts


def carpeta_de(archivo: Archivo) -> str:
    """Dónde está dentro de su acción: producto final, soportes o suelto."""
    if not archivo.accion:
        return ""
    partes = _partes(archivo)
    for i, parte in enumerate(partes):
        if PATRON_ACCION.search(parte):  # también «ACCION 1.3.zip»
            resto = [_plegar(p) for p in partes[i + 1 :]]
            break
    else:
        resto = []
    if not resto:
        return "suelto"
    if resto[0].startswith(SOPORTES):
        return "soportes"
    if resto[0].startswith(PRODUCTO_FINAL):
        return "producto final"
    return "suelto"


def revisar_nombre(nombre: str) -> list[str]:
    """Observaciones sobre el nombre de un soporte de producto final."""
    obs: list[str] = []
    tallo = PurePosixPath(nombre).stem
    if len(nombre) > MAX_CARACTERES:
        obs.append(f"tiene {len(nombre)} caracteres (máximo {MAX_CARACTERES})")
    if not _CONSECUTIVO.match(tallo):
        obs.append("no empieza con número consecutivo (01, 02, 03…)")
    m = _FECHA_FINAL.search(tallo)
    if not m:
        obs.append("no termina con la fecha AAAAMMDD")
    elif _fecha_valida(m.group(1)) is None:
        obs.append(f"la fecha {m.group(1)} no es válida")
    tildes = sorted({c for c in tallo if unicodedata.decomposition(c)})
    if tildes:
        obs.append(f"tiene tildes o eñes ({' '.join(tildes)})")
    otros = sorted({c for c in tallo if not _PERMITIDO.match(c) and c not in tildes})
    if otros:
        obs.append(f"tiene caracteres especiales ({' '.join(otros)})")
    if "  " in tallo or tallo != tallo.strip():
        obs.append("tiene espacios dobles o al inicio o al final")
    return obs


def _descripcion(tallo: str) -> str:
    """La parte descriptiva del nombre, sin consecutivo, fecha ni signos."""
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", tallo) if not unicodedata.combining(c)
    )
    texto = re.sub(r"[^A-Za-z0-9]+", " ", texto)
    texto = re.sub(r"^\s*\d{1,3}\s+", "", texto)  # consecutivo o «1.»
    texto = re.sub(r"\s+\d{8}\s*$", "", texto)  # fecha al final
    texto = re.sub(r"\s+\d{1,2}\s*$", "", texto)  # «(1)» de las copias
    texto = " ".join(texto.split())
    return texto[:1].upper() + texto[1:] if texto else "Documento"


def _fecha_de(archivo: Archivo) -> str:
    m = _FECHA_FINAL.search(PurePosixPath(archivo.nombre).stem)
    if m and _fecha_valida(m.group(1)):
        return m.group(1)
    if archivo.fecha:
        return archivo.fecha.replace("-", "")[:8]
    return "AAAAMMDD"


def nombre_sugerido(archivo: Archivo, consecutivo: int) -> str:
    """«01 Descripcion 20251015.pdf», recortado a 50 caracteres.

    La fecha sale del nombre si ya la trae y si no de los metadatos; si no hay
    ninguna queda «AAAAMMDD» para que la persona la complete.
    """
    ext = archivo.extension.lower()
    fecha = _fecha_de(archivo)
    prefijo = f"{consecutivo:02d} "
    cabe = MAX_CARACTERES - len(prefijo) - len(fecha) - 1 - len(ext)
    desc = _descripcion(PurePosixPath(archivo.nombre).stem)
    if len(desc) > cabe:  # se corta en la última palabra que cabe
        corto = desc[: cabe + 1].rsplit(" ", 1)[0]
        desc = corto if " " in desc[: cabe + 1] else desc[:cabe]
    desc = desc.rstrip()
    return f"{prefijo}{desc} {fecha}{ext}"


def _revisar_soportes(revisiones: list[Revision]) -> None:
    """Nombres, orden cronológico y duplicados dentro de una carpeta de soportes."""
    for r in revisiones:
        r.observaciones.extend(revisar_nombre(r.archivo.nombre))
    # El consecutivo debe seguir el orden de las fechas del nombre.
    fechados: list[tuple[int, str, Revision]] = []
    for r in revisiones:
        tallo = PurePosixPath(r.archivo.nombre).stem
        c, f = _CONSECUTIVO.match(tallo), _FECHA_FINAL.search(tallo)
        if c and f and _fecha_valida(f.group(1)):
            fechados.append((int(c.group(1)), f.group(1), r))
    fechados.sort(key=lambda t: (t[0], t[1]))
    vistos: dict[int, Revision] = {}
    for i, (num, fecha, r) in enumerate(fechados):
        if num in vistos:
            r.observaciones.append(
                f"repite el consecutivo {num:02d} de {vistos[num].archivo.nombre}"
            )
        vistos.setdefault(num, r)
        if i and fecha < fechados[i - 1][1]:
            r.observaciones.append(
                f"su fecha es anterior a la de {fechados[i - 1][2].archivo.nombre}: "
                "el consecutivo no va en orden cronológico"
            )
    # Sugerencia: numerar por fecha (la del nombre o la de los metadatos).
    orden = sorted(
        revisiones, key=lambda r: (_fecha_de(r.archivo), r.archivo.nombre.casefold())
    )
    for i, r in enumerate(orden, start=1):
        sugerido = nombre_sugerido(r.archivo, i)
        if r.observaciones and sugerido != r.archivo.nombre:
            r.sugerido = sugerido


def revisar(archivos: list[Archivo]) -> Organizacion:
    """Revisa carpetas y nombres de todas las acciones del inventario."""
    revisiones = [Revision(a, carpeta_de(a)) for a in archivos if a.tipo != "zip"]
    por_accion: dict[str, list[Revision]] = {}
    for r in revisiones:
        if r.archivo.accion:
            por_accion.setdefault(r.archivo.accion, []).append(r)

    acciones: dict[str, list[str]] = {}
    for codigo, grupo in por_accion.items():
        obs: list[str] = []
        finales = [r for r in grupo if r.carpeta == "producto final"]
        soportes = [r for r in grupo if r.carpeta == "soportes"]
        if not finales:
            obs.append("no tiene carpeta «Producto final» o está vacía")
        elif len(finales) > 1:
            obs.append(
                f"«Producto final» tiene {len(finales)} archivos; debe tener uno solo"
            )
        for r in finales:
            if r.archivo.extension.lower() != ".pdf":
                r.observaciones.append("el producto final debe ser un PDF")
        if not soportes:
            obs.append("no tiene carpeta «Soportes de producto final» o está vacía")
        for r in grupo:
            if r.carpeta == "suelto":
                r.observaciones.append(
                    "está suelto en la carpeta de la acción: va en «Producto final» "
                    "o en «Soportes de producto final»"
                )
        # Duplicados: el mismo contenido dos veces en la acción.
        por_hash: dict[str, Revision] = {}
        for r in grupo:
            h = r.archivo.sha256
            if h and h in por_hash:
                r.observaciones.append(f"es igual a {por_hash[h].archivo.nombre}")
            elif h:
                por_hash[h] = r
        # Cada carpeta de soportes se numera por separado (puede haber zips).
        por_carpeta: dict[tuple[str, ...], list[Revision]] = {}
        for r in soportes:
            por_carpeta.setdefault(_partes(r.archivo), []).append(r)
        for lote in por_carpeta.values():
            _revisar_soportes(lote)
        acciones[codigo] = obs
    return Organizacion(revisiones, acciones)
