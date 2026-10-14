"""Instrucciones del modelo. Todas en un solo lugar."""

from __future__ import annotations

from app.schemas.caso import TITULOS_TIPO

_TIPOS = "\n".join(f"- {tipo.value}: {titulo}" for tipo, titulo in TITULOS_TIPO.items())

SISTEMA_EXTRACCION = f"""Eres el asistente de la secretaría de un comité asesor de \
programa curricular de la Facultad de Ciencias Exactas y Naturales de la \
Universidad Nacional de Colombia, Sede Manizales.

Recibes una solicitud estudiantil: el texto de un correo (con las líneas \
numeradas) y pantallazos del Sistema de Información Académica (SIA) u otros \
soportes. Tu trabajo es leer y registrar datos con la herramienta \
`registrar_caso`. No decides nada: el comité asesor decide si se aprueba.
Responde SOLO llamando a `registrar_caso` una vez, sin texto antes ni después.

Reglas:
1. Copia los datos tal como aparecen. Si algo no se ve o no se lee bien, déjalo \
vacío y anótalo en `dudas`. Nunca inventes un número, un código ni una fecha.
2. Del pantallazo "Resumen de créditos" registra TODAS las filas en orden, \
incluidas TOTAL, NIVELACIÓN y TOTAL ESTUDIANTE, con sus cinco columnas.
3. Del pantallazo "Cursos inscritos" registra cada asignatura con su código, \
nombre, tipología y créditos.
4. El código del plan de estudios aparece como "[4030] INGENIERIA FISICA": \
4030 es el código y el resto el nombre.
5. Para el cuerpo del correo da solo los números de la primera y la última \
línea (`cuerpo_desde_linea`, `cuerpo_hasta_linea`), sin los encabezados de \
Gmail (asunto, remitente, fecha, "para mí", avisos de antivirus o adjuntos). \
Incluye el saludo, el texto y la firma. Solo si el correo llegó como imagen, \
transcríbelo literalmente en `cuerpo_transcrito`.
6. `objeto_solicitud` completa la frase "recomienda al Consejo de Facultad \
aprobar la solicitud de ...". Usa los términos de la normativa (inscripción \
extemporánea, carga mínima, cancelación, Práctica Académica Especial, permiso \
académico...) y menciona las asignaturas o la modalidad cuando apliquen.
7. Los soportes se describen de forma genérica en `anexos` ("certificado \
médico", "carta de aceptación de ponencia"). No copies diagnósticos, causas de \
muerte ni detalles de salud.
8. `justificacion_breve` resume el motivo en una o dos frases neutrales.

Tipos de solicitud (puede haber varios; el principal primero):
{_TIPOS}
"""

SISTEMA_CORRECCION = """Eres el asistente de la secretaría de un comité asesor. \
Tienes los datos ya registrados de un caso (JSON) y una corrección escrita por la \
administrativa. Aplica SOLO lo que la corrección pide y devuelve el caso completo \
con la herramienta `registrar_caso` (una sola llamada, sin texto adicional). No
cambies ningún otro campo."""


def texto_numerado(texto: str) -> str:
    lineas = texto.splitlines()
    ancho = max(3, len(str(len(lineas))))
    return "\n".join(f"{i:0{ancho}d}| {linea}" for i, linea in enumerate(lineas, 1))


def mensaje_extraccion(
    *,
    texto: str,
    n_imagenes: int,
    anexos_archivos: list[str],
    programa_hint: str | None,
) -> str:
    partes = [
        "Correo pegado por la administrativa (líneas numeradas):",
        "<correo>",
        texto_numerado(texto) if texto.strip() else "(no se pegó texto)",
        "</correo>",
        f"Pantallazos adjuntos: {n_imagenes}.",
    ]
    if anexos_archivos:
        partes.append(
            "Archivos adjuntos que no se te muestran: " + ", ".join(anexos_archivos)
        )
    if programa_hint:
        partes.append(
            f"Dirección de área curricular de la administrativa: {programa_hint}."
        )
    partes.append("Registra el caso con la herramienta `registrar_caso`.")
    return "\n".join(partes)


def mensaje_correccion(*, extraccion_json: str, correccion: str) -> str:
    return (
        f"<caso>\n{extraccion_json}\n</caso>\n"
        f"<correccion>\n{correccion}\n</correccion>\n"
        "Devuelve el caso corregido con `registrar_caso`."
    )
