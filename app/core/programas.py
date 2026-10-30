"""Programas curriculares y direcciones de área.

Cada programa tiene su propio comité asesor, así que cada uno produce su propio
borrador. El programa de un caso se reconoce por el código o el nombre del
plan de estudios que aparece en el pantallazo del SIA.

Los datos marcados como None no se conocen todavía y se piden cuando hagan
falta (por ejemplo, el prefijo del radicado al firmar).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Direccion:
    clave: str
    nombre: str


@dataclass(frozen=True)
class Miembro:
    """Integrante del comité asesor, como aparece en ASISTENTES del acta."""

    nombre: str
    cargo: str
    tratamiento: str = "El profesor"  # «El profesor» o «La profesora»


@dataclass(frozen=True)
class Programa:
    clave: str
    nombre: str
    direccion: str
    planes: tuple[str, ...] = ()
    correo: str | None = None
    extension: str | None = None
    radicado_prefijo: str | None = None
    # En posgrado las asignaturas se llaman «cursos» en el oficio.
    nivel: Literal["pregrado", "posgrado"] = "pregrado"
    # Los créditos disciplinares exigidos para inscribir Trabajo de Grado están
    # en config/solicitudes.yaml (umbrales.tdg_creditos_disciplinares).
    alias: tuple[str, ...] = field(default=())
    # Integrantes del comité (de la última acta conocida). Si cambian, se
    # actualizan aquí; los que no están se pueden escribir a mano en el bot.
    miembros: tuple[Miembro, ...] = field(default=())

    @property
    def comite(self) -> str:
        return f"Comité Asesor del Programa Curricular de {self.nombre}"

    @property
    def encabezado(self) -> str:
        return f"Programa Curricular de {self.nombre}"


DIRECCIONES: dict[str, Direccion] = {
    "ciencias_naturales": Direccion(
        "ciencias_naturales", "Área Curricular de Ciencias Naturales"
    ),
    "matematicas": Direccion(
        "matematicas", "Área Curricular de Matemáticas y Estadística"
    ),
}

PROGRAMAS: dict[str, Programa] = {
    p.clave: p
    for p in (
        Programa(
            clave="ing_fisica",
            nombre="Ingeniería Física",
            direccion="ciencias_naturales",
            planes=("4030",),
            correo="caringfis_man@unal.edu.co",
            extension="55633",
            radicado_prefijo="Mz.FCEN.1.066",
            alias=("ingenieria fisica",),
            # Acta 19 de 2026.
            miembros=(
                Miembro(
                    "Jorge Eduardo Giraldo Aristizábal",
                    "Director Área Curricular Ciencias Naturales, quien lo preside",
                ),
                Miembro("Jairo de Jesús Agudelo Calle", "Representante Profesoral"),
                Miembro(
                    "Elisabeth Restrepo Parra",
                    "Representante Profesoral",
                    "La profesora",
                ),
            ),
        ),
        Programa(
            clave="ing_biologica",
            nombre="Ingeniería Biológica",
            direccion="ciencias_naturales",
            correo="ingbiologica_man@unal.edu.co",
            extension="55633",
            alias=("ingenieria biologica",),
        ),
        Programa(
            clave="matematicas",
            nombre="Matemáticas",
            direccion="matematicas",
            alias=("matematicas",),
        ),
        Programa(
            clave="ciencias_computacion",
            nombre="Ciencias de la Computación",
            direccion="matematicas",
            planes=("4034",),
            correo="carcomp_man@unal.edu.co",
            extension="55634",
            radicado_prefijo="Mz.FCEN.1.065",
            alias=("ciencias de la computacion",),
            # Acta 35 de 2026.
            miembros=(
                Miembro(
                    "Olmer Folleco Solarte",
                    "Coordinador Área de Matemáticas y Estadística",
                ),
                Miembro(
                    "Fabián Fernando Serrano Suárez",
                    "Coordinador Ciencias de la Computación",
                ),
                Miembro("David Angulo García", "Representante Profesoral"),
            ),
        ),
        # Posgrados. Los integrantes del comité, el correo y el prefijo del
        # radicado se agregan cuando los confirme cada programa.
        Programa(
            clave="mcf",
            nombre="Maestría en Ciencias - Física",
            direccion="ciencias_naturales",
            nivel="posgrado",
            alias=("maestria en ciencias - fisica", "maestria en ciencias fisica"),
        ),
        Programa(
            clave="mcma",
            nombre="Maestría en Ciencias - Matemática Aplicada",
            direccion="matematicas",
            nivel="posgrado",
            alias=(
                "maestria en ciencias - matematica aplicada",
                "maestria en ciencias matematica aplicada",
            ),
        ),
        Programa(
            clave="mecen",
            nombre="Maestría en Enseñanza de las Ciencias Exactas y Naturales",
            direccion="matematicas",
            nivel="posgrado",
            alias=(
                "maestria en ensenanza de las ciencias exactas y naturales",
                "mecen",
            ),
        ),
        Programa(
            clave="estadistica",
            nombre="Estadística",
            direccion="matematicas",
            alias=("estadistica",),
        ),
    )
}


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def programas_de(direccion: str) -> list[Programa]:
    return [p for p in PROGRAMAS.values() if p.direccion == direccion]


def identificar_programa(
    plan_codigo: str | None, plan_nombre: str | None
) -> Programa | None:
    """Código del plan primero; si no se conoce, el nombre del plan."""
    if plan_codigo:
        codigo = plan_codigo.strip()
        for programa in PROGRAMAS.values():
            if codigo in programa.planes:
                return programa
    if plan_nombre:
        nombre = normalizar(plan_nombre)
        for programa in PROGRAMAS.values():
            if any(alias == nombre or alias in nombre for alias in programa.alias):
                return programa
    return None
