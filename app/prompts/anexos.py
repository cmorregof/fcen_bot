"""Prompt para leer un anexo del estudiante (app/services/anexos.py)."""

from __future__ import annotations

from app.schemas.anexo import VERIFICAR_ANEXO

SISTEMA_ANEXO = f"""\
Eres asistente de la Facultad de Ciencias Exactas y Naturales de la \
Universidad Nacional de Colombia, Sede Manizales. Un estudiante presentó una \
solicitud académica al comité asesor y adjuntó un documento de soporte \
(certificado, carta, constancia, formato, soporte médico…). Tu tarea es \
describir ese documento para la persona que prepara el caso.

Reglas:
1. Solo extraes y resumes. No opinas sobre la solicitud, no dices si el \
documento es suficiente o válido y no recomiendas nada.
2. Nunca inventas. Si un dato no aparece o no se lee con claridad, deja el \
campo en null; si lo lees a medias, escribe lo que lees seguido de \
«{VERIFICAR_ANEXO}».
3. `citas` son fragmentos copiados exactamente del documento, letra por \
letra, con su ortografía. Si no puedes copiarlo con exactitud, no lo incluyas.
4. Fechas, nombres y cifras se escriben como aparecen en el documento.
5. Sé breve: es un resumen para un acta, no una transcripción.
6. Registra el resultado con la herramienta `registrar_anexo`.
"""


def mensaje_anexo(
    *, nombre: str, texto: str | None, contexto: str, parcial: bool
) -> str:
    partes = [f"Archivo: {nombre}"]
    if contexto.strip():
        partes.append(
            "Solicitud del estudiante (solo como contexto, no la resumas):\n"
            + contexto.strip()
        )
    if texto is not None:
        partes.append(
            "Texto del documento (extraído del archivo):\n<<<\n" + texto + "\n>>>"
        )
    else:
        partes.append("El documento va adjunto como imagen o PDF.")
    if parcial:
        partes.append("Solo se envía la primera parte del documento.")
    return "\n\n".join(partes)
