"""Tipos del revisor de soportes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from app.servicios.calidad.soportes.cliente import Respuesta


@dataclass
class Archivo:
    """Un archivo del inventario (o un archivo dentro de un zip)."""

    id: str
    ruta: str  # relativa a la carpeta del plan; dentro de zip: "x.zip!/miembro"
    nombre: str
    accion: str  # "1.3"; "" si no está en una carpeta de acción
    tipo: str  # pdf, imagen, xlsx, docx, zip, otro
    extension: str
    tamano: int
    paginas: int | None = None
    fecha: str | None = None  # fecha del metadato, si la hay
    fuente_fecha: str = ""
    dentro_de_zip: str | None = None  # id del zip que lo contiene
    miembros: list[str] = field(default_factory=list)  # solo para zip
    sha256: str = ""
    nota: str = ""
    conteos: str = ""  # xlsx: registros por periodo, contados aquí (sin nombres)


@dataclass
class Accion:
    """Una acción del plan, con lo mínimo que necesita el cruce."""

    codigo: str  # "1.3"
    aspecto: str
    objetivo: str
    descripcion: str
    indicador: str
    inicio: str
    fin: str


class DescripcionArchivo(BaseModel):
    """Lo que el modelo devuelve por cada archivo (propuesta)."""

    model_config = ConfigDict(extra="forbid")

    que_es: str = Field(
        description="Tipo de documento y contenido, en una o dos frases."
    )
    fecha_documento: str = Field(
        description="Fecha que aparece en el documento (AAAA-MM-DD, AAAA-MM o AAAA). "
        "Vacío si no aparece."
    )
    que_prueba: str = Field(
        description="Qué hecho o actividad del plan de mejoramiento podría probar."
    )
    ilegible_o_incompleto: bool = Field(
        description="Verdadero si se ve ilegible, cortado, vacío o incompleto."
    )
    observacion: str = Field(
        description="Problemas de calidad del soporte. Vacío si no hay."
    )


class Veredicto(StrEnum):
    SUFICIENTE = "evidencia suficiente"
    PARCIAL = "parcial"
    SIN_EVIDENCIA = "sin evidencia"


class CruceAccion(BaseModel):
    """Propuesta del modelo para una acción. Una persona la revisa o la ajusta."""

    model_config = ConfigDict(extra="forbid")

    veredicto: Veredicto
    justificacion: str = Field(
        description="Por qué, con citas [ID] a los soportes en el texto."
    )
    falta: str = Field(
        description="Lo que falta para probar el indicador. Vacío si nada."
    )
    avance_propuesto: int = Field(description="% de avance real propuesto, de 0 a 100.")
    citas: list[str] = Field(description="IDs de los archivos citados, p. ej. S012.")
    parrafo_cierre: str = Field(
        description="Párrafo de cierre para el informe de autoevaluación, con "
        "citas [ID] a los soportes."
    )

    @field_validator("avance_propuesto")
    @classmethod
    def _acotar(cls, valor: int) -> int:
        return max(0, min(100, valor))


class SugerenciaAccion(BaseModel):
    """Sugerencia para una acción sin evidencia. No es evidencia ni decisión."""

    model_config = ConfigDict(extra="forbid")

    accion: str = Field(description="Código de la acción, p. ej. «1.2».")
    donde_buscar: str = Field(
        description="Qué soportes de la época podrían existir y dónde buscarlos "
        "(actas, correos, afiches, sistemas de la universidad)."
    )
    accion_proximo_plan: str = Field(
        description="Si la acción de verdad no se hizo: una acción concreta y "
        "medible para el próximo plan de mejoramiento."
    )


class SugerenciasCierre(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sugerencias: list[SugerenciaAccion]


class ResumenCierre(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resumen: str = Field(
        description="Resumen general del cierre del plan para el informe de "
        "autoevaluación, con citas [ID] a los soportes."
    )


@dataclass
class Descripcion:
    """Descripción guardada de un archivo."""

    archivo_id: str
    datos: DescripcionArchivo | None
    error: str = ""
    desde_cache: bool = False


@dataclass
class EstadoCita:
    cita: str
    valida: bool
    archivo: Archivo | None
    nota: str = ""


@dataclass
class Cruce:
    accion: Accion
    propuesta: CruceAccion | None
    error: str = ""
    verificacion: list[EstadoCita] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    sugerencia: SugerenciaAccion | None = None

    @property
    def citas_validas(self) -> set[str]:
        """IDs que pasaron el verificador: lo único que cuenta como evidencia."""
        return {e.cita for e in self.verificacion if e.valida}


@dataclass
class Uso:
    """Tokens y costo acumulados por modelo."""

    por_modelo: dict[str, list[int]] = field(default_factory=dict)  # in, out, llamadas

    def sumar(self, modelo: str, entrada: int, salida: int) -> None:
        fila = self.por_modelo.setdefault(modelo, [0, 0, 0])
        fila[0] += entrada
        fila[1] += salida
        fila[2] += 1

    def registrar(self, modelo: str, resp: Respuesta) -> None:
        """Suma una respuesta del cliente; las que no llegaron a la API no cuentan."""
        if resp.llamada:
            self.sumar(resp.modelo or modelo, resp.tokens_entrada, resp.tokens_salida)

    def costo(self) -> float:
        total = 0.0
        for modelo, (ent, sal, _) in self.por_modelo.items():
            p_in, p_out = PRECIOS_USD_POR_MILLON.get(modelo, (4.0, 20.0))
            total += ent * p_in / 1e6 + sal * p_out / 1e6
        return total


# Tarifas de la API (USD por millón de tokens: entrada, salida).
PRECIOS_USD_POR_MILLON: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
