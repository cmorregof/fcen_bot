"""Normas base por tipo de solicitud (fase 1, sin RAG).

Los textos son literales. `verificada=True` significa que el texto se copió del
PDF de la norma que está en la carpeta de reglamentación. `verificada=False`
significa que se copió de como aparece transcrito en un acta, porque el PDF de
la norma todavía no está en la carpeta (el Estatuto Estudiantil, la Res.
CFCEN-060-2008). En la fase 2 todos estos textos salen del índice de normativa.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.caso import TipoSolicitud


@dataclass(frozen=True)
class NormaCitada:
    norma: str
    articulo: str
    texto: str
    verificada: bool
    solo_programa: str | None = None


ACUERDO_008_ART_10 = NormaCitada(
    norma="Acuerdo 008 de 2008 del Consejo Superior Universitario",
    articulo="Artículo 10 y parágrafo",
    texto=(
        "ARTÍCULO 10. En cada período académico los estudiantes o admitidos a un "
        "programa de pregrado deberán inscribir asignaturas que sumen diez (10) "
        "créditos como mínimo.\n"
        "PARÁGRAFO. Los Consejos de Facultad podrán autorizar la inscripción de "
        "asignaturas o actividades académicas con un número inferior de créditos, "
        "previa solicitud justificada del estudiante."
    ),
    verificada=False,
)

ACUERDO_350_ART_1_2 = NormaCitada(
    norma="Acuerdo 350 de 2021 del Consejo Superior Universitario",
    articulo="Artículos 1 y 2",
    texto=(
        "ARTÍCULO 1. Delegar en los Consejos de Facultad o quien haga sus veces la "
        "potestad de estudiar y decidir, con carácter de excepción, las solicitudes "
        "de inscripción de asignaturas o actividades académicas presentadas con "
        "posterioridad al período de inscripciones definido por el calendario "
        "académico, siempre y cuando se mantenga el mínimo de créditos exigibles de "
        "inscripción según los artículos 9 y 10 del Acuerdo 008 de 2008 del Consejo "
        "Superior Universitario.\n"
        "ARTÍCULO 2. Delegar en los Consejos de Facultad o quien haga sus veces la "
        "potestad de estudiar y decidir, con carácter de excepción, las solicitudes "
        "de adición de asignaturas o actividades académicas presentadas con "
        "posterioridad a las dos primeras semanas de clase del período académico."
    ),
    verificada=True,
)

ACUERDO_027_ART_1 = NormaCitada(
    norma="Acuerdo 027 de 2024 del Consejo Superior Universitario",
    articulo="Artículo 1 (modifica el artículo 3 del Acuerdo 350 de 2021)",
    texto=(
        "ARTÍCULO 3. Para el estudio y decisión de las excepciones normativas "
        "delegadas en los artículos 1 y 2 del presente Acuerdo, los Consejos de "
        "Facultad o quien haga sus veces deberán tener en cuenta los siguientes "
        "criterios:\n"
        "1. El Comité Asesor de Programa Curricular o quien haga sus veces deberá "
        "emitir concepto sobre la solicitud presentada.\n"
        "2. Contar con disponibilidad de cupos.\n"
        "3. En el caso de asignaturas se podrá autorizar la excepción siempre y "
        "cuando la solicitud haya sido presentada hasta la semana 10 del período "
        "académico para el cual se requiere la misma. Cuando corresponde a las "
        "asignaturas: Trabajo de Grado, en cualquier modalidad, Práctica o Pasantía, "
        "la autorización podrá darse hasta la semana 13 del periodo académico para "
        "el cual se requiere la misma.\n"
        "4. En el caso de actividades académicas se podrá autorizar la excepción "
        "siempre y cuando la solicitud haya sido presentada hasta la semana 13 del "
        "período académico para el cual se requiere la misma."
    ),
    verificada=True,
)

RES_CFCEN_060_ART_5 = NormaCitada(
    norma="Resolución CFCEN-060 de 2008",
    articulo="Artículo 5 y parágrafo",
    texto=(
        "ARTÍCULO 5. Las modalidades de Trabajo de grado para los estudiantes del "
        "Programa de Ingeniería Física de la Facultad de Ciencias Exactas y "
        "Naturales de la Sede Manizales serán: Trabajos investigativos, Prácticas "
        "de extensión y Asignaturas de posgrado.\n"
        "PARÁGRAFO. Para inscribir Trabajo de grado el estudiante debe haber "
        "aprobado 46 créditos del componente disciplinar o profesional (80% del "
        "total de créditos exigidos de este componente)."
    ),
    verificada=False,
    solo_programa="ing_fisica",
)

PAE_PROCEDIMIENTO = NormaCitada(
    norma="Procedimiento para solicitud de Práctica Académica Especial – PAE "
    "(U.PR.05.007.008)",
    articulo="Condiciones generales",
    texto=(
        "La Práctica Académica Especial –PAE-, se le asignarán créditos como parte "
        "del componente de libre elección, sin exceder el 5% del total de créditos "
        "del plan de estudios y su calificación será numérica.\n"
        "Para que una Práctica Académica Especial- PAE- pueda ser cursada en "
        "determinado período académico deberá estar aprobada previamente por el "
        "Consejo de Facultad, o quien haga sus veces, que es la instancia que "
        "determinará el número de créditos dependiendo de la intensidad horaria o "
        "la dedicación que tendrá el estudiante en el desarrollo de esa Práctica "
        "Académica Especial – PAE-."
    ),
    verificada=True,
)

# Normas transcritas, por el nombre con que las cita config/solicitudes.yaml.
# Qué normas acompañan a cada tipo de solicitud se define en ese archivo.
NORMAS: dict[str, NormaCitada] = {
    "ACUERDO_008_ART_10": ACUERDO_008_ART_10,
    "ACUERDO_350_ART_1_2": ACUERDO_350_ART_1_2,
    "ACUERDO_027_ART_1": ACUERDO_027_ART_1,
    "RES_CFCEN_060_ART_5": RES_CFCEN_060_ART_5,
    "PAE_PROCEDIMIENTO": PAE_PROCEDIMIENTO,
}


def normas_para(tipos: list[TipoSolicitud], programa: str | None) -> list[NormaCitada]:
    """Normas base del caso, sin repetir y respetando las de un solo programa."""
    # Import diferido: app.core.solicitudes valida contra NORMAS.
    from app.core import solicitudes

    config = solicitudes.actual()
    vistas: list[NormaCitada] = []
    for tipo in tipos:
        for ref in config.ruta(tipo).normas:
            norma = NORMAS[ref]
            if norma.solo_programa and norma.solo_programa != programa:
                continue
            if norma not in vistas:
                vistas.append(norma)
    return vistas
