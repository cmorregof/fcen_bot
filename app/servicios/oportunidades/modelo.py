"""Tipos del servicio: lo que lee el modelo y los estados de una oferta."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

TipoOferta = Literal["empleo", "practica", "pasantia", "convocatoria", "beca"]
Modalidad = Literal["presencial", "remota", "hibrida", "sin_dato"]
Estado = Literal["encontrada", "verificada", "aprobada", "publicada", "descartada"]

TIPOS: tuple[TipoOferta, ...] = (
    "empleo",
    "practica",
    "pasantia",
    "convocatoria",
    "beca",
)
ESTADOS: tuple[Estado, ...] = (
    "encontrada",
    "verificada",
    "aprobada",
    "publicada",
    "descartada",
)
NOMBRE_ESTADO: dict[str, str] = {
    "encontrada": "Encontrada",
    "verificada": "Verificada",
    "aprobada": "Aprobada para boletín",
    "publicada": "Publicada",
    "descartada": "Descartada",
}
NOMBRE_TIPO: dict[str, str] = {
    "empleo": "Empleo",
    "practica": "Práctica",
    "pasantia": "Pasantía",
    "convocatoria": "Convocatoria",
    "beca": "Beca",
}


class OfertaLeida(BaseModel):
    """Una oferta tal como la lee el modelo en la página de una fuente."""

    titulo: str = Field(
        description="Nombre del cargo, práctica o convocatoria, tal cual"
    )
    entidad: str = Field(description="Empresa o entidad que ofrece, tal cual")
    tipo: TipoOferta
    url: str = Field(
        description="Enlace de la oferta, copiado de la página. Si no hay uno propio, "
        "el de la página"
    )
    resumen: str = Field(
        description="Una o dos frases con lo que ofrece. Sin nombres ni datos de "
        "contacto de personas"
    )
    requisitos: str = Field(
        default="", description="Requisitos tal como aparecen (formación, semestre…)"
    )
    areas: list[str] = Field(
        default_factory=list,
        description="Carreras o áreas de formación que pide la oferta, tal cual",
    )
    programas: list[str] = Field(
        default_factory=list,
        description="Claves de programas FCEN de la lista dada a los que aplica",
    )
    fecha_cierre: date | None = Field(
        default=None, description="Fecha de cierre AAAA-MM-DD, solo si aparece"
    )
    modalidad: Modalidad = "sin_dato"
    lugar: str = Field(default="", description="Ciudad o lugar, si aparece")
    dudas: list[str] = Field(
        default_factory=list,
        description="Lo que no está claro y una persona debe revisar (fecha "
        "ambigua, programa dudoso, enlace roto…). Vacío si nada",
    )


class PaginaLeida(BaseModel):
    ofertas: list[OfertaLeida] = Field(default_factory=list)
