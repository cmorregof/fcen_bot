"""Filtro de nombres de personas para el borrador de avance.

Es una RED DE SEGURIDAD, no una garantía: con expresiones regulares no se
detectan todos los nombres. Detecta (a) los nombres que el plan trae en los
campos de responsables, (b) un título («prof.», «dra.», «ing.»…) seguido de
nombre o apellido, (c) «con/por» seguido de dos o tres palabras con mayúscula,
(d) correos y teléfonos. Los cargos y las dependencias («Dirección del
programa», «Facultad de Ciencias Exactas») no cuentan como nombres. La
revisión de Calidad antes de usar el borrador es obligatoria.
"""

from __future__ import annotations

import re
import unicodedata
from itertools import combinations

from app.servicios.calidad.plan import PlanGuardado
from app.servicios.calidad.plantilla import plegar

CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TELEFONO = re.compile(r"(?<!\d)(?:\+?57)?\s?3\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")

# Títulos de persona: con ellos, una palabra en minúscula también es un nombre.
_TITULOS_PERSONALES = {
    plegar(t)
    for t in (
        "prof profesor profesora dr dra doctor doctora ing ingeniero ingeniera "
        "lic licenciado licenciada mg mag magister msc phd sr sra srta señor "
        "señora don doña"
    ).split()
}
# Títulos de cargo: solo preceden a un nombre si este empieza con mayúscula.
_TITULOS_CARGO = {
    plegar(t)
    for t in (
        "estudiante docente director directora coordinador coordinadora decano "
        "decana jefe secretario secretaria asesor asesora egresado egresada"
    ).split()
}
_TITULO = re.compile(
    r"(?<![^\W\d_])(?:"
    + "|".join(
        sorted((re.escape(t) for t in _TITULOS_PERSONALES | _TITULOS_CARGO), key=len)[
            ::-1
        ]
    )
    + r")\b\.?",
    re.I,
)

# Palabras de cargos y dependencias: lo que SÍ puede escribirse.
_CARGOS = {
    plegar(p)
    for p in (
        "dirección direccion director directora coordinación coordinacion "
        "coordinador coordinadora comité comite asesor asesora oficina calidad "
        "programa facultad decanatura decano decana vicedecanatura consejo sede "
        "secretaría secretaria académica academica área area unidad jefe jefatura "
        "profesor profesora docente docentes estudiantes estudiante bienestar "
        "departamento escuela maestría maestria doctorado posgrado pregrado "
        "curricular grupo equipo ejemplo ficticio universidad nacional manizales "
        "investigación investigacion extensión extension acreditación acreditacion "
        "autoevaluación autoevaluacion sistema servicio apoyo gestión gestion "
        "ciencias exactas naturales ingeniería ingenieria arquitectura "
        "administración administracion humanas económicas economicas sociales "
        "salud artes educación educacion física fisica química quimica "
        "matemáticas matematicas biología biologia geología geologia "
        "estadística estadistica computación computacion ambiental biotecnología "
        "biotecnologia ecología ecologia currículo curriculo plan mejoramiento "
        "colombia caldas egresados egresado egresada asesores"
    ).split()
}
# Palabras funcionales que no son nombres.
_FUNCION = {
    plegar(p)
    for p in (
        "de del la el los las un una unos unas y e o u a al en se su sus lo no "
        "que quien para por con sin sobre como mas ya tambien durante ante hasta "
        "desde entre es son fue fueron ser esta este estos estas ese esa cada "
        "todo todos toda todas nuestro nuestra"
    ).split()
}
_ENLACES = _FUNCION  # compatibilidad con el nombre anterior
_PALABRA = re.compile(r"[^\W\d_]+")


def _es_nombre(palabra: str, minuscula_ok: bool) -> bool:
    p = plegar(palabra)
    if len(p) < 2 or p in _CARGOS or p in _FUNCION:
        return False
    return minuscula_ok or palabra[:1].isupper()


