"""Boletín semanal de oportunidades, por programa.

El borrador se arma con plantilla fija (sin modelo) a partir de las ofertas
aprobadas para boletín que siguen abiertas. Solo una persona lo publica con
«Aprobar y publicar». MemorIA no lo envía: se exporta en texto o HTML para
pegarlo en el correo.
"""

from __future__ import annotations

import html
import json
from datetime import date, timedelta
from typing import Any

from app.core.conexion import Conexion
from app.core.programas import PROGRAMAS
from app.servicios.oportunidades import almacen
from app.servicios.oportunidades.config import config
from app.servicios.oportunidades.modelo import NOMBRE_TIPO

TODOS = "Todos los programas"
NOMBRE_MODALIDAD = {
    "presencial": "Presencial",
    "remota": "Remota",
    "hibrida": "Híbrida",
    "sin_dato": "Modalidad sin dato",
}


class ErrorBoletin(Exception):
    pass


def semana(hoy: date) -> str:
    anio, numero, _ = hoy.isocalendar()
    return f"{anio}-S{numero:02d}"


def _abierta(oferta: dict[str, Any], hoy: date) -> bool:
    cierre = oferta["fecha_cierre"]
    if not cierre:
        return True  # una persona la verificó sin fecha y lo dejó anotado
    minimo = hoy + timedelta(days=config.dias_minimos_cierre)
    return date.fromisoformat(cierre) >= minimo


