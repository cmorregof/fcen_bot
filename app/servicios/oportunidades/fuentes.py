"""Fuentes de la vigía (config/oportunidades.yaml).

Cada fuente es una página pública que lista ofertas o convocatorias. Solo se
consultan las que tienen ``activa: true``; la lista la aprueba la Decanatura.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field, field_validator

from app.core.programas import PROGRAMAS
from app.servicios.oportunidades.config import config
from app.servicios.oportunidades.modelo import TipoOferta


class Fuente(BaseModel):
    clave: str = Field(pattern=r"^[a-z0-9_]+$")
    nombre: str
    url: str
    activa: bool = False
    # Qué suele publicar: orienta al modelo, no filtra.
    tipos: list[TipoOferta] = Field(default_factory=list)
    # Programas a los que suele aplicar (vacío: cualquiera de la FCEN).
    programas: list[str] = Field(default_factory=list)
    # Por qué se puede consultar: términos de uso, robots.txt, carácter público.
    justificacion: str = ""
    terminos_url: str = ""
    # Dominios en los que pueden estar los enlaces de sus ofertas.
    dominios: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _https(cls, valor: str) -> str:
        partes = urlsplit(valor)
        if partes.scheme not in ("https", "http") or not partes.hostname:
            raise ValueError(f"URL no válida: {valor}")
        return valor

    @field_validator("programas")
    @classmethod
    def _programas(cls, valor: list[str]) -> list[str]:
        desconocidos = [p for p in valor if p not in PROGRAMAS]
        if desconocidos:
            raise ValueError(f"Programas desconocidos: {desconocidos}")
        return valor

    @property
    def dominios_validos(self) -> list[str]:
        host = urlsplit(self.url).hostname or ""
        return [host, *self.dominios]


class ListaFuentes(BaseModel):
    fuentes: list[Fuente] = Field(default_factory=list)
    # Fuentes que se evaluaron y NO se consultan, con su motivo (documentación).
    excluidas: list[dict[str, str]] = Field(default_factory=list)


def cargar(ruta: Path | None = None) -> ListaFuentes:
    ruta = ruta or config.fuentes_path
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    lista = ListaFuentes.model_validate(datos)
    claves = [f.clave for f in lista.fuentes]
    repetidas = {c for c in claves if claves.count(c) > 1}
    if repetidas:
        raise ValueError(f"Claves de fuente repetidas: {sorted(repetidas)}")
    return lista


def activas(ruta: Path | None = None) -> list[Fuente]:
    return [f for f in cargar(ruta).fuentes if f.activa]


def por_clave(clave: str) -> Fuente | None:
    return next((f for f in cargar().fuentes if f.clave == clave), None)
