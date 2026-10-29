"""Contratos del caso estudiantil.

`ExtraccionCaso` es lo único que el modelo devuelve: datos leídos del correo y
de los pantallazos, más una frase corta que describe lo que se pide. El sentido
de la recomendación (aprobar o no aprobar) nunca sale del modelo: lo registra
la administrativa después de la sesión del comité.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class TipoSolicitud(StrEnum):
    INSCRIPCION_EXTEMPORANEA = "inscripcion_extemporanea"
    CARGA_MINIMA = "carga_minima"
    CANCELACION = "cancelacion"
    TRABAJO_GRADO = "trabajo_grado"
    DESIGNACION_JURADOS = "designacion_jurados"
    PROYECTO_TESIS = "proyecto_tesis"
    EXCEPCION_NORMA = "excepcion_norma"
    PAE = "pae"
    PERMISO_ACADEMICO = "permiso_academico"
    REINGRESO = "reingreso"
    TRASLADO = "traslado"
    DOBLE_TITULACION = "doble_titulacion"
    MOVILIDAD = "movilidad"
    REEXPEDICION_RECIBO = "reexpedicion_recibo"
    CANCELACION_PERIODO = "cancelacion_periodo"
    RESERVA_CUPO = "reserva_cupo"
    HOMOLOGACION = "homologacion"
    OTRO = "otro"


TITULOS_TIPO: dict[TipoSolicitud, str] = {
    TipoSolicitud.INSCRIPCION_EXTEMPORANEA: "inscripción extemporánea de asignaturas",
    TipoSolicitud.CARGA_MINIMA: "carga mínima",
    TipoSolicitud.CANCELACION: "cancelación de asignaturas",
    TipoSolicitud.TRABAJO_GRADO: "inscripción de trabajo de grado",
    TipoSolicitud.DESIGNACION_JURADOS: "designación de jurados de trabajo de grado",
    TipoSolicitud.PROYECTO_TESIS: "inscripción de proyecto de tesis o trabajo final de maestría",
    TipoSolicitud.EXCEPCION_NORMA: "excepción a la norma",
    TipoSolicitud.PAE: "práctica académica especial (PAE)",
    TipoSolicitud.PERMISO_ACADEMICO: "permiso académico",
    TipoSolicitud.REINGRESO: "reingreso",
    TipoSolicitud.TRASLADO: "traslado",
    TipoSolicitud.DOBLE_TITULACION: "doble titulación",
    TipoSolicitud.MOVILIDAD: "movilidad",
    TipoSolicitud.REEXPEDICION_RECIBO: "reexpedición de recibo de matrícula",
    TipoSolicitud.CANCELACION_PERIODO: "cancelación del periodo académico",
    TipoSolicitud.RESERVA_CUPO: "reserva de cupo adicional",
    TipoSolicitud.HOMOLOGACION: "homologación, convalidación o equivalencia de asignaturas",
    TipoSolicitud.OTRO: "otras solicitudes",
}


class FilaCreditos(BaseModel):
    """Una fila de la tabla 'Resumen de créditos' del SIA, tal como aparece."""

    tipologia: str
    exigidos: int | None = None
    aprobados: int | None = None
    pendientes: int | None = None
    inscritos: int | None = None
    cursados: int | None = None


class CursoInscrito(BaseModel):
    codigo: str
    nombre: str
    tipologia: str | None = None
    creditos: int | None = None


class DatosSIA(BaseModel):
    """Lo que se lee de los pantallazos de la historia académica."""

    plan_codigo: str | None = Field(
        default=None,
        description="Código del plan, p. ej. 4030 en '[4030] INGENIERIA FISICA'",
    )
    plan_nombre: str | None = None
    periodo: str | None = Field(
        default=None, description="Periodo visto, p. ej. 2026-2S"
    )
    convocatoria: str | None = Field(
        default=None,
        description="Periodo de admisión del estudiante (p. ej. 2024-1S), solo si "
        "aparece en un pantallazo",
    )
    papa: float | None = Field(default=None, description="P.A.P.A. acumulado")
    promedio_academico: float | None = None
    porcentaje_avance: float | None = Field(
        default=None, description="Porcentaje de avance, como número (56.5 para 56,5 %)"
    )
    cursos_inscritos: list[CursoInscrito] = Field(default_factory=list)
    resumen_creditos: list[FilaCreditos] = Field(
        default_factory=list,
        description="Todas las filas de 'Resumen de créditos', incluidas TOTAL, "
        "NIVELACIÓN y TOTAL ESTUDIANTE, en el orden en que aparecen",
    )
    creditos_disponibles: int | None = None
    creditos_cancelados: int | None = None


class AsignaturaSolicitada(BaseModel):
    codigo: str | None = None
    nombre: str
    grupo: str | None = Field(
        default=None,
        description="Grupo de la asignatura, tal como aparece en el SIA o la solicitud",
    )
    tipologia: str | None = Field(
        default=None,
        description="Tipología de la asignatura (p. ej. DISCIPLINAR OBLIGATORIA, "
        "FUND. OPTATIVA, LIBRE ELECCIÓN), como aparece en el SIA",
    )
    creditos: int | None = None
    accion: Literal["inscribir", "cancelar", "apertura"] = "inscribir"


class AsignaturaCuadro(BaseModel):
    """Un lado de una fila del cuadro comparativo, tal como lo escribe el estudiante."""

    codigo: str | None = None
    nombre: str | None = None
    tipologia: str | None = None
    creditos: int | None = None
    nota: str | None = Field(
        default=None, description="Nota tal como aparece (p. ej. '4.2', 'AP')"
    )


class FilaCuadro(BaseModel):
    origen: AsignaturaCuadro = Field(description="Asignatura ya cursada")
    destino: AsignaturaCuadro = Field(
        description="Asignatura que se reconoce en el plan de destino"
    )


class CuadroEquivalencias(BaseModel):
    """Cuadro comparativo de asignaturas (formato de homologación, convalidación
    o equivalencia; también el que acompaña un traslado o una doble titulación)."""

    figura: Literal["equivalencia", "homologacion", "convalidacion"] = Field(
        default="equivalencia",
        description="equivalencia: entre planes de la UNAL; homologacion: desde otra "
        "institución; convalidacion: la que marque el formato como tal",
    )
    origen: str | None = Field(
        default=None,
        description="Programa o universidad donde se cursaron, como aparece",
    )
    destino: str | None = Field(
        default=None, description="Programa donde se reconocen, como aparece"
    )
    filas: list[FilaCuadro] = Field(default_factory=list)


class Jurado(BaseModel):
    """Un jurado de Trabajo de Grado, copiado tal como aparece en la solicitud."""

    nombre: str
    vinculacion: str | None = Field(
        default=None,
        description="Vinculación o institución, solo si aparece (p. ej. 'Profesor "
        "asociado, Departamento de Física y Química' o 'Universidad de Caldas')",
    )
    correo: str | None = Field(default=None, description="Solo si aparece")


class ProyectoTesis(BaseModel):
    """Proyecto de tesis o trabajo final de posgrado, tal como aparece."""

    titulo: str | None = None
    director: str | None = Field(
        default=None, description="Director(a), como aparece (con su vinculación)"
    )
    codirector: str | None = None
    linea: str | None = Field(
        default=None, description="Línea o grupo de investigación, solo si aparece"
    )


class ExtraccionCaso(BaseModel):
    """Salida estructurada del modelo para un caso."""

    nombre_estudiante: str | None = Field(
        default=None, description="Nombre completo tal como lo escribe el estudiante"
    )
    documento: str | None = Field(
        default=None, description="Número de documento, solo dígitos"
    )
    tratamiento: Literal["El estudiante", "La estudiante"] = Field(
        default="El estudiante",
        description="Según cómo se presenta la persona en la solicitud",
    )
    correo_estudiante: str | None = None
    fecha_solicitud: str | None = Field(
        default=None, description="Fecha del correo en formato AAAA-MM-DD"
    )
    tipos: list[TipoSolicitud] = Field(
        default_factory=list,
        description="Todos los trámites que pide, el principal primero",
    )
    objeto_solicitud: str = Field(
        default="",
        description="Qué pide, como complemento de 'recomienda aprobar la solicitud "
        "de ...'. Ej.: 'inscripción extemporánea de la asignatura Trabajo de Grado "
        "en la modalidad de asignaturas de posgrado'",
    )
    modalidad_trabajo_grado: str | None = Field(
        default=None,
        description="Solo si pide Trabajo de Grado: trabajo investigativo, práctica de "
        "extensión o asignaturas de posgrado, como lo dice el estudiante",
    )
    asignaturas: list[AsignaturaSolicitada] = Field(default_factory=list)
    jurados: list[Jurado] = Field(
        default_factory=list,
        description="Jurados de Trabajo de Grado que trae la solicitud, en el orden "
        "en que aparecen. No se inventan ni se completan",
    )
    proyecto: ProyectoTesis | None = Field(
        default=None,
        description="Solo si pide inscribir un proyecto de tesis o trabajo final "
        "de posgrado",
    )
    equivalencias: list[CuadroEquivalencias] = Field(
        default_factory=list,
        description="Cuadros comparativos de asignaturas cursadas y reconocidas, "
        "uno por cada cuadro que traiga la solicitud",
    )
    cuerpo_desde_linea: int | None = Field(
        default=None,
        description="Primera línea (numerada) del cuerpo del correo, sin encabezados "
        "de Gmail (remitente, fecha, 'para mí')",
    )
    cuerpo_hasta_linea: int | None = Field(
        default=None,
        description="Última línea del cuerpo del correo, incluida la firma",
    )
    cuerpo_transcrito: str | None = Field(
        default=None,
        description="Solo si el correo llegó como imagen y no como texto: el cuerpo "
        "transcrito literalmente",
    )
    cita_textual: str | None = Field(
        default=None,
        description="Fragmento del cuerpo (o de la justificación del formato) donde "
        "el estudiante expone su motivo, copiado carácter por carácter, sin los "
        "números de línea. Va entre comillas en el oficio",
    )
    justificacion_breve: str = Field(
        default="", description="Una o dos frases neutrales con el motivo que expone"
    )
    anexos: list[str] = Field(
        default_factory=list,
        description="Soportes que menciona o adjunta, descritos de forma genérica "
        "(p. ej. 'carta de aceptación de ponencia', 'certificado médico')",
    )
    sia: DatosSIA | None = None
    dudas: list[str] = Field(
        default_factory=list,
        description="Datos que no se pudieron leer o que son ambiguos",
    )


class Sentido(StrEnum):
    PENDIENTE = "pendiente"
    APROBAR = "aprobar"
    NO_APROBAR = "no_aprobar"


class EstadoCaso(StrEnum):
    ABIERTO = "abierto"
    PROCESANDO = "procesando"
    LISTO = "listo"
    ERROR = "error"
    DESCARTADO = "descartado"
    # El comité ya sesionó sobre el caso; sale del borrador en curso.
    CERRADO = "cerrado"


class Alerta(BaseModel):
    nivel: Literal["error", "aviso", "info"]
    mensaje: str


class Concepto(BaseModel):
    """Concepto de un integrante del comité. Va al acta, nunca al oficio.

    El texto se guarda tal como lo envió el profesor: no se resume ni se
    corrige.
    """

    miembro: str
    tratamiento: str | None = None  # «El profesor», «La profesora» o None
    texto: str


class Caso(BaseModel):
    id: int
    chat_id: int
    direccion: str
    programa: str | None = None
    estado: EstadoCaso
    sentido: Sentido = Sentido.PENDIENTE
    texto: str = ""
    imagenes: list[str] = Field(default_factory=list)
    anexos_archivos: list[str] = Field(default_factory=list)
    extraccion: ExtraccionCaso | None = None
    nota_comite: str | None = None
    conceptos: list[Concepto] = Field(default_factory=list)
    creado: str | None = None
