"""Resumen de un anexo del estudiante (app/services/anexos.py).

El modelo solo extrae: qué documento es, quién lo emite, de cuándo es y qué
acredita. Nunca opina sobre la solicitud. Lo que no se lee con claridad queda
como «[verificar en el anexo]».
"""

from __future__ import annotations

from pydantic import BaseModel, Field

VERIFICAR_ANEXO = "[verificar en el anexo]"


class ResumenAnexo(BaseModel):
    """Lo que devuelve el modelo por cada anexo."""

    tipo_documento: str = Field(
        description="Qué documento es, en minúscula y breve: «certificado médico», "
        "«constancia laboral», «carta del director», «formato de solicitud»…"
    )
    fecha: str | None = Field(
        default=None,
        description="Fecha de expedición tal como aparece en el documento. null "
        "si no tiene fecha o no se lee.",
    )
    emisor: str | None = Field(
        default=None,
        description="Quién lo expide: la entidad, o la persona con su cargo, tal "
        "como aparece. Sin números de registro ni firmas. null si no se lee.",
    )
    acredita: str | None = Field(
        default=None,
        description="Lo que el documento hace constar, como complemento breve que "
        "siga a «que acredita…», sin repetir el nombre ni el documento del "
        "estudiante. Ejemplo: «incapacidad médica entre el 20 y el 31 de octubre "
        "de 2026». Solo lo que dice el documento. null si no se entiende.",
    )
    datos_relevantes: list[str] = Field(
        default_factory=list,
        description="Hasta 5 datos concretos del documento útiles para la "
        "solicitud: fechas, periodos, días de incapacidad, asignaturas, "
        "horarios, números de radicado. Cada uno breve. No repita lo que ya "
        "dice «acredita» ni el nombre o el documento del estudiante.",
    )
    citas: list[str] = Field(
        default_factory=list,
        description="Hasta 2 fragmentos copiados exactamente del documento, "
        "letra por letra, que sustentan lo que acredita. Sin comillas.",
    )
    legible: bool = Field(
        default=True,
        description="false si partes importantes no se pueden leer.",
    )


class LecturaAnexo(BaseModel):
    """Lo que se guarda en `caso_archivos.resumen`."""

    resumen: ResumenAnexo
    # Por cita: True si es subcadena exacta del texto del archivo. None si el
    # archivo no tenía texto (imagen o PDF escaneado) y no se puede comprobar.
    citas_verificadas: list[bool] | None = None
    # Solo se leyó una parte (archivo muy largo).
    parcial: bool = False
    modelo: str = ""


class AnexoLeido(BaseModel):
    """Un anexo del caso con su lectura, para la ficha y el acta."""

    archivo_id: int
    nombre: str
    lectura: LecturaAnexo