def agrupar(ofertas: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Secciones en el orden de app/core/programas.py; una oferta que aplica a
    varios programas sale en cada uno."""
    secciones: list[tuple[str, list[dict[str, Any]]]] = []
    for clave, programa in PROGRAMAS.items():
        del_programa = [o for o in ofertas if clave in o["programas"]]
        if del_programa:
            secciones.append((programa.nombre, del_programa))
    sin_programa = [o for o in ofertas if not o["programas"]]
    if sin_programa:
        secciones.append((TODOS, sin_programa))
    return secciones


def _ordenar(ofertas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(ofertas, key=lambda o: (o["fecha_cierre"] or "9999", o["titulo"]))


def _detalle(o: dict[str, Any]) -> list[str]:
    partes = [NOMBRE_TIPO.get(o["tipo"], o["tipo"]), NOMBRE_MODALIDAD[o["modalidad"]]]
    if o["lugar"]:
        partes.append(o["lugar"])
    cierre = (
        f"Cierra: {o['fecha_cierre']}" if o["fecha_cierre"] else "Cierre: ver enlace"
    )
    return [" · ".join(partes), cierre]


def texto(titulo: str, secciones: list[tuple[str, list[dict[str, Any]]]]) -> str:
    lineas = [titulo, "=" * len(titulo), ""]
    if not secciones:
        lineas.append("Esta semana no hay ofertas aprobadas.")
    for nombre, ofertas in secciones:
        lineas += [nombre, "-" * len(nombre)]
        for o in _ordenar(ofertas):
            lineas.append(f"• {o['titulo']} — {o['entidad']}")
            lineas += [f"  {d}" for d in _detalle(o)]
            if o["resumen"]:
                lineas.append(f"  {o['resumen']}")
            if o["requisitos"]:
                lineas.append(f"  Requisitos: {o['requisitos']}")
            lineas.append(f"  Más información: {o['url']}")
            lineas.append("")
    lineas.append(PIE)
    return "\n".join(lineas).strip() + "\n"


PIE = (
    "Las condiciones de cada oferta son las de la entidad que la publica: "
    "revise el enlace antes de postularse. La Facultad no intermedia en la "
    "selección."
)


def _enlace(url: str) -> str:
    seguro = url if url.startswith(("https://", "http://")) else "#"
    return html.escape(seguro, quote=True)


def a_html(titulo: str, secciones: list[tuple[str, list[dict[str, Any]]]]) -> str:
    e = html.escape
    partes = [
        '<div style="font-family:Arial,sans-serif;max-width:680px;color:#222">',
        f'<h1 style="font-size:20px">{e(titulo)}</h1>',
    ]
    if not secciones:
        partes.append("<p>Esta semana no hay ofertas aprobadas.</p>")
    for nombre, ofertas in secciones:
        partes.append(
            f'<h2 style="font-size:16px;border-bottom:1px solid #ccc">{e(nombre)}</h2>'
        )
        partes.append("<ul>")
        for o in _ordenar(ofertas):
            partes.append(
                f'<li style="margin-bottom:12px"><strong>{e(o["titulo"])}</strong>'
                f" — {e(o['entidad'])}<br>"
                + "<br>".join(e(d) for d in _detalle(o))
                + (f"<br>{e(o['resumen'])}" if o["resumen"] else "")
                + (
                    f"<br><em>Requisitos:</em> {e(o['requisitos'])}"
                    if o["requisitos"]
                    else ""
                )
                + f'<br><a href="{_enlace(o["url"])}">Más información</a></li>'
            )
        partes.append("</ul>")
    partes.append(f'<p style="font-size:12px;color:#555">{e(PIE)}</p></div>')
    return "\n".join(partes)


def _titulo(hoy: date) -> str:
    return f"Boletín de oportunidades FCEN — semana {semana(hoy)}"


async def obtener(
    db: Conexion, *, boletin_id: int | None = None, de_semana: str | None = None
) -> dict[str, Any] | None:
    if boletin_id is not None:
        cur = await db.execute(
            "SELECT * FROM opo_boletines WHERE id = ?", (boletin_id,)
        )
    else:
        cur = await db.execute(
            "SELECT * FROM opo_boletines WHERE semana = ?", (de_semana,)
        )
    f = await cur.fetchone()
    if f is None:
        return None
    datos = {k: f[k] for k in f.keys()}
    datos["oferta_ids"] = json.loads(datos["oferta_ids"])
    return datos


async def listar(db: Conexion, limite: int = 12) -> list[dict[str, Any]]:
    cur = await db.execute(
        "SELECT id, semana, estado, oferta_ids, generado, aprobado_por, aprobado"
        " FROM opo_boletines ORDER BY semana DESC LIMIT ?",
        (limite,),
    )
    filas = []
    for f in await cur.fetchall():
        datos = {k: f[k] for k in f.keys()}
        datos["ofertas"] = len(json.loads(datos.pop("oferta_ids")))
        filas.append(datos)
    return filas


async def generar(db: Conexion, hoy: date, quien: str) -> dict[str, Any]:
    """Arma (o rehace) el borrador de la semana. Uno publicado no se toca."""
    clave = semana(hoy)
    previo = await obtener(db, de_semana=clave)
    if previo is not None and previo["estado"] == "publicado":
        return {"id": previo["id"], "semana": clave, "estado": "publicado"}
    ofertas = [
        o for o in await almacen.listar(db, estado="aprobada") if _abierta(o, hoy)
    ]
    secciones = agrupar(ofertas)
    titulo = _titulo(hoy)
    ids = json.dumps(sorted(o["id"] for o in ofertas))
    cuerpo = texto(titulo, secciones)
    cuerpo_html = a_html(titulo, secciones)
    if previo is None:
        cur = await db.execute(
            "INSERT INTO opo_boletines (semana, oferta_ids, texto, html, generado_por)"
            " VALUES (?, ?, ?, ?, ?)",
            (clave, ids, cuerpo, cuerpo_html, quien),
        )
        boletin_id = int(cur.lastrowid or 0)
    else:
        boletin_id = int(previo["id"])
        await db.execute(
            "UPDATE opo_boletines SET oferta_ids = ?, texto = ?, html = ?,"
            " generado_por = ?, generado = CURRENT_TIMESTAMP WHERE id = ?",
            (ids, cuerpo, cuerpo_html, quien, boletin_id),
        )
    await db.commit()
    return {
        "id": boletin_id,
        "semana": clave,
        "estado": "borrador",
        "ofertas": len(ofertas),
    }


async def aprobar_y_publicar(
    db: Conexion, boletin_id: int, quien: str
) -> dict[str, Any]:
    """El botón humano. Marca el boletín y sus ofertas como publicados.

    No envía nada: devuelve el boletín para exportarlo y mandarlo por correo.
    Si alguna oferta cambió desde el borrador, pide rehacerlo.
    """
    hoja = await obtener(db, boletin_id=boletin_id)
    if hoja is None:
        raise LookupError(f"No existe el boletín {boletin_id}.")
    if hoja["estado"] != "borrador":
        raise ErrorBoletin("Este boletín ya se publicó.")
    if not hoja["oferta_ids"]:
        raise ErrorBoletin("El boletín no tiene ofertas.")
    for oferta_id in hoja["oferta_ids"]:
        oferta = await almacen.obtener(db, oferta_id)
        if oferta is None or oferta["estado"] != "aprobada":
            raise ErrorBoletin(
                f"La oferta #{oferta_id} cambió desde el borrador. Rehaga el borrador."
            )
    try:
        for oferta_id in hoja["oferta_ids"]:
            await almacen.publicar(db, oferta_id, boletin_id, quien)
        await db.execute(
            "UPDATE opo_boletines SET estado = 'publicado', aprobado_por = ?,"
            " aprobado = CURRENT_TIMESTAMP WHERE id = ?",
            (quien, boletin_id),
        )
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    publicado = await obtener(db, boletin_id=boletin_id)
    assert publicado is not None
    return publicado
