"""Lectura de los anexos del estudiante con el modelo.

Un anexo es lo que el estudiante manda como soporte: certificados, cartas,
constancias, soportes médicos… (tipo «anexo» en app/services/adjuntos.py).
Los pantallazos del SIA no pasan por aquí: los lee la extracción del caso.

De cada anexo el modelo saca un resumen breve (qué es, quién lo emite, de
cuándo es, qué acredita y los datos útiles para la solicitud). Nunca opina ni
recomienda. Lo que no lee queda como «[verificar en el anexo]», y las citas se
comprueban contra el texto del archivo cuando lo tiene.

- Word y PDF con texto: se extrae el texto aquí (app/services/formatos.py) y
  al modelo solo llega ese texto.
- PDF escaneado: va al modelo como documento (máximo ANEXOS_MAX_PAGINAS).
- Imagen: va reducida, como los pantallazos.

El resumen se guarda en la fila del adjunto: si se borra el anexo, su resumen
se va con él, del caso y del acta.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.core.conexion import Conexion
from app.core.config import settings
from app.db import repo
from app.integrations.claude import (
    ClaudeEstructurador,
    Imagen,
    LectorDocumentos,
    validar,
)
from app.prompts.anexos import SISTEMA_ANEXO, mensaje_anexo
from app.schemas.anexo import VERIFICAR_ANEXO, AnexoLeido, LecturaAnexo, ResumenAnexo
from app.schemas.caso import Caso
from app.services import formatos
from app.services.extraccion import preparar_imagen

logger = logging.getLogger(__name__)

HERRAMIENTA = "registrar_anexo"
OPERACION = "anexo"  # en uso_modelo
# Menos caracteres que esto en un PDF: se trata como escaneado.
_MIN_TEXTO_PDF = 40
# Lecturas simultáneas al leer varios anexos de un caso.
_SIMULTANEAS = 3
_CONTEXTO = 2000

_lector: LectorDocumentos | None = None


def get_lector() -> LectorDocumentos | None:
    global _lector
    if _lector is None and settings.anthropic_api_key:
        _lector = ClaudeEstructurador(
            settings.anthropic_api_key,
            settings.extraction_timeout_seconds,
            settings.anthropic_workspace_id,
        )
    return _lector


def set_lector(lector: LectorDocumentos | None) -> None:
    """Para pruebas."""
    global _lector
    _lector = lector


def se_lee(archivo: repo.Archivo) -> bool:
    """El adjunto es un anexo del estudiante que el modelo puede leer."""
    return archivo.tipo == "anexo" and bool(archivo.ruta)


# ---------------------------------------------------------------------------
# Qué se le envía al modelo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entrada:
    texto: str | None  # texto extraído del archivo (None: va como imagen o PDF)
    imagenes: list[Imagen]
    pdf: bytes | None
    parcial: bool


class NoSePuedeLeer(ValueError):
    """El mensaje es para la persona."""


def _recortar_pdf(datos: bytes, paginas: int) -> tuple[bytes, bool]:
    """Las primeras `paginas` del PDF. Devuelve (pdf, recortado)."""
    try:
        lector = PdfReader(io.BytesIO(datos))
        total = len(lector.pages)
        if total <= paginas:
            return datos, False
        escritor = PdfWriter()
        for pagina in lector.pages[:paginas]:
            escritor.add_page(pagina)
        salida = io.BytesIO()
        escritor.write(salida)
        return salida.getvalue(), True
    except Exception:
        # Cifrado o dañado: se envía tal cual y el modelo dice lo que lea.
        logger.warning("No pude contar las páginas del PDF", exc_info=True)
        return datos, False


async def preparar(ruta: Path) -> Entrada:
    if not ruta.exists():
        raise NoSePuedeLeer("El archivo ya no está guardado.")
    ext = ruta.suffix.lower()
    tope = settings.anexos_max_caracteres
    if ext in (".jpg", ".png", ".webp"):
        try:
            return Entrada(None, [preparar_imagen(ruta)], None, False)
        except Exception:
            raise NoSePuedeLeer("No pude abrir la imagen.") from None
    datos = ruta.read_bytes()
    if ext == ".docx":
        texto = await formatos.texto_de_archivo(datos, ".docx")
        if not texto.strip():
            raise NoSePuedeLeer("El Word no tiene texto.")
        return Entrada(texto[:tope], [], None, len(texto) > tope)
    if ext == ".pdf":
        texto = await formatos.texto_de_archivo(datos, ".pdf")
        if len(texto.strip()) >= _MIN_TEXTO_PDF:
            return Entrada(texto[:tope], [], None, len(texto) > tope)
        pdf, recortado = _recortar_pdf(datos, settings.anexos_max_paginas)
        return Entrada(None, [], pdf, recortado)
    raise NoSePuedeLeer("Ese tipo de archivo no se lee.")


# ---------------------------------------------------------------------------
# Citas
# ---------------------------------------------------------------------------


def _plano(texto: str) -> str:
    return " ".join(texto.split())


def verificar_citas(citas: list[str], texto: str | None) -> list[bool] | None:
    """Cada cita es subcadena del texto del archivo (los espacios y saltos se
    toleran: pdftotext los cambia). None si no hay texto con qué comprobar."""
    if texto is None:
        return None
    plano = _plano(texto)
    return [bool(_plano(c)) and _plano(c) in plano for c in citas]


# ---------------------------------------------------------------------------
# Leer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Consulta:
    archivo: repo.Archivo
    lectura: LecturaAnexo | None
    input_tokens: int = 0
    output_tokens: int = 0
    llamo: bool = False  # hubo llamada al modelo (para registrar el uso)
    error: str | None = None


def _contexto(caso: Caso) -> str:
    return caso.texto.strip()[:_CONTEXTO]


async def _consultar(
    lector: LectorDocumentos, caso: Caso, archivo: repo.Archivo
) -> Consulta:
    """Sin escribir en la base: se puede correr en paralelo."""
    assert archivo.ruta
    try:
        entrada = await preparar(Path(archivo.ruta))
    except NoSePuedeLeer as exc:
        return Consulta(archivo, None, error=str(exc))
    nombre = archivo.nombre or "anexo"
    resultado = await lector.leer_documento(
        sistema=SISTEMA_ANEXO,
        texto=mensaje_anexo(
            nombre=nombre,
            texto=entrada.texto,
            contexto=_contexto(caso),
            parcial=entrada.parcial,
        ),
        imagenes=entrada.imagenes,
        pdf=entrada.pdf,
        modelo_salida=ResumenAnexo,
        nombre_herramienta=HERRAMIENTA,
        modelo=settings.anexos_modelo,
        max_tokens=settings.anexos_max_tokens,
        esfuerzo=settings.anexos_esfuerzo,
    )
    resumen = validar(resultado, ResumenAnexo)
    if resumen is None:
        return Consulta(
            archivo,
            None,
            resultado.input_tokens,
            resultado.output_tokens,
            llamo=True,
            error=resultado.error or "Sin resultado.",
        )
    lectura = LecturaAnexo(
        resumen=resumen,
        citas_verificadas=verificar_citas(resumen.citas, entrada.texto),
        parcial=entrada.parcial,
        modelo=settings.anexos_modelo,
    )
    return Consulta(
        archivo, lectura, resultado.input_tokens, resultado.output_tokens, llamo=True
    )


async def _guardar(db: Conexion, caso_id: int, consulta: Consulta) -> None:
    if consulta.llamo:
        await repo.registrar_uso(
            db,
            caso_id=caso_id,
            operacion=OPERACION,
            modelo=settings.anexos_modelo,
            input_tokens=consulta.input_tokens,
            output_tokens=consulta.output_tokens,
        )
    if consulta.lectura is not None:
        # Puede haberse borrado mientras se leía: entonces no hay fila que tocar.
        await repo.set_resumen_archivo(
            db, caso_id, consulta.archivo.id, consulta.lectura.model_dump_json()
        )


async def leer(db: Conexion, caso: Caso, archivo_id: int) -> str | None:
    """Lee (o vuelve a leer) un anexo. Devuelve el error para la persona, o
    None si quedó leído. Lanza KeyError si no es un anexo del caso."""
    archivo = await repo.get_archivo_por_id(db, caso.id, archivo_id)
    if archivo is None or not se_lee(archivo):
        raise KeyError(archivo_id)
    lector = get_lector()
    if lector is None:
        return "Falta configurar ANTHROPIC_API_KEY."
    consulta = await _consultar(lector, caso, archivo)
    await _guardar(db, caso.id, consulta)
    return consulta.error


async def leer_pendientes(db: Conexion, caso: Caso) -> list[str]:
    """Lee los anexos del caso que aún no tienen resumen (cada uno se paga una
    sola vez). Devuelve los errores, con el nombre del archivo."""
    lector = get_lector()
    pendientes = [
        a
        for a in await repo.archivos_de(db, caso.id, derivados=False)
        if se_lee(a) and a.resumen is None
    ]
    if not pendientes:
        return []
    if lector is None:
        return ["Falta configurar ANTHROPIC_API_KEY para leer los anexos."]
    semaforo = asyncio.Semaphore(_SIMULTANEAS)

    async def una(a: repo.Archivo) -> Consulta:
        async with semaforo:
            try:
                return await _consultar(lector, caso, a)
            except Exception as exc:
                logger.exception("Falló la lectura del anexo %s", a.id)
                return Consulta(a, None, error=f"error inesperado ({exc})")

    consultas = await asyncio.gather(*(una(a) for a in pendientes))
    errores: list[str] = []
    for consulta in consultas:
        await _guardar(db, caso.id, consulta)
        if consulta.error:
            errores.append(f"«{consulta.archivo.nombre or 'anexo'}»: {consulta.error}")
    return errores


# ---------------------------------------------------------------------------
# Cómo se ve en la ficha y en el acta
# ---------------------------------------------------------------------------


def _limpio(valor: str | None) -> str:
    texto = " ".join((valor or "").split()).rstrip(".;, ")
    return texto or VERIFICAR_ANEXO


def frase(anexo: AnexoLeido) -> str:
    """La viñeta del análisis del caso. Ejemplo: «Se adjunta certificado médico
    de Clínica Ejemplo del 3 de septiembre de 2026 que acredita incapacidad
    entre el 1 y el 10 de septiembre de 2026.»"""
    lectura = anexo.lectura
    r = lectura.resumen
    tipo = " ".join(r.tipo_documento.split()).rstrip(".") or "documento"
    texto = (
        f"Se adjunta {tipo} de {_limpio(r.emisor)} del {_limpio(r.fecha)} "
        f"que acredita {_limpio(r.acredita)}."
    )
    datos = [_limpio(d) for d in r.datos_relevantes if d.strip()]
    if datos:
        lista = "; ".join(datos)
        texto += f" {lista[0].upper()}{lista[1:]}."
    for i, cita in enumerate(r.citas):
        cita = " ".join(cita.split()).strip('"“”«» ')
        if not cita:
            continue
        verificada = (
            lectura.citas_verificadas is not None
            and i < len(lectura.citas_verificadas)
            and lectura.citas_verificadas[i]
        )
        texto += f" Cita del anexo: “{cita}”"
        texto += "." if verificada else f" {VERIFICAR_ANEXO}."
    if not r.legible:
        texto += f" Hay partes del documento que no se leen {VERIFICAR_ANEXO}."
    if lectura.parcial:
        texto += " Solo se leyó la primera parte del archivo."
    return texto


def vinetas(caso: Caso) -> list[str]:
    """Las viñetas de los anexos leídos, para el análisis del oficio y el acta."""
    return [frase(a) for a in caso.anexos_leidos]


def describir(archivo: repo.Archivo) -> dict[str, object] | None:
    """El resumen para la ficha (None si el anexo no se ha leído)."""
    if not archivo.resumen:
        return None
    try:
        lectura = LecturaAnexo.model_validate_json(archivo.resumen)
    except ValueError:
        return None
    r = lectura.resumen
    verificadas = lectura.citas_verificadas
    return {
        "tipo_documento": r.tipo_documento,
        "fecha": r.fecha,
        "emisor": r.emisor,
        "acredita": r.acredita,
        "datos_relevantes": r.datos_relevantes,
        "citas": [
            {
                "texto": c,
                "verificada": verificadas is not None
                and i < len(verificadas)
                and verificadas[i],
            }
            for i, c in enumerate(r.citas)
        ],
        "legible": r.legible,
        "parcial": lectura.parcial,
        "frase_acta": frase(
            AnexoLeido(
                archivo_id=archivo.id,
                nombre=archivo.nombre or "anexo",
                lectura=lectura,
            )
        ),
    }
