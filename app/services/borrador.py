"""Arma y entrega los borradores por programa. Sin modelo: solo plantilla."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

from app.core.config import settings
from app.core.programas import DIRECCIONES, PROGRAMAS, Programa
from app.db import repo
from app.integrations import telegram
from app.schemas.caso import Caso
from app.services.documento import CasoDocumento, DatosOficio, construir_oficio
from app.services.extraccion import cuerpo_del_correo
from app.services.pdf import docx_a_pdf
from app.services.reglas import analizar

logger = logging.getLogger(__name__)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class Borrador:
    programa: Programa
    caso_ids: list[int]
    docx: bytes
    pdf: bytes | None
    nombre_base: str
    ruta_docx: Path
    ruta_pdf: Path | None
    ultima_modificacion: str


def _iniciales(nombre: str | None) -> str:
    partes = [p for p in (nombre or "").split() if p]
    return "".join(p[0].upper() for p in partes)[:5] or "FCEN"


def caso_documento(caso: Caso, programa: Programa) -> CasoDocumento | None:
    if caso.extraccion is None:
        return None
    analisis = analizar(
        caso.extraccion,
        programa,
        periodo_inicio=settings.periodo_inicio,
        hay_imagenes=bool(caso.imagenes),
    )
    return CasoDocumento(
        caso=caso,
        extraccion=caso.extraccion,
        analisis=analisis,
        cuerpo_correo=cuerpo_del_correo(caso.texto, caso.extraccion),
        imagenes=[Path(r) for r in caso.imagenes if Path(r).exists()],
    )


async def armar_borradores(
    db: aiosqlite.Connection,
    *,
    direccion: str,
    elaboro: str | None,
    solo_con_cambios: bool,
) -> tuple[list[Borrador], list[int]]:
    """Un borrador por programa con casos abiertos. Devuelve también los casos
    que no se pudieron ubicar en un programa."""
    ahora = datetime.now(ZoneInfo(settings.timezone))
    casos = await repo.casos_listos(db, direccion=direccion)
    por_programa: dict[str, list[Caso]] = {}
    sin_programa: list[int] = []
    for caso in casos:
        if caso.programa and caso.programa in PROGRAMAS:
            por_programa.setdefault(caso.programa, []).append(caso)
        else:
            sin_programa.append(caso.id)

    borradores: list[Borrador] = []
    for clave, lista in por_programa.items():
        programa = PROGRAMAS[clave]
        actual = await repo.firma_actual(db, direccion=direccion, programa=clave)
        if solo_con_cambios:
            previo = await repo.ultimo_borrador(db, clave)
            if (
                previo is not None
                and previo.caso_ids == actual.caso_ids
                and actual.ultima_modificacion <= previo.ultima_modificacion
            ):
                continue
        items = [i for c in lista if (i := caso_documento(c, programa)) is not None]
        if not items:
            continue
        datos = DatosOficio(
            programa=programa,
            fecha=ahora.date(),
            casos=items,
            elaboro=_iniciales(elaboro),
        )
        try:
            docx = construir_oficio(datos, settings.periodo_actual)
        except Exception:
            logger.exception("No pude armar el borrador de %s", clave)
            continue
        pdf = await docx_a_pdf(docx)
        nombre = f"Borrador_{programa.nombre.replace(' ', '_')}_{ahora:%Y-%m-%d_%H%M}"
        carpeta = settings.output_dir / ahora.strftime("%Y-%m-%d")
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_docx = carpeta / f"{nombre}.docx"
        ruta_docx.write_bytes(docx)
        ruta_pdf: Path | None = None
        if pdf:
            ruta_pdf = carpeta / f"{nombre}.pdf"
            ruta_pdf.write_bytes(pdf)
        borradores.append(
            Borrador(
                programa=programa,
                caso_ids=[i.caso.id for i in items],
                docx=docx,
                pdf=pdf,
                nombre_base=nombre,
                ruta_docx=ruta_docx,
                ruta_pdf=ruta_pdf,
                ultima_modificacion=actual.ultima_modificacion,
            )
        )
    return borradores, sin_programa


async def registrar_entrega(db: aiosqlite.Connection, borrador: Borrador) -> None:
    await repo.registrar_borrador(
        db,
        programa=borrador.programa.clave,
        caso_ids=borrador.caso_ids,
        docx_path=str(borrador.ruta_docx),
        pdf_path=str(borrador.ruta_pdf) if borrador.ruta_pdf else None,
        ultima_modificacion=borrador.ultima_modificacion,
    )


async def enviar_borradores(chat_id: int, borradores: list[Borrador]) -> None:
    for b in borradores:
        caption = (
            f"<b>{b.programa.nombre}</b> · {len(b.caso_ids)} caso(s): "
            + ", ".join(f"#{i}" for i in b.caso_ids)
        )
        await telegram.send_document(
            chat_id,
            nombre=f"{b.nombre_base}.docx",
            contenido=b.docx,
            mime=DOCX_MIME,
            caption=caption,
        )
        if b.pdf:
            await telegram.send_document(
                chat_id,
                nombre=f"{b.nombre_base}.pdf",
                contenido=b.pdf,
                mime="application/pdf",
            )


async def entrega_diaria(db: aiosqlite.Connection) -> dict[str, int]:
    """Para el cron: un borrador por programa que haya cambiado desde la última
    entrega diaria. Un envío fallido a una persona no detiene a las demás, y un
    borrador solo se da por entregado si le llegó a alguien."""
    enviados: dict[str, int] = {}
    for direccion in DIRECCIONES:
        try:
            usuarios = await repo.usuarios_de(db, direccion)
            if not usuarios:
                continue
            borradores, sin_programa = await armar_borradores(
                db,
                direccion=direccion,
                elaboro=usuarios[0].nombre,
                solo_con_cambios=True,
            )
            entregados: set[str] = set()
            for usuario in usuarios:
                try:
                    if borradores:
                        await telegram.send_message(
                            usuario.telegram_id,
                            "Borradores del día con los casos en curso:",
                        )
                        await enviar_borradores(usuario.telegram_id, borradores)
                        entregados.update(b.programa.clave for b in borradores)
                    if sin_programa:
                        await telegram.send_message(
                            usuario.telegram_id,
                            "Estos casos no entraron porque no sé de qué programa son: "
                            + ", ".join(f"#{i}" for i in sin_programa)
                            + ". Ábrelos con /caso N para asignarlos.",
                        )
                except Exception:
                    logger.exception("No pude entregar a %s", usuario.telegram_id)
            for b in borradores:
                if b.programa.clave in entregados:
                    await registrar_entrega(db, b)
            enviados[direccion] = sum(
                1 for b in borradores if b.programa.clave in entregados
            )
        except Exception:
            logger.exception("Falló la entrega diaria de %s", direccion)
            enviados[direccion] = 0
    return enviados
