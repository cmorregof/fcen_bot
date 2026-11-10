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

from app.core.config import settings


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
    # El primero firma el oficio y el acta (su imagen de firma, fuera del
    # repositorio: docs/integrantes-y-firmas.md).
    miembros: tuple[Miembro, ...] = field(default=())
    # Cargo de la representación estudiantil, si el comité la tiene. El nombre
    # es un dato personal y no va en el repositorio: sale de la variable
    # REPRESENTANTES_ESTUDIANTILES (docs/integrantes-y-firmas.md).
    representante_estudiantil: str | None = None

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
    # Los posgrados de matemáticas tienen su propia dirección y su propia
    # administrativa (posmate_man): no ven los pregrados del área ni al revés.
    # El nombre oficial está pendiente de confirmar.
    "posgrados_matematicas": Direccion(
        "posgrados_matematicas", "Dirección de Posgrados de Matemáticas"
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
            # Correo de la administrativa del área, 3-nov-2026.
            miembros=(
                Miembro(
                    "David Leonardo Ocampo Rodríguez",
                    "Coordinador Área Curricular de Matemáticas",
                ),
                Miembro("Jairo Alonso Ayala Molina", "Representante Profesoral"),
                Miembro(
                    "Diana Milena Sánchez Monsalve",
                    "Representante Profesoral",
                    "La profesora",
                ),
            ),
            representante_estudiantil="Representante Estudiantil (suplente)",
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
            # Correo de la administrativa del área, 3-nov-2026.
            miembros=(
                Miembro(
                    "Fabián Fernando Serrano Suarez",
                    "Coordinador Ciencias de la Computación",
                ),
                Miembro("David Leonardo Ocampo Rodríguez", "Representante Profesoral"),
                Miembro("David Angulo García", "Representante Profesoral"),
            ),
        ),
        # Posgrados. Los integrantes del comité, el correo, la extensión, el
        # código del plan y el prefijo del radicado se agregan cuando los
        # confirme cada programa. No se inventan.
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
            direccion="posgrados_matematicas",
            nivel="posgrado",
            alias=(
                "maestria en ciencias - matematica aplicada",
                "maestria en ciencias matematica aplicada",
            ),
        ),
        Programa(
            clave="mecen",
            nombre="Maestría en Enseñanza de las Ciencias Exactas y Naturales",
            direccion="posgrados_matematicas",
            nivel="posgrado",
            alias=(
                "maestria en ensenanza de las ciencias exactas y naturales",
                "mecen",
            ),
        ),
        Programa(
            clave="esp_actuaria",
            nombre="Especialización en Actuaría",
            direccion="posgrados_matematicas",
            nivel="posgrado",
            alias=("especializacion en actuaria",),
        ),
        Programa(
            clave="esp_estadistica",
            nombre="Especialización en Estadística",
            direccion="posgrados_matematicas",
            nivel="posgrado",
            alias=("especializacion en estadistica",),
        ),
        Programa(
            clave="dcm",
            nombre="Doctorado en Ciencias - Matemáticas",
            direccion="posgrados_matematicas",
            nivel="posgrado",
            alias=(
                "doctorado en ciencias - matematicas",
                "doctorado en ciencias matematicas",
            ),
        ),
        Programa(
            clave="estadistica",
            nombre="Estadística",
            direccion="matematicas",
            alias=("estadistica",),
            # Correo de la administrativa del área, 3-nov-2026.
            miembros=(
                Miembro(
                    "Nubia Esteban Duarte",
                    "Coordinadora programa curricular de Estadística",
                    "La profesora",
                ),
                Miembro("David Leonardo Ocampo Rodríguez", "Representante Profesoral"),
                Miembro("José Hernán Parra Sánchez", "Representante Profesoral"),
            ),
        ),
    )
}


def integrantes(programa: Programa) -> tuple[Miembro, ...]:
    """Integrantes del comité para el acta.

    Si el comité tiene representación estudiantil, va al final con el nombre
    de REPRESENTANTES_ESTUDIANTILES. Si no está configurado, el nombre queda
    vacío y el acta lo marca en amarillo.
    """
    if not programa.representante_estudiantil:
        return programa.miembros
    nombre = settings.representantes_por_programa.get(programa.clave, "")
    # Sin tratamiento: el concepto dice «<nombre> expresa…».
    representante = Miembro(nombre, programa.representante_estudiantil, "")
    return (*programa.miembros, representante)


def integrantes_con_nombre(programa: Programa | None) -> tuple[Miembro, ...]:
    """Los integrantes a los que se les puede atribuir un concepto."""
    if programa is None:
        return ()
    return tuple(m for m in integrantes(programa) if m.nombre)


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def programas_de(direccion: str) -> list[Programa]:
    return [p for p in PROGRAMAS.values() if p.direccion == direccion]


def identificar_programa(
    plan_codigo: str | None, plan_nombre: str | None
) -> Programa | None:
    """Código del plan primero; si no se conoce, el nombre del plan.

    Gana el alias más largo que aparezca en el nombre: «Doctorado en Ciencias -
    Matemáticas» contiene «matematicas», pero es el doctorado, no el pregrado.
    """
    if plan_codigo:
        codigo = plan_codigo.strip()
        for programa in PROGRAMAS.values():
            if codigo in programa.planes:
                return programa
    if plan_nombre:
        nombre = normalizar(plan_nombre)
        mejor: Programa | None = None
        largo = 0
        for programa in PROGRAMAS.values():
            for alias in programa.alias:
                if (alias == nombre or alias in nombre) and len(alias) > largo:
                    mejor, largo = programa, len(alias)
        return mejor
    return None


def programa_unico(direccion: str) -> Programa | None:
    """Si la dirección tiene un solo programa, no hay que preguntar cuál."""
    lista = programas_de(direccion)
    return lista[0] if len(lista) == 1 else None
