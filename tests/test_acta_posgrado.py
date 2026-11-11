"""Solicitudes y acta del Comité Asesor de Posgrados de Ciencias Exactas.

Todo con datos inventados: nombres, documentos, códigos, títulos y eventos
son ficticios. La estructura sigue la de las actas de ese comité
(docs/solicitudes-posgrado.md).
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

import aiosqlite
import pytest
from docx import Document

from app.core.programas import COMITES, PROGRAMAS
from app.integrations.claude import Resultado
from app.prompts.extraccion import SISTEMA_EXTRACCION
from app.schemas.caso import (
    ASUNTOS_PROGRAMA,
    TIPOS_POSGRADO,
    AsignaturaSolicitada,
    Caso,
    Concepto,
    DatosSIA,
    EstadoCaso,
    EventoAcademico,
    ExtraccionCaso,
    Jurado,
    ProyectoTesis,
    Sentido,
    TipoSolicitud,
)
from app.services import extraccion as servicio_extraccion
from app.services.acta_posgrado import ordenados, titulo_punto
from app.services.documento import (
    CasoDocumento,
    DatosOficio,
    construir_acta,
    construir_oficio,
)
from app.services.reglas import analizar, completar_tipos
from tests.conftest import extraccion_ejemplo

POS = "posgrados_matematicas"
T = TipoSolicitud


def _e(**cambios: Any) -> ExtraccionCaso:
    base: dict[str, Any] = dict(
        nombre_estudiante="Persona Ficticia Uno",
        documento="1000000001",
        tratamiento="La estudiante",
        tipos=[T.OTRO],
        objeto_solicitud="lo que se pide",
        asignaturas=[],
        sia=None,
    )
    base.update(cambios)
    return extraccion_ejemplo(**base)


def _item(
    e: ExtraccionCaso,
    programa: str = "mcma",
    sentido: Sentido = Sentido.APROBAR,
    cuerpo: str = "Solicito el trámite por un motivo ficticio.",
    conceptos: list[Concepto] | None = None,
) -> CasoDocumento:
    caso = Caso(
        id=1,
        chat_id=1,
        direccion=POS,
        programa=programa,
        estado=EstadoCaso.LISTO,
        sentido=sentido,
        texto=cuerpo,
        extraccion=e,
        conceptos=conceptos or [],
    )
    a = analizar(e, PROGRAMAS[programa], periodo_inicio=None, hay_imagenes=False)
    return CasoDocumento(caso, e, a, cuerpo)


def _datos(*items: CasoDocumento, **kw: Any) -> DatosOficio:
    return DatosOficio(
        programa=COMITES[POS],
        fecha=date(2026, 11, 17),
        casos=list(items),
        elaboro="AB",
        miembros=COMITES[POS].miembros,
        **kw,
    )


def _texto(contenido: bytes) -> str:
    doc = Document(io.BytesIO(contenido))
    return "\n".join(p.text for p in doc.paragraphs)


def _acta(*items: CasoDocumento, **kw: Any) -> str:
    return _texto(construir_acta(_datos(*items, **kw), "2026-2S"))


# ---------------------------------------------------------------------------
# Casos inventados, uno por tipo de solicitud de posgrado
# ---------------------------------------------------------------------------


def cancelacion() -> CasoDocumento:
    e = _e(
        tipos=[T.CANCELACION],
        objeto_solicitud="cancelación del curso Análisis Ficticio",
        periodo_solicitado="2026-2S",
        asignaturas=[
            AsignaturaSolicitada(
                codigo="9900001",
                nombre="Análisis Ficticio",
                tipologia="L",
                creditos=4,
                accion="cancelar",
            )
        ],
    )
    return _item(e, "dcm")


def permiso() -> CasoDocumento:
    e = _e(
        tipos=[T.PERMISO_ACADEMICO],
        tratamiento="El estudiante",
        nombre_estudiante="Persona Ficticia Dos",
        documento="1000000002",
        objeto_solicitud="permiso académico para participar en un congreso",
        eventos=[
            EventoAcademico(
                nombre="Congreso Ficticio de Matemáticas",
                participacion="ponente",
                fechas_participacion="Del 2 al 6 de marzo de 2027",
                fechas_evento="Del 3 al 5 de marzo de 2027",
                lugar="Ciudad Ficticia",
            )
        ],
        anexos=["carta de aceptación de ponencia", "aval del director"],
    )
    return _item(e, "dcm")


def reingreso() -> CasoDocumento:
    e = _e(
        tipos=[T.REINGRESO],
        tratamiento="El estudiante",
        nombre_estudiante="Persona Ficticia Tres",
        documento="1000000003",
        objeto_solicitud="reingreso al programa",
        periodo_solicitado="2027-1S",
        radicado_portal="XX-000-1",
    )
    return _item(e, "mcma", Sentido.PENDIENTE)


def sustentacion() -> CasoDocumento:
    e = _e(
        tipos=[T.SUSTENTACION_TESIS],
        objeto_solicitud="registro de la calificación de la tesis de maestría",
        proyecto=ProyectoTesis(
            titulo="Un modelo ficticio de difusión",
            director="Profesor Ficticio A",
            actividad="Tesis de Maestría, código 9900002",
            fecha_sustentacion="2026-11-03",
            calificacion="Aprobado (AP)",
        ),
        jurados=[
            Jurado(nombre="Profesor Ficticio B", vinculacion="Universidad Ficticia"),
            Jurado(nombre="Profesor Ficticio C"),
        ],
    )
    return _item(e, "mcma")


def calificacion_tfm() -> CasoDocumento:
    e = _e(
        tipos=[T.CALIFICACION_TRABAJO_FINAL],
        objeto_solicitud="registro de la calificación del trabajo final de maestría",
        proyecto=ProyectoTesis(
            titulo="Una secuencia didáctica ficticia",
            director="Profesora Ficticia D",
            fecha_entrega="2026-08-01",
            calificacion="Aprobado (AP)",
        ),
        jurados=[Jurado(nombre="Profesor Ficticio E")],
    )
    return _item(e, "mecen")


def evaluadores() -> CasoDocumento:
    e = _e(
        tipos=[T.NOMBRAMIENTO_EVALUADORES],
        objeto_solicitud="nombramiento de evaluadores de la tesis de maestría",
        proyecto=ProyectoTesis(
            titulo="Otra tesis ficticia", director="Profesor Ficticio A"
        ),
        jurados=[
            Jurado(
                nombre="Profesora Ficticia F",
                vinculacion="Universidad Ficticia",
                correo="f@ejemplo.org",
            ),
            Jurado(nombre="Profesor Ficticio G"),
        ],
    )
    return _item(e, "mcma")


def propuesta_tfm() -> CasoDocumento:
    e = _e(
        tipos=[T.PROYECTO_TESIS],
        objeto_solicitud="aval del título y nombramiento del director del trabajo "
        "final de maestría",
        proyecto=ProyectoTesis(
            titulo="Propuesta ficticia de enseñanza",
            director="Profesora Ficticia D",
            objetivo_general="Objetivo general ficticio.",
            objetivos_especificos=["Primer objetivo ficticio.", "Segundo ficticio."],
        ),
    )
    return _item(e, "mecen")


def cambio_titulo() -> CasoDocumento:
    e = _e(
        tipos=[T.MODIFICACION_PROYECTO],
        objeto_solicitud="cambio de título del trabajo final de maestría",
        proyecto=ProyectoTesis(
            titulo_anterior="Título ficticio anterior",
            titulo="Título ficticio nuevo",
            director="Profesora Ficticia D",
        ),
    )
    return _item(e, "mecen")


def transito() -> CasoDocumento:
    e = _e(
        tipos=[T.TRANSITO_POSGRADO],
        objeto_solicitud="tránsito a la Maestría en Ciencias - Matemática Aplicada",
        programa_destino="Maestría en Ciencias - Matemática Aplicada",
        periodo_solicitado="2027-1S",
    )
    return _item(e, "esp_estadistica")


def examen() -> CasoDocumento:
    e = _e(
        tipos=[T.EXAMEN_CALIFICACION],
        objeto_solicitud="homologación del examen de calificación",
    )
    return _item(e, "dcm", Sentido.NO_APROBAR)


def exencion() -> CasoDocumento:
    e = _e(
        tipos=[T.EXENCION_PAGO],
        objeto_solicitud="exención de pago de derechos académicos",
        periodo_solicitado="2027-1S",
    )
    return _item(e, "mcma")


def desbloqueo() -> CasoDocumento:
    e = _e(
        tipos=[
            T.REEXPEDICION_RECIBO,
            T.DESBLOQUEO_HISTORIA,
            T.INSCRIPCION_EXTEMPORANEA,
        ],
        objeto_solicitud="reexpedición del recibo de pago, desbloqueo de la historia "
        "académica e inscripción del curso Seminario Ficticio",
        asignaturas=[
            AsignaturaSolicitada(
                codigo="9900003",
                nombre="Seminario Ficticio",
                grupo="1",
                tipologia="F",
                accion="inscribir",
            )
        ],
    )
    return _item(e, "dcm")


def asunto(tipo: TipoSolicitud, objeto: str, programa: str = "mecen") -> CasoDocumento:
    e = _e(
        nombre_estudiante=None,
        documento=None,
        tipos=[tipo],
        objeto_solicitud=objeto,
        presenta="El coordinador de la Maestría Ficticia",
    )
    return _item(e, programa, cuerpo="Propuesta ficticia del programa.")


def todos() -> list[CasoDocumento]:
    return [
        cancelacion(),
        permiso(),
        reingreso(),
        sustentacion(),
        calificacion_tfm(),
        evaluadores(),
        propuesta_tfm(),
        cambio_titulo(),
        transito(),
        examen(),
        exencion(),
        desbloqueo(),
        asunto(T.ADMISION_NO_MASIVA, "cronograma de admisión ficticio", "dcm"),
        asunto(T.CREACION_CURSO, "creación del curso «Curso Ficticio»", "mcma"),
        asunto(T.PROPUESTA_PROGRAMA, "convenio ficticio con otra sede"),
    ]


# ---------------------------------------------------------------------------
# Inventario: tipos, rutas y prompt
# ---------------------------------------------------------------------------


def test_los_casos_inventados_cubren_los_tipos_nuevos() -> None:
    usados = {t for item in todos() for t in item.extraccion.tipos}
    assert TIPOS_POSGRADO | ASUNTOS_PROGRAMA <= usados


def test_el_prompt_explica_los_tipos_de_posgrado() -> None:
    for tipo in TIPOS_POSGRADO | ASUNTOS_PROGRAMA:
        assert f"`{tipo.value}`" in SISTEMA_EXTRACCION, tipo
    assert "«cursos»" in SISTEMA_EXTRACCION
    assert "`presenta`" in SISTEMA_EXTRACCION
    assert "`eventos`" in SISTEMA_EXTRACCION


# ---------------------------------------------------------------------------
# Acta
# ---------------------------------------------------------------------------


def test_estructura_del_acta_de_posgrado() -> None:
    texto = _acta(
        *todos(),
        numero_acta="030",
        fecha_sesion="17 de noviembre de 2026",
        hora="4:00 p. m.",
        lugar="Coordinación Programa Curricular de Matemáticas",
    )
    lineas = texto.splitlines()
    orden = [
        "COMITÉ ASESOR DE POSGRADOS DEL ÁREA CURRICULAR DE CIENCIAS EXACTAS",
        "ACTA-030",
        "MIEMBROS DEL COMITÉ ASISTENTES:",
        "ORDEN DEL DÍA:",
        "DESARROLLO:",
    ]
    posiciones = [lineas.index(x) for x in orden]
    assert posiciones == sorted(posiciones)
    assert "FECHA:\tManizales, 17 de noviembre de 2026" in lineas
    # Lo de pregrado no va en el acta de posgrado.
    for ausente in ("INVITADOS", "VARIOS", "QUÓRUM", "PREGRADO", "ASISTENTES:\n"):
        assert ausente not in texto.replace("MIEMBROS DEL COMITÉ ASISTENTES:", "")
    assert (
        "El Comité Asesor de Posgrados del Área Curricular de Ciencias Exactas, en "
        "sesión realizada el 17 de noviembre de 2026, según Acta 30 de 2026, "
        "estudió las solicitudes"
    ) in texto
    assert "Las solicitudes corresponden a los siguientes programas:" in lineas
    # Firma del director al final.
    assert lineas[-1] == "Director Área Curricular Posgrados Ciencias Exactas Naturales"


def test_un_punto_por_solicitud_agrupado_por_programa() -> None:
    datos = _datos(exencion(), cancelacion(), transito())
    # Doctorado, maestrías y especializaciones, como en las actas.
    programas = [item.caso.programa for item in ordenados(datos)]
    assert programas == ["dcm", "mcma", "esp_estadistica"]
    texto = _texto(construir_acta(datos, "2026-2S"))
    assert (
        "1) SOLICITUD DE CANCELACIÓN DE CURSOS – DOCTORADO EN CIENCIAS - "
        "MATEMÁTICAS 2026-2S"
    ) in texto
    assert "ASIGNATURAS" not in texto
    # Orden del día: un punto por solicitud, con nombre y programa.
    assert (
        "1)\tSolicitud de cancelación de cursos: Persona Ficticia Uno (Doctorado en "
        "Ciencias - Matemáticas)"
    ) in texto


def test_presentacion_y_recomendacion() -> None:
    texto = _acta(cancelacion(), reingreso())
    assert (
        "PERSONA FICTICIA UNO, identificada con DNI No. 1000000001, estudiante del "
        "Doctorado en Ciencias - Matemáticas,"
    ) in texto
    assert "Curso que solicita cancelar:" in texto
    assert "•\tAnálisis Ficticio, código 9900001, tipología L, 4 créditos." in texto
    assert (
        "Justificación emitida por el estudiante: “Solicito el trámite por un motivo "
        "ficticio.”"
    ) in texto
    assert (
        "RECOMENDACIÓN: El Comité Asesor de Posgrados del Área Curricular de Ciencias "
        "Exactas recomienda al Consejo de Facultad APROBAR la solicitud de "
        "cancelación del curso Análisis Ficticio a la estudiante Persona Ficticia Uno."
    ) in texto
    # Reingreso: exestudiante, periodo, número del portal y sentido pendiente.
    assert "exestudiante de la Maestría en Ciencias - Matemática Aplicada" in texto
    assert "solicita reingreso al programa para el periodo académico 2027-1S." in texto
    assert "La solicitud se radicó con el número XX-000-1." in texto
    assert "[APROBAR / NO APROBAR]" in texto


def test_sentido_pendiente_en_amarillo() -> None:
    doc = Document(io.BytesIO(construir_acta(_datos(reingreso()), "2026-2S")))
    [run] = [
        r for p in doc.paragraphs for r in p.runs if r.text == "[APROBAR / NO APROBAR]"
    ]
    assert run.font.highlight_color is not None


def test_permiso_con_evento_y_anexos() -> None:
    texto = _acta(permiso())
    for linea in (
        "Evento: Congreso Ficticio de Matemáticas",
        "En calidad de: ponente",
        "Fechas de participación: Del 2 al 6 de marzo de 2027",
        "Fechas de realización del evento: Del 3 al 5 de marzo de 2027",
        "Lugar: Ciudad Ficticia",
        "Para el estudio de la solicitud se adjuntó: carta de aceptación de ponencia "
        "y aval del director.",
    ):
        assert linea in texto.splitlines(), linea
    assert "identificado con DNI No. 1000000002" in texto
    # Los anexos no se repiten en el análisis.
    assert "Se anexa" not in texto


def test_tesis_jurados_y_evaluadores() -> None:
    texto = _acta(sustentacion(), calificacion_tfm(), evaluadores())
    lineas = texto.splitlines()
    for linea in (
        "Título: “Un modelo ficticio de difusión”",
        "Director(a): Profesor Ficticio A",
        "Actividad académica: Tesis de Maestría, código 9900002",
        "Fecha de sustentación: 03 de noviembre de 2026",
        "Calificación emitida: Aprobado (AP)",
        "Jurados evaluadores:",
        "•\tProfesor Ficticio B, Universidad Ficticia",
        "Fecha de entrega para evaluación: 01 de agosto de 2026",
        "Evaluador:",
        "Evaluadores puestos a consideración del Comité:",
        "•\tProfesora Ficticia F, Universidad Ficticia, f@ejemplo.org",
    ):
        assert linea in lineas, linea


def test_propuesta_y_cambio_de_titulo() -> None:
    lineas = _acta(propuesta_tfm(), cambio_titulo()).splitlines()
    for linea in (
        "Objetivo general: Objetivo general ficticio.",
        "Objetivos específicos:",
        "•\tPrimer objetivo ficticio.",
        "Título anterior: “Título ficticio anterior”",
        "Título nuevo: “Título ficticio nuevo”",
    ):
        assert linea in lineas, linea


def test_titulo_faltante_en_amarillo() -> None:
    e = sustentacion().extraccion.model_copy(update={"proyecto": None})
    doc = Document(io.BytesIO(construir_acta(_datos(_item(e)), "2026-2S")))
    marcadores = [
        r.text for p in doc.paragraphs for r in p.runs if r.font.highlight_color
    ]
    assert "[título]" in marcadores and "[director]" in marcadores


def test_transito_examen_y_norma_literal() -> None:
    texto = _acta(transito(), examen())
    assert (
        "Programa de destino: Maestría en Ciencias - Matemática Aplicada"
        in texto.splitlines()
    )
    assert "recomienda al Consejo de Facultad NO APROBAR" in texto
    # La norma del examen de calificación se transcribe literal.
    assert "Acuerdo 033 de 2008 del Consejo Superior Universitario, Artículo 17" in (
        texto
    )
    assert "“ARTÍCULO 17. Examen de calificación. Es una actividad cuyo objetivo" in (
        texto
    )


def test_desbloqueo_con_cursos_y_titulo_compuesto() -> None:
    item = desbloqueo()
    assert titulo_punto(_datos(item), item) == (
        "SOLICITUD DE REEXPEDICIÓN DE RECIBO DE MATRÍCULA, DESBLOQUEO DE LA HISTORIA "
        "ACADÉMICA Y INSCRIPCIÓN EXTEMPORÁNEA DE CURSOS – DOCTORADO EN CIENCIAS - "
        "MATEMÁTICAS"
    )
    texto = _acta(item)
    assert "Curso que solicita inscribir:" in texto
    assert "•\tSeminario Ficticio, código 9900003, grupo 1, tipología F." in texto


def test_asuntos_del_programa_sin_datos_de_estudiante() -> None:
    texto = _acta(
        asunto(T.CREACION_CURSO, "creación del curso «Curso Ficticio»"),
        asunto(T.ADMISION_NO_MASIVA, "cronograma de admisión ficticio", "dcm"),
    )
    assert (
        "El coordinador de la Maestría Ficticia presenta a consideración del Comité "
        "la solicitud de creación del curso «Curso Ficticio»."
    ) in texto
    assert "Texto de la solicitud: “Propuesta ficticia del programa.”" in texto
    assert "DNI" not in texto and "____" not in texto
    assert "ANÁLISIS" not in texto


def test_conceptos_antes_de_la_recomendacion() -> None:
    item = _item(
        exencion().extraccion,
        conceptos=[
            Concepto(
                miembro="Profesor Ficticio H",
                tratamiento="El profesor",
                texto="Concepto ficticio.",
            )
        ],
    )
    texto = _acta(item)
    assert texto.index("El profesor Profesor Ficticio H expresa:") < texto.index(
        "RECOMENDACIÓN:"
    )


def test_oficio_de_posgrado_habla_de_cursos() -> None:
    texto = _texto(construir_oficio(_datos(cancelacion()), "2026-2S"))
    assert "SOLICITUD DE CANCELACIÓN DE CURSOS" in texto
    assert "El Comité Asesor de Posgrados del Área Curricular de Ciencias Exactas" in (
        texto
    )


def test_pregrado_conserva_su_acta() -> None:
    programa = PROGRAMAS["matematicas"]
    e = extraccion_ejemplo()
    caso = Caso(
        id=1,
        chat_id=1,
        direccion="matematicas",
        programa="matematicas",
        estado=EstadoCaso.LISTO,
        sentido=Sentido.APROBAR,
        extraccion=e,
    )
    item = CasoDocumento(
        caso, e, analizar(e, programa, periodo_inicio=None, hay_imagenes=False), "x"
    )
    datos = DatosOficio(
        programa=programa, fecha=date(2026, 11, 17), casos=[item], elaboro="AB"
    )
    texto = _texto(construir_acta(datos, "2026-2S"))
    assert "3. VARIOS" in texto and "INVITADOS:" in texto
    assert "MIEMBROS DEL COMITÉ ASISTENTES:" not in texto
    assert "RECOMENDACIÓN: El Comité Asesor recomienda al Consejo de Facultad" in texto


# ---------------------------------------------------------------------------
# Reglas
# ---------------------------------------------------------------------------


def _alertas(e: ExtraccionCaso, programa: str = "mcma") -> list[str]:
    a = analizar(e, PROGRAMAS[programa], periodo_inicio=None, hay_imagenes=False)
    return [x.mensaje for x in a.alertas]


def test_asunto_del_programa_no_pide_estudiante() -> None:
    e = asunto(T.CREACION_CURSO, "creación de un curso").extraccion
    alertas = _alertas(e)
    assert not any("nombre del estudiante" in m for m in alertas)
    assert not any("documento" in m for m in alertas)
    assert not any("pantallazos" in m.lower() for m in alertas)
    sin_quien = e.model_copy(update={"presenta": None})
    assert any("quién lo presenta" in m for m in _alertas(sin_quien))


def test_sustentacion_y_evaluadores_sin_nombres_avisan() -> None:
    for item in (sustentacion(), evaluadores()):
        e = item.extraccion.model_copy(update={"jurados": []})
        assert any("No encontré" in m for m in _alertas(e))


def test_evaluadores_de_posgrado_no_siguen_el_minimo_de_jurados() -> None:
    alertas = _alertas(evaluadores().extraccion)
    assert not any("se presentan mínimo" in m for m in alertas)


def test_transito_sin_destino_avisa() -> None:
    e = transito().extraccion.model_copy(update={"programa_destino": None})
    assert any("programa de destino" in m for m in _alertas(e, "esp_estadistica"))


def test_tramite_de_posgrado_en_pregrado_avisa() -> None:
    alertas = _alertas(sustentacion().extraccion, "matematicas")
    assert any("un trámite de posgrado" in m for m in alertas)


def test_posgrado_no_suma_carga_minima() -> None:
    """El art. 10 del Acuerdo 008 de 2008 es para pregrado."""
    e = cancelacion().extraccion.model_copy(
        update={"sia": extraccion_ejemplo().sia}  # 13 créditos, 9 tras cancelar
    )
    assert T.CARGA_MINIMA not in completar_tipos(e, PROGRAMAS["dcm"]).tipos
    assert T.CARGA_MINIMA in completar_tipos(e, PROGRAMAS["matematicas"]).tipos
    assert not any("carga mínima" in m for m in _alertas(e, "dcm"))


# ---------------------------------------------------------------------------
# Extracción simulada (sin llamar al modelo)
# ---------------------------------------------------------------------------


class _Falso:
    def __init__(self, salida: ExtraccionCaso) -> None:
        self.salida = salida
        self.sistema = ""

    async def extraer(self, **kw: Any) -> Resultado:
        self.sistema = kw["sistema"]
        return Resultado(self.salida, 100, 50)


CORREO_POSGRADO = """Buenos días, Comité Asesor de Posgrados:

