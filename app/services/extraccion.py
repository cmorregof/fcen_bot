"""Del caso acumulado (texto + pantallazos) a una `ExtraccionCaso` validada."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite
from PIL import Image as PILImage

from app.core.config import settings
from app.core.programas import DIRECCIONES, Programa, identificar_programa
from app.db import repo
from app.integrations.claude import (
    ClaudeEstructurador,
    Estructurador,
    Imagen,
    validar,
)
from app.prompts.extraccion import (
    SISTEMA_CORRECCION,
    SISTEMA_EXTRACCION,
    mensaje_correccion,
    mensaje_extraccion,
)
from app.schemas.caso import Caso, ExtraccionCaso
from app.services.reglas import cita_literal, completar_tipos

logger = logging.getLogger(__name__)

HERRAMIENTA = "registrar_caso"


@dataclass(frozen=True)
class SalidaExtraccion:
    extraccion: ExtraccionCaso | None
    programa: Programa | None
    error: str | None = None


_estructurador: Estructurador | None = None


def get_estructurador() -> Estructurador | None:
    global _estructurador
    if _estructurador is None and settings.anthropic_api_key:
        _estructurador = ClaudeEstructurador(
            settings.anthropic_api_key,
            settings.extraction_timeout_seconds,
            settings.anthropic_workspace_id,
        )
    return _estructurador


def set_estructurador(estructurador: Estructurador | None) -> None:
    """Para pruebas."""
    global _estructurador
    _estructurador = estructurador


def preparar_imagen(ruta: str | Path, lado_max: int | None = None) -> Imagen:
    """Reduce y recomprime el pantallazo: menos tokens, misma legibilidad."""
    lado = lado_max or settings.max_image_side
    with PILImage.open(ruta) as original:
        im = original.convert("RGB")
    im.thumbnail((lado, lado))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return Imagen(buf.getvalue(), "image/jpeg")


def _es_encabezado_gmail(linea: str) -> bool:
    limpia = linea.strip()
    return limpia.lower() in {"para mí", "para mi"} or limpia.startswith("Para:")


def cuerpo_del_correo(texto: str, extraccion: ExtraccionCaso) -> str:
    """El cuerpo citado en el acta sale del texto pegado, no del modelo."""
    if extraccion.cuerpo_transcrito and not texto.strip():
        return extraccion.cuerpo_transcrito.strip()
    lineas = texto.splitlines()
    desde = extraccion.cuerpo_desde_linea
    hasta = extraccion.cuerpo_hasta_linea
    if desde and hasta and 1 <= desde <= hasta <= len(lineas):
        # Si el rango arrastra el encabezado de Gmail, empieza después de él.
        for i in range(hasta - 1, desde - 2, -1):
            if _es_encabezado_gmail(lineas[i]):
                desde = i + 2
                break
        if desde <= hasta:
            return "\n".join(lineas[desde - 1 : hasta]).strip()
    if extraccion.cuerpo_transcrito:
        return extraccion.cuerpo_transcrito.strip()
    return texto.strip()


def cita_del_caso(texto: str, extraccion: ExtraccionCaso) -> tuple[str, bool]:
    """Lo que va entre comillas en «justificando que “…”» y si está verificado.

    Si el modelo señaló el fragmento de la justificación, se usa tal cual y se
    comprueba que sea una subcadena exacta del texto original; si no lo es, no
    se arregla: el borrador lo resalta y la ficha lo alerta. Sin fragmento, la
    cita es el cuerpo completo, que ya sale recortado del texto pegado.
    """
    cita = (extraccion.cita_textual or "").strip()
    if cita:
        return cita, cita_literal(cita, texto, extraccion.cuerpo_transcrito)
    return cuerpo_del_correo(texto, extraccion), True


async def extraer_caso(db: aiosqlite.Connection, caso: Caso) -> SalidaExtraccion:
    estructurador = get_estructurador()
    if estructurador is None:
        return SalidaExtraccion(None, None, "Falta configurar ANTHROPIC_API_KEY.")
    imagenes: list[Imagen] = []
    for ruta in caso.imagenes:
        try:
            imagenes.append(preparar_imagen(ruta))
        except Exception as exc:
            logger.warning("No pude abrir %s: %s", ruta, exc)
    direccion = DIRECCIONES.get(caso.direccion)
    texto = mensaje_extraccion(
        texto=caso.texto,
        n_imagenes=len(imagenes),
        anexos_archivos=caso.anexos_archivos,
        programa_hint=direccion.nombre if direccion else None,
        hoy=datetime.now(ZoneInfo(settings.timezone)).date(),
    )
    resultado = await estructurador.extraer(
        sistema=SISTEMA_EXTRACCION,
        texto=texto,
        imagenes=imagenes,
        modelo_salida=ExtraccionCaso,
        nombre_herramienta=HERRAMIENTA,
        modelo=settings.extraction_model,
        max_tokens=settings.extraction_max_tokens,
    )
    await repo.registrar_uso(
        db,
        caso_id=caso.id,
        operacion="extraccion",
        modelo=settings.extraction_model,
        input_tokens=resultado.input_tokens,
        output_tokens=resultado.output_tokens,
    )
    extraccion = validar(resultado, ExtraccionCaso)
    if extraccion is None:
        return SalidaExtraccion(None, None, resultado.error or "Sin resultado.")
    extraccion = completar_tipos(extraccion)
    programa = _programa_de(extraccion, caso.direccion)
    return SalidaExtraccion(extraccion, programa)


async def corregir_caso(
    db: aiosqlite.Connection, caso: Caso, correccion: str
) -> SalidaExtraccion:
    estructurador = get_estructurador()
    if estructurador is None or caso.extraccion is None:
        return SalidaExtraccion(None, None, "No hay datos que corregir.")
    resultado = await estructurador.extraer(
        sistema=SISTEMA_CORRECCION,
        texto=mensaje_correccion(
            extraccion_json=caso.extraccion.model_dump_json(),
            correccion=correccion,
        ),
        imagenes=[],
        modelo_salida=ExtraccionCaso,
        nombre_herramienta=HERRAMIENTA,
        modelo=settings.correction_model,
        max_tokens=settings.extraction_max_tokens,
    )
    await repo.registrar_uso(
        db,
        caso_id=caso.id,
        operacion="correccion",
        modelo=settings.correction_model,
        input_tokens=resultado.input_tokens,
        output_tokens=resultado.output_tokens,
    )
    extraccion = validar(resultado, ExtraccionCaso)
    if extraccion is None:
        return SalidaExtraccion(None, None, resultado.error or "Sin resultado.")
    extraccion = completar_tipos(extraccion)
    return SalidaExtraccion(extraccion, _programa_de(extraccion, caso.direccion))


def _programa_de(extraccion: ExtraccionCaso, direccion: str) -> Programa | None:
    """Solo se acepta un programa de la dirección de quien pega el caso."""
    sia = extraccion.sia
    programa = identificar_programa(
        sia.plan_codigo if sia else None, sia.plan_nombre if sia else None
    )
    if programa and programa.direccion == direccion:
        return programa
    return None