def nombres_en_plan(pg: PlanGuardado) -> set[str]:
    """Nombres de personas que el plan trae en los campos de responsables.

    Un segmento se toma como nombre si, quitando palabras de cargos y
    conectores, le quedan dos o más palabras con mayúscula inicial. Se guarda
    el nombre completo y cada par ordenado de sus palabras («nombre apellido»).
    """
    campos: list[str] = []
    for a in pg.plan.acciones:
        campos.append(a.responsables)
        campos += [t.responsable for t in a.tareas]
    nombres: set[str] = set()
    for campo in campos:
        for segmento in re.split(r"[,;/\n]|\s+y\s+|\s+e\s+", campo or ""):
            restantes = [p for p in _PALABRA.findall(segmento) if _es_nombre(p, False)]
            if len(restantes) >= 2:
                nombres.add(" ".join(restantes))
                nombres.update(f"{a} {b}" for a, b in combinations(restantes, 2))
    return nombres


def _plano(texto: str, invisible_es_espacio: bool = False) -> tuple[str, list[int]]:
    """Minúsculas, sin tildes ni caracteres invisibles y con espacios simples,
    con la posición original de cada carácter."""
    salida: list[str] = []
    mapa: list[int] = []
    for i, ch in enumerate(texto):
        if unicodedata.category(ch) in ("Cf", "Cc") and not ch.isspace():
            if not invisible_es_espacio:
                continue
            ch = " "
        for d in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(d):
                continue
            if d.isspace():
                if salida and salida[-1] == " ":
                    continue
                d = " "
            salida.append(d.lower())
            mapa.append(i)
    return "".join(salida), mapa


def _tramos_conocidos(texto: str, nombres: set[str]) -> list[tuple[int, int]]:
    tramos: list[tuple[int, int]] = []
    # Un carácter invisible entre palabras puede ser un separador («Zoila<ZWSP>
    # Pérez») o parte de una palabra («Zo<ZWSP>ila»): se prueban las dos lecturas.
    for como_espacio in (False, True):
        plano, mapa = _plano(texto, como_espacio)
        for nombre in nombres:
            buscado = _plano(nombre)[0].strip()
            if not buscado:
                continue
            for m in re.finditer(rf"(?<!\w){re.escape(buscado)}(?!\w)", plano):
                tramos.append((mapa[m.start()], mapa[m.end() - 1] + 1))
    return tramos


def _tramos_genericos(texto: str) -> list[tuple[int, int]]:
    """Título + nombre(s) y «con/por» + nombre completo."""
    tramos: list[tuple[int, int]] = []
    for m in _TITULO.finditer(texto):
        titulo = plegar(m.group(0).rstrip("."))
        personal = titulo in _TITULOS_PERSONALES
        fin = m.end()
        capturadas = 0
        for p in re.finditer(r"\s+([^\W\d_]+)", texto[fin:]):
            if capturadas == 3 or not _es_nombre(p.group(1), personal):
                break
            capturadas += 1
            fin += p.end()
        if capturadas:
            tramos.append((m.start(), fin))
    for m in re.finditer(
        r"\b(?:con|por)\s+((?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+){1,2}[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)",
        texto,
    ):
        palabras = _PALABRA.findall(m.group(1))
        if all(_es_nombre(p, False) for p in palabras):
            tramos.append((m.start(1), m.end(1)))
    return tramos


def ocultar(texto: str, nombres: set[str]) -> str:
    """Quita nombres, títulos con nombre, correos y teléfonos antes de mandar o
    mostrar texto del plan o de los soportes."""
    marcados = [(i, f, "[responsable]") for i, f in _tramos_conocidos(texto, nombres)]
    marcados += [(i, f, "[persona]") for i, f in _tramos_genericos(texto)]
    fusion: list[tuple[int, int, str]] = []
    for ini, fin, rotulo in sorted(marcados):
        if fusion and ini <= fusion[-1][1]:
            previo = fusion[-1]
            fusion[-1] = (previo[0], max(previo[1], fin), previo[2])
        else:
            fusion.append((ini, fin, rotulo))
    for ini, fin, rotulo in reversed(fusion):
        texto = texto[:ini] + rotulo + texto[fin:]
    texto = CORREO.sub("[correo]", texto)
    return TELEFONO.sub("[teléfono]", texto)


def con_nombre_de_persona(texto: str, nombres: set[str]) -> bool:
    """Verificación de la salida: un nombre conocido, un título con nombre,
    «con/por» + nombre completo, un correo o un teléfono."""
    return (
        bool(CORREO.search(texto) or TELEFONO.search(texto))
        or bool(_tramos_conocidos(texto, nombres))
        or bool(_tramos_genericos(texto))
    )
