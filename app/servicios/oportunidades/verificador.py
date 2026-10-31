"""Verificador: reglas deterministas sobre cada oferta encontrada.

Una oferta que pasa todas las reglas y no trae dudas del modelo queda
«verificada». Si no pasa, sigue «encontrada» en la cola de revisión con cada
motivo. El verificador nunca aprueba para el boletín: eso es de una persona.

Reglas (código: qué comprueba):

- ``campos``: tiene título, entidad y enlace.
- ``enlace_vivo``: el enlace responde (HTTP < 400), pidiendo permiso a robots.txt.
- ``dominio``: el enlace es del sitio de la fuente o de un dominio que la
  fuente declara (``dominios`` en config/oportunidades.yaml).
- ``cierre``: tiene fecha de cierre y faltan al menos
  OPORTUNIDADES_DIAS_MINIMOS_CIERRE días.
- ``programa``: aplica a uno o más programas FCEN de app/core/programas.py.
- ``duplicado``: no hay otra oferta viva con el mismo enlace, ni con la misma
  entidad y el mismo título.
- ``dudas``: el modelo no marcó dudas al leerla.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.conexion import Conexion
from app.core.programas import PROGRAMAS
from app.servicios.oportunidades import almacen, fuentes
from app.servicios.oportunidades.config import config
from app.servicios.oportunidades.texto import clave_texto
from app.servicios.oportunidades.transporte import Bloqueado, Cortes


@dataclass(frozen=True)
class Motivo:
    regla: str
    texto: str

    def __str__(self) -> str:
        return f"{self.regla}: {self.texto}"


def _fecha(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def reglas_fijas(
    oferta: dict[str, Any], hoy: date, otras: list[dict[str, Any]]
) -> list[Motivo]:
    """Las reglas que no necesitan red."""
    motivos: list[Motivo] = []
    if not (oferta["titulo"].strip() and oferta["entidad"].strip() and oferta["url"]):
        motivos.append(Motivo("campos", "faltan título, entidad o enlace"))

    fuente = fuentes.por_clave(oferta["fuente"])
    if fuente is not None:
        host = (urlsplit(oferta["url"]).hostname or "").lower()
        validos = [d.lower().removeprefix("www.") for d in fuente.dominios_validos]
        if not any(
            host.removeprefix("www.") == d or host.endswith("." + d) for d in validos
        ):
            motivos.append(
                Motivo("dominio", f"el enlace es de {host}, no de {fuente.nombre}")
            )

    cierre = _fecha(oferta["fecha_cierre"])
    minimo = hoy + timedelta(days=config.dias_minimos_cierre)
    if cierre is None:
        motivos.append(Motivo("cierre", "sin fecha de cierre"))
    elif cierre < hoy:
        motivos.append(Motivo("cierre", f"cerró el {cierre.isoformat()}"))
    elif cierre < minimo:
        motivos.append(
            Motivo("cierre", f"cierra el {cierre.isoformat()}: no alcanza al boletín")
        )

    programas = oferta["programas"]
    if not programas:
        motivos.append(Motivo("programa", "no se identificó un programa FCEN"))
    elif any(p not in PROGRAMAS for p in programas):
        motivos.append(Motivo("programa", f"programas desconocidos: {programas}"))

    titulo, entidad = clave_texto(oferta["titulo"]), clave_texto(oferta["entidad"])
    for otra in otras:
        # Solo contra las anteriores: de un par repetido, la segunda va a la cola.
        if otra["id"] >= oferta["id"] or otra["estado"] == "descartada":
            continue
        if otra["url_clave"] == oferta["url_clave"] or (
            clave_texto(otra["titulo"]) == titulo
            and clave_texto(otra["entidad"]) == entidad
        ):
            motivos.append(
                Motivo("duplicado", f"posible duplicado de la oferta #{otra['id']}")
            )
            break

    if oferta["dudas"]:
        motivos.append(Motivo("dudas", "; ".join(oferta["dudas"])))
    return motivos


async def enlace_vivo(cortes: Cortes, url: str) -> Motivo | None:
    try:
        r = await cortes.obtener(url)
    except Bloqueado as exc:
        return Motivo("enlace_vivo", f"no se pudo comprobar ({exc})")
    except (httpx.HTTPError, OSError):
        return Motivo("enlace_vivo", "el enlace no responde")
    if r.estado >= 400:
        return Motivo("enlace_vivo", f"el enlace responde {r.estado}")
    return None


async def revisar(
    db: Conexion, oferta_id: int, hoy: date, cortes: Cortes | None
) -> list[str]:
    """Aplica las reglas y guarda el resultado. Sin ``cortes`` (sin red), el
    enlace queda como motivo para que una persona lo compruebe."""
    oferta = await almacen.obtener(db, oferta_id)
    if oferta is None or oferta["estado"] != "encontrada":
        return []
    motivos = reglas_fijas(oferta, hoy, await almacen.listar(db))
    if cortes is None:
        motivos.append(Motivo("enlace_vivo", "sin comprobar (revisión sin red)"))
    else:
        vivo = await enlace_vivo(cortes, oferta["url"])
        if vivo is not None:
            motivos.append(vivo)
    textos = [str(m) for m in motivos]
    await almacen.guardar_revision(db, oferta_id, textos, verificada=not motivos)
    await db.commit()
    return textos
