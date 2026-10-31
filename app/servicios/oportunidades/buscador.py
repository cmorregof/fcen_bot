"""Buscador y vigía semanal.

La vigía recorre las fuentes activas, el modelo lee cada página (buscador),
las reglas revisan lo nuevo (verificador) y se arma el borrador del boletín.
Nada se publica: el boletín espera el botón «Aprobar y publicar».
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.core.conexion import Conexion
from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.db.session import connect
from app.servicios.oportunidades import almacen, boletin, fuentes, verificador
from app.servicios.oportunidades.config import config
from app.servicios.oportunidades.db import init_oportunidades
from app.servicios.oportunidades.fuentes import Fuente
from app.servicios.oportunidades.lector import ClaudeLector, Lector, costo
from app.servicios.oportunidades.modelo import OfertaLeida
from app.servicios.oportunidades.texto import a_texto, clave_url, sin_contactos
from app.servicios.oportunidades.transporte import (
    Bloqueado,
    Cortes,
    Transporte,
    TransporteHttp,
)

logger = logging.getLogger(__name__)

QUIEN = "buscador"


class CorridaEnCurso(Exception):
    pass


def normalizar(
    leida: OfertaLeida, fuente: Fuente, url_pagina: str, enlaces: set[str]
) -> almacen.NuevaOferta:
    """Limpia lo que leyó el modelo con reglas fijas antes de guardarlo."""
    dudas = list(leida.dudas)
    url = leida.url.strip()
    claves = {clave_url(e) for e in enlaces} | {clave_url(url_pagina)}
    if not url or clave_url(url) not in claves:
        # El enlace debe salir de la página: el modelo no puede inventarlo.
        dudas.append(
            "El enlace que dio el modelo no está en la página; se usa el de la fuente."
        )
        url = url_pagina
    programas = [p for p in dict.fromkeys(leida.programas) if p in PROGRAMAS]
    if len(programas) < len(leida.programas):
        dudas.append("El modelo propuso programas que no son de la FCEN.")
    return almacen.NuevaOferta(
        fuente=fuente.clave,
        url=url,
        titulo=sin_contactos(leida.titulo.strip())[:300],
        entidad=sin_contactos(leida.entidad.strip())[:200],
        tipo=leida.tipo,
        programas=programas,
        areas=[sin_contactos(a)[:100] for a in leida.areas][:20],
        resumen=sin_contactos(leida.resumen.strip())[:1000],
        requisitos=sin_contactos(leida.requisitos.strip())[:2000],
        fecha_cierre=leida.fecha_cierre.isoformat() if leida.fecha_cierre else None,
        modalidad=leida.modalidad,
        lugar=sin_contactos(leida.lugar.strip())[:200],
        dudas=[sin_contactos(d)[:300] for d in dudas],
    )


# Una corrida 'corriendo' con más de esto se cortó con el proceso (despliegue).
HORAS_COLGADA = 2


async def _en_curso(db: Conexion) -> bool:
    limite = (datetime.now(UTC) - timedelta(hours=HORAS_COLGADA)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    await db.execute(
        "UPDATE opo_corridas SET estado = 'interrumpida',"
        " terminada = CURRENT_TIMESTAMP"
        " WHERE estado = 'corriendo' AND iniciada < ?",
        (limite,),
    )
    cur = await db.execute(
        "SELECT COUNT(*) FROM opo_corridas WHERE estado = 'corriendo'"
    )
    fila = await cur.fetchone()
    return bool(fila and int(fila[0]))


async def iniciar(db: Conexion, origen: str) -> int:
    if await _en_curso(db):
        raise CorridaEnCurso("Ya hay una vigía corriendo. Espere a que termine.")
    cur = await db.execute("INSERT INTO opo_corridas (origen) VALUES (?)", (origen,))
    await db.commit()
    return int(cur.lastrowid or 0)


async def correr(
    db: Conexion,
    corrida_id: int,
    *,
    cortes: Cortes,
    lector: Lector | None,
    hoy: date,
    lista: list[Fuente] | None = None,
) -> dict[str, Any]:
    """Una vigía completa. ``lector`` None: sin API key, no se buscan ofertas
    nuevas, pero se revisa la cola y se arma el boletín."""
    lista = fuentes.activas() if lista is None else lista
    registro: list[dict[str, Any]] = []
    ids_nuevas: list[int] = []
    encontradas = 0
    tokens_in = tokens_out = 0
    try:
        for fuente in lista:
            r: dict[str, Any] = {"clave": fuente.clave, "nombre": fuente.nombre}
            registro.append(r)
            if lector is None:
                r.update(estado="omitida", detalle="sin ANTHROPIC_API_KEY")
                continue
            if costo(tokens_in, tokens_out) >= config.tope_usd_corrida:
                r.update(estado="tope", detalle="se alcanzó el tope de gasto")
                continue
            try:
                resp = await cortes.obtener(fuente.url)
            except Bloqueado as exc:
                r.update(estado="bloqueada", detalle=str(exc))
                continue
            except (httpx.HTTPError, OSError) as exc:
                r.update(estado="error", detalle=f"no responde ({type(exc).__name__})")
                continue
            if resp.estado >= 400:
                r.update(estado="error", detalle=f"respondió {resp.estado}")
                continue
            texto, enlaces = a_texto(resp.texto, resp.url)
            lectura = await lector.leer(
                fuente=fuente, url=resp.url, texto=texto, hoy=hoy
            )
            tokens_in += lectura.input_tokens
            tokens_out += lectura.output_tokens
            if lectura.error:
                r.update(estado="error", detalle=lectura.error)
                continue
            nuevas = 0
            for leida in lectura.ofertas:
                encontradas += 1
                oferta = normalizar(leida, fuente, resp.url, enlaces)
                oferta.corrida_id = corrida_id
                if await almacen.existe(db, oferta.url, oferta.titulo):
                    continue
                ids_nuevas.append(await almacen.insertar(db, oferta, QUIEN))
                nuevas += 1
            await db.commit()
            r.update(estado="ok", ofertas=len(lectura.ofertas), nuevas=nuevas)

        verificadas = 0
        en_revision = 0
        for oferta_id in ids_nuevas:
            motivos = await verificador.revisar(db, oferta_id, hoy, cortes)
            if motivos:
                en_revision += 1
            else:
                verificadas += 1
        hoja = await boletin.generar(db, hoy, "vigía semanal")
        resultado: dict[str, Any] = {
            "corrida": corrida_id,
            "fuentes": registro,
            "encontradas": encontradas,
            "nuevas": len(ids_nuevas),
            "verificadas": verificadas,
            "en_revision": en_revision,
            "costo_usd": round(costo(tokens_in, tokens_out), 4),
            "boletin": hoja,
        }
        await db.execute(
            "UPDATE opo_corridas SET estado = 'terminada', fuentes_json = ?,"
            " encontradas = ?, nuevas = ?, verificadas = ?, en_revision = ?,"
            " input_tokens = ?, output_tokens = ?, costo_usd = ?,"
            " terminada = CURRENT_TIMESTAMP WHERE id = ?",
            (
                json.dumps(registro, ensure_ascii=False),
                encontradas,
                len(ids_nuevas),
                verificadas,
                en_revision,
                tokens_in,
                tokens_out,
                str(resultado["costo_usd"]),
                corrida_id,
            ),
        )
        await db.commit()
        return resultado
    except Exception as exc:
        logger.exception("Falló la vigía %s", corrida_id)
        await db.rollback()
        await db.execute(
            "UPDATE opo_corridas SET estado = 'fallida', error = ?, fuentes_json = ?,"
            " input_tokens = ?, output_tokens = ?, terminada = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (
                str(exc)[:500],
                json.dumps(registro, ensure_ascii=False),
                tokens_in,
                tokens_out,
                corrida_id,
            ),
        )
        await db.commit()
        raise


async def corridas(db: Conexion, limite: int = 10) -> list[dict[str, Any]]:
    cur = await db.execute(
        "SELECT * FROM opo_corridas ORDER BY id DESC LIMIT ?", (limite,)
    )
    filas = []
    for f in await cur.fetchall():
        datos = {k: f[k] for k in f.keys()}
        datos["fuentes"] = json.loads(datos.pop("fuentes_json") or "[]")
        datos["costo_usd"] = float(datos["costo_usd"] or 0)
        filas.append(datos)
    return filas


# ---------------------------------------------------------------------------
# Ejecución (cron y botón de la web). Las pruebas cambian estas dos fábricas.
# ---------------------------------------------------------------------------


def crear_transporte() -> Transporte:
    return TransporteHttp()


def crear_lector() -> Lector | None:
    return ClaudeLector() if settings.anthropic_api_key else None


async def ejecutar(corrida_id: int, hoy: date) -> dict[str, Any]:
    """Corre una vigía ya iniciada con su propia conexión."""
    db = await connect()
    transporte = crear_transporte()
    try:
        await init_oportunidades(db)
        return await correr(
            db, corrida_id, cortes=Cortes(transporte), lector=crear_lector(), hoy=hoy
        )
    finally:
        cerrar = getattr(transporte, "cerrar", None)
        if cerrar is not None:
            await cerrar()
        await db.close()
