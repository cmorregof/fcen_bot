"""Programas curriculares, direcciones de área y comités asesores.

En pregrado cada programa tiene su propio comité asesor, así que cada uno
produce su propio borrador, su acta y su consecutivo. Una dirección con
`comite_unico` (los posgrados de Ciencias Exactas) tiene un solo comité para
todos sus programas: un solo borrador, una sola acta y un solo consecutivo,
con la clave de la dirección (`comite_de`, `COMITES`). El programa de un caso
se reconoce por el código o el nombre del plan de estudios que aparece en el
pantallazo del SIA.

Los datos marcados como None no se conocen todavía y se piden cuando hagan
falta (por ejemplo, el prefijo del radicado al firmar).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from app.core.config import settings


@dataclass(frozen=True)
class Miembro:
    """Integrante del comité asesor, como aparece en ASISTENTES del acta."""

    nombre: str
    cargo: str
    tratamiento: str = "El profesor"  # «El profesor» o «La profesora»
    # Cargo bajo la firma, si no es el de ASISTENTES sin lo que sigue a la coma.
    cargo_firma: str | None = None

    @property
    def cargo_bajo_firma(self) -> str:
        return self.cargo_firma or self.cargo.split(",")[0]


@dataclass(frozen=True)
class UltimaActa:
    """La última acta del comité numerada por fuera de MemorIA. El consecutivo
    sigue desde ahí en ese año (actas_comite.proponer_numero)."""

    anio: int
    numero: int


@dataclass(frozen=True)
class Direccion:
    clave: str
    nombre: str
    # Un solo comité asesor para todos los programas de la dirección (acta,
    # consecutivo, firma e integrantes de la dirección, no de cada programa).
    # Lo que sigue solo aplica con comite_unico.
    comite_unico: bool = False
    nombre_comite: str | None = None
    miembros: tuple[Miembro, ...] = ()
    ultima_acta: UltimaActa | None = None
    correo: str | None = None
    extension: str | None = None
    radicado_prefijo: str | None = None


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
    # Solo en el comité único de una dirección (`COMITES`): su nombre oficial,
    # los programas que cubre y la última acta numerada por fuera de MemorIA.
    nombre_comite: str | None = None
    programas: tuple[str, ...] = ()
    ultima_acta: UltimaActa | None = None

    @property
    def comite(self) -> str:
        if self.nombre_comite:
            return self.nombre_comite
        return f"Comité Asesor del Programa Curricular de {self.nombre}"

    @property
    def encabezado(self) -> str:
        if self.es_comite_unico:
            return self.nombre
        return f"Programa Curricular de {self.nombre}"

    @property
    def es_comite_unico(self) -> bool:
        """El comité de una dirección entera, no el de un programa."""
        return bool(self.programas)


DIRECCIONES: dict[str, Direccion] = {
    "ciencias_naturales": Direccion(
        "ciencias_naturales", "Área Curricular de Ciencias Naturales"
    ),
    "matematicas": Direccion(
        "matematicas", "Área Curricular de Matemáticas y Estadística"
    ),
    # Los posgrados de Ciencias Exactas tienen su propia dirección y su propia
    # administrativa (posmate_man): no ven los pregrados del área ni al revés.
    # La clave interna sigue siendo posgrados_matematicas (casos, usuarios,
    # firmas y actas ya guardados la usan). Nombre, comité, integrantes y
    # firma: encabezado del acta 029, que envió la administrativa de posgrados
    # el 10-nov-2026.
    "posgrados_matematicas": Direccion(
        "posgrados_matematicas",
        "Área Curricular de Posgrados de Ciencias Exactas",
        comite_unico=True,
        nombre_comite=(
            "Comité Asesor de Posgrados del Área Curricular de Ciencias Exactas"
        ),
        miembros=(
            Miembro(
                "David Leonardo Ocampo Rodríguez",
                "Director de Área Curricular Posgrados del Área de Ciencias Exactas",
                cargo_firma=(
                    "Director Área Curricular Posgrados Ciencias Exactas Naturales"
                ),
            ),
            Miembro(
                "Jaider Albeiro Figueroa Flórez",
                "coordinador de la Maestría en Enseñanza de las Ciencias Exactas "
                "y Naturales",
            ),
            Miembro(
                "Nubia Esteban Duarte",
                "coordinadora de la Especialización en Estadística",
                "La profesora",
            ),
            Miembro(
                "David Leonardo Ocampo Rodríguez",
                "coordinador de la Especialización en Actuaría y Finanzas",
            ),
            Miembro(
                "Emer Jesús Lopera Arias",
                "miembro del personal académico de la respectiva área",
            ),
            Miembro(
                "Simeón Casanova Trujillo",
                "miembro del personal académico de la respectiva área",
            ),
        ),
        # Acta 029, enviada el 10-nov-2026: la siguiente que se propone es la
        # 030. Si la numeración cambia, se corrige aquí.
        ultima_acta=UltimaActa(anio=2026, numero=29),
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
            # La clave sigue siendo esp_actuaria; el nombre oficial es
            # «Especialización en Actuaría y Finanzas» (acta 029).
            clave="esp_actuaria",
            nombre="Especialización en Actuaría y Finanzas",
            direccion="posgrados_matematicas",
            nivel="posgrado",
            alias=(
                "especializacion en actuaria y finanzas",
                "especializacion en actuaria",
            ),
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


def _comite_unico(direccion: Direccion) -> Programa:
    """El comité de una dirección con comite_unico, con la forma de un
    programa: la clave de la dirección es la del acta, el consecutivo y la
    imagen de firma."""
    del_area = tuple(
        p.clave for p in PROGRAMAS.values() if p.direccion == direccion.clave
    )
    niveles = {PROGRAMAS[c].nivel for c in del_area}
    return Programa(
        clave=direccion.clave,
        nombre=direccion.nombre,
        direccion=direccion.clave,
        correo=direccion.correo,
        extension=direccion.extension,
        radicado_prefijo=direccion.radicado_prefijo,
        nivel="posgrado" if niveles == {"posgrado"} else "pregrado",
        miembros=direccion.miembros,
        nombre_comite=direccion.nombre_comite,
        programas=del_area,
        ultima_acta=direccion.ultima_acta,
    )


# Comités únicos, con la clave de su dirección. No son programas: no entran en
# el selector de programa de un caso ni en identificar_programa.
COMITES: dict[str, Programa] = {
    d.clave: _comite_unico(d) for d in DIRECCIONES.values() if d.comite_unico
}
assert not set(COMITES) & set(PROGRAMAS), (
    "Un comité no puede usar la clave de un programa"
)


def comite_de(clave: str | None) -> Programa | None:
    """El comité que trata los casos de un programa: el mismo programa en
    pregrado, o el comité único de su dirección. También acepta la clave de un
    comité (la que queda en firmas y actas_comite)."""
    if clave is None:
        return None
    if clave in COMITES:
        return COMITES[clave]
    programa = PROGRAMAS.get(clave)
    if programa is None:
        return None
    return COMITES.get(programa.direccion, programa)


def comites_de(direccion: str) -> list[Programa]:
    """Los comités de la dirección: uno por programa o el comité único."""
    if direccion in COMITES:
        return [COMITES[direccion]]
    return programas_de(direccion)


def programas_del_comite(comite: Programa) -> tuple[str, ...]:
    """Las claves de los programas cuyos casos trata el comité."""
    return comite.programas or (comite.clave,)


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
    # Una persona con dos cargos en el comité (en posgrados, el director también
    # coordina un programa) da su concepto una sola vez.
    vistos: set[str] = set()
    con_nombre: list[Miembro] = []
    for m in integrantes(programa):
        if m.nombre and m.nombre not in vistos:
            vistos.add(m.nombre)
            con_nombre.append(m)
    return tuple(con_nombre)


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
