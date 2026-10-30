"""Decisiones del Consejo (de Facultad, de Sede o Superior) leídas de su acta.

El modelo solo copia lo que dice el acta: el texto literal de cada decisión y
los identificadores que aparezcan. El sentido (aprobó, no aprobó, aplazó) se
deduce del texto literal con una regla fija, y el cruce con los casos de
MemorIA es determinista. Nada se registra en un caso hasta que una persona lo
confirma.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Instancia(StrEnum):
    FACULTAD = "facultad"
    SEDE = "sede"
    SUPERIOR = "superior"


NOMBRE_INSTANCIA: dict[Instancia, str] = {
    Instancia.FACULTAD: "Consejo de Facultad",
    Instancia.SEDE: "Consejo de Sede",
    Instancia.SUPERIOR: "Consejo Superior Universitario",
}


class SentidoConsejo(StrEnum):
    APROBO = "aprobo"
    NO_APROBO = "no_aprobo"
    APLAZO = "aplazo"
    OTRO = "otro"


ETIQUETA_SENTIDO_CONSEJO: dict[SentidoConsejo, str] = {
    SentidoConsejo.APROBO: "Aprobó",
    SentidoConsejo.NO_APROBO: "No aprobó",
    SentidoConsejo.APLAZO: "Aplazó",
    SentidoConsejo.OTRO: "Otra decisión",
}


class Cruce(StrEnum):
    EXACTO = "exacto"  # un solo caso y todos los identificadores coinciden
    DUDOSO = "dudoso"  # va a la cola de revisión
    SIN_CASO = "sin_caso"  # ningún caso de MemorIA se le parece
    NO_VERIFICADO = "no_verificado"  # el fragmento no está literal en el acta


class EstadoDecision(StrEnum):
    PENDIENTE = "pendiente"  # espera a que una persona confirme
    APLICADA = "aplicada"
    DESCARTADA = "descartada"


# ---------------------------------------------------------------------------
# Lo que devuelve el modelo
# ---------------------------------------------------------------------------


class DecisionLeida(BaseModel):
    """Una decisión sobre un caso estudiantil, copiada del acta."""

    nombre_estudiante: str | None = Field(
        default=None, description="Nombre del estudiante tal como aparece en el acta"
    )
    documento: str | None = Field(
        default=None, description="Número de documento, solo si aparece; solo dígitos"
    )
    numero_caso: str | None = Field(
        default=None,
        description="Número de caso de MemorIA (p. ej. 'caso #12'), solo si aparece",
    )
    radicado: str | None = Field(
        default=None,
        description="Radicado del oficio o de la solicitud, tal como aparece",
    )
    programa: str | None = Field(
        default=None, description="Programa curricular, solo si aparece"
    )
    texto_decision: str = Field(
        description="Las palabras exactas con que el acta dice lo que se decidió "
        "(p. ej. 'APROBADO', 'El Consejo no aprueba', 'Se aplaza'). Copiadas "
        "carácter por carácter"
    )
    fragmento: str = Field(
        description="El párrafo o la fila completa del acta sobre este caso, "
        "copiado carácter por carácter, sin resumir ni corregir"
    )


class ActaLeida(BaseModel):
    """Salida estructurada del modelo para un acta del Consejo."""

    numero_acta: str | None = Field(
        default=None, description="Número del acta, tal como aparece"
    )
    fecha_acta: str | None = Field(
        default=None, description="Fecha de la sesión en formato AAAA-MM-DD"
    )
    instancia_texto: str | None = Field(
        default=None,
        description="Nombre del cuerpo que sesiona, tal como aparece en el "
        "encabezado (p. ej. 'Consejo de Facultad de Ciencias Exactas y Naturales')",
    )
    decisiones: list[DecisionLeida] = Field(
        default_factory=list,
        description="Todas las decisiones sobre solicitudes de estudiantes, en el "
        "orden del acta",
    )


# ---------------------------------------------------------------------------
# Lo que se guarda
# ---------------------------------------------------------------------------


class DecisionConsejo(BaseModel):
    """La decisión del Consejo registrada en un caso (una por caso)."""

    caso_id: int
    instancia: Instancia
    sentido: SentidoConsejo
    texto_decision: str
    acta_numero: str | None = None
    acta_fecha: str | None = None
    fragmento: str
    confirmado_por: str
    confirmado: str | None = None
