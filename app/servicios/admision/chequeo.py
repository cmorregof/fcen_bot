"""Lista de chequeo por documento (config/admision/chequeo.yaml, editable)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from app.servicios.admision.config import config

Tipo = Literal["obligatorio", "condicional", "opcional"]


class Documento(BaseModel):
    clave: str
    nombre: str
    seccion: str
    chequeo: list[str]
    tipo: Tipo = "obligatorio"
    # Solo en los condicionales: a quién aplica, con el texto de la lista.
    condicion: str | None = None
    # Texto literal de la lista que acompaña al documento.
    nota: str | None = None

    @model_validator(mode="after")
    def _condicion_solo_si_condicional(self) -> Documento:
        if (self.tipo == "condicional") != bool(self.condicion):
            raise ValueError(
                f"{self.clave}: «condicion» va en los condicionales y solo en ellos"
            )
        if not self.chequeo:
            raise ValueError(f"{self.clave}: la lista de chequeo está vacía")
        return self


class ListaChequeo(BaseModel):
    documentos: list[Documento]

    @model_validator(mode="after")
    def _claves_unicas(self) -> ListaChequeo:
        claves = [d.clave for d in self.documentos]
        repetidas = {c for c in claves if claves.count(c) > 1}
        if repetidas:
            raise ValueError(f"Claves repetidas: {', '.join(sorted(repetidas))}")
        return self

    def buscar(self, clave: str) -> Documento | None:
        return next((d for d in self.documentos if d.clave == clave), None)

    def secciones(self) -> list[tuple[str, list[Documento]]]:
        """Documentos agrupados por sección, en el orden de la lista."""
        grupos: dict[str, list[Documento]] = {}
        for d in self.documentos:
            grupos.setdefault(d.seccion, []).append(d)
        return list(grupos.items())


def cargar(ruta: Path | None = None) -> ListaChequeo:
    datos = yaml.safe_load((ruta or config.chequeo_path).read_text(encoding="utf-8"))
    return ListaChequeo.model_validate(datos)