Solicito permiso académico para asistir al Congreso Ficticio de Matemáticas,
del 2 al 6 de marzo de 2027, en Ciudad Ficticia.

Persona Ficticia Dos
Maestría en Ciencias - Matemática Aplicada"""


@pytest.mark.parametrize(
    "tipos",
    [
        [T.PERMISO_ACADEMICO],
        [T.SUSTENTACION_TESIS],
        [T.TRANSITO_POSGRADO],
        [T.CANCELACION],
        [T.CREACION_CURSO],
    ],
)
async def test_extraccion_simulada_de_un_correo_de_posgrado(
    db: aiosqlite.Connection, tipos: list[TipoSolicitud]
) -> None:
    salida = _e(
        tipos=tipos,
        sia=DatosSIA(
            plan_codigo="9999",
            plan_nombre="MAESTRIA EN CIENCIAS - MATEMATICA APLICADA",
            resumen_creditos=extraccion_ejemplo().sia.resumen_creditos,  # type: ignore[union-attr]
        ),
        asignaturas=[
            AsignaturaSolicitada(nombre="Curso Ficticio", creditos=4, accion="cancelar")
        ],
    )
    falso = _Falso(salida)
    servicio_extraccion.set_estructurador(falso)  # type: ignore[arg-type]
    try:
        caso = Caso(
            id=1,
            chat_id=1,
            direccion=POS,
            estado=EstadoCaso.PROCESANDO,
            texto=CORREO_POSGRADO,
        )
        r = await servicio_extraccion.extraer_caso(db, caso)
    finally:
        servicio_extraccion.set_estructurador(None)
    assert r.extraccion is not None
    # El programa sale del plan; el modelo no agrega ni quita trámites y, en
    # posgrado, las reglas no suman la carga mínima de pregrado.
    assert r.programa == PROGRAMAS["mcma"]
    assert r.extraccion.tipos == tipos
    assert "`transito_posgrado`" in falso.sistema
