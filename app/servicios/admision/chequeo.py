"""Lista de chequeo por documento (config/admision/chequeo.yaml, editable)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from app.servicios.admision.config import config


class Documento(BaseModel):
    clave: str
    nombre: str
    seccion: str
    chequeo: list[str]


class ListaChequeo(BaseModel):
    documentos: list[Documento]

    def buscar(self, clave: str) -> Documento | None:
        return next((d for d in self.documentos if d.clave == clave), None)


def cargar(ruta: Path | None = None) -> ListaChequeo:
    datos = yaml.safe_load((ruta or config.chequeo_path).read_text(encoding="utf-8"))
    return ListaChequeo.model_validate(datos)
