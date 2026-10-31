"""Lectura y escritura de ofertas y entidades, con la traza de cada cambio.

Las transiciones de estado son las únicas que se permiten:

    encontrada → verificada → aprobada (para boletín) → publicada
    cualquiera menos publicada → descartada (con motivo)

«aprobada» y «publicada» solo las hace una persona (botón en la web).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.core.conexion import Conexion, Fila
from app.core.programas import PROGRAMAS
from app.servicios.oportunidades.texto import clave_texto, clave_url

SISTEMA = "verificador (reglas)"

_CAMPOS_JSON = ("programas", "areas", "motivos", "dudas")


class ErrorEstado(Exception):
    """La oferta no está en un estado que permita esa acción."""


def _fila(f: Fila) -> dict[str, Any]:
    datos = {k: f[k] for k in f.keys()}
    for campo in _CAMPOS_JSON:
        if campo in datos:
            datos[campo] = json.loads(datos[campo] or "[]")
    if "aliada" in datos:
        datos["aliada"] = bool(datos["aliada"])
    return datos


# ---------------------------------------------------------------------------
# Ofertas
# ---------------------------------------------------------------------------


@dataclass
class NuevaOferta:
    fuente: str
    url: str
    titulo: str
    entidad: str
    tipo: str
    programas: list[str]
    areas: list[str]
    resumen: str
    requisitos: str
    fecha_cierre: str | None
    modalidad: str
    lugar: str
    dudas: list[str]
    corrida_id: int | None = None


async def entidad_por_nombre(db: Conexion, nombre: str) -> int | None:
    cur = await db.execute(
        "SELECT id FROM opo_entidades WHERE clave = ?", (clave_texto(nombre),)
    )
    fila = await cur.fetchone()
    return int(fila[0]) if fila else None


async def existe(db: Conexion, url: str, titulo: str) -> bool:
    """¿Ya se registró esta oferta (mismo enlace y mismo título)?"""
    cur = await db.execute(
        "SELECT titulo FROM opo_ofertas WHERE url_clave = ?", (clave_url(url),)
    )
    clave = clave_texto(titulo)
    return any(clave_texto(f[0]) == clave for f in await cur.fetchall())


async def insertar(db: Conexion, o: NuevaOferta, quien: str) -> int:
    cur = await db.execute(
        "INSERT INTO opo_ofertas (fuente, url, url_clave, titulo, entidad,"
        " entidad_id, tipo, programas, areas, resumen, requisitos, fecha_cierre,"
        " modalidad, lugar, dudas, corrida_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            o.fuente,
            o.url,
            clave_url(o.url),
            o.titulo,
            o.entidad,
            await entidad_por_nombre(db, o.entidad),
            o.tipo,
            json.dumps(o.programas),
            json.dumps(o.areas, ensure_ascii=False),
            o.resumen,
            o.requisitos,
            o.fecha_cierre,
            o.modalidad,
            o.lugar,
            json.dumps(o.dudas, ensure_ascii=False),
            o.corrida_id,
        ),
    )
    oferta_id = int(cur.lastrowid or 0)
    await _historial(db, oferta_id, None, "encontrada", quien, f"fuente: {o.fuente}")
    return oferta_id


async def obtener(db: Conexion, oferta_id: int) -> dict[str, Any] | None:
    cur = await db.execute("SELECT * FROM opo_ofertas WHERE id = ?", (oferta_id,))
    fila = await cur.fetchone()
    return _fila(fila) if fila else None


async def listar(
    db: Conexion, *, estado: str | None = None, programa: str | None = None
) -> list[dict[str, Any]]:
    if estado:
        cur = await db.execute(
            "SELECT * FROM opo_ofertas WHERE estado = ? ORDER BY id DESC", (estado,)
        )
    else:
        cur = await db.execute("SELECT * FROM opo_ofertas ORDER BY id DESC")
    ofertas = [_fila(f) for f in await cur.fetchall()]
    if programa:
        ofertas = [o for o in ofertas if programa in o["programas"]]
    return ofertas


async def historial(db: Conexion, oferta_id: int) -> list[dict[str, Any]]:
    cur = await db.execute(
        "SELECT de_estado, a_estado, quien, nota, creado FROM opo_historial"
        " WHERE oferta_id = ? ORDER BY id",
        (oferta_id,),
    )
    return [_fila(f) for f in await cur.fetchall()]


async def _historial(
    db: Conexion, oferta_id: int, de: str | None, a: str, quien: str, nota: str = ""
) -> None:
    await db.execute(
        "INSERT INTO opo_historial (oferta_id, de_estado, a_estado, quien, nota)"
        " VALUES (?, ?, ?, ?, ?)",
        (oferta_id, de, a, quien, nota),
    )


async def _exigir(db: Conexion, oferta_id: int, *estados: str) -> dict[str, Any]:
    oferta = await obtener(db, oferta_id)
    if oferta is None:
        raise LookupError(f"No existe la oferta {oferta_id}.")
    if oferta["estado"] not in estados:
        raise ErrorEstado(
            f"La oferta {oferta_id} está «{oferta['estado']}»; esta acción pide "
            f"{' o '.join(estados)}."
        )
    return oferta


async def guardar_revision(
    db: Conexion, oferta_id: int, motivos: list[str], *, verificada: bool
) -> None:
    """Resultado del verificador automático (nunca aprueba)."""
    oferta = await _exigir(db, oferta_id, "encontrada")
    if verificada:
        await db.execute(
            "UPDATE opo_ofertas SET estado = 'verificada', motivos = '[]',"
            " verificado_por = ?, verificado = CURRENT_TIMESTAMP,"
            " actualizado = CURRENT_TIMESTAMP WHERE id = ?",
            (SISTEMA, oferta_id),
        )
        await _historial(db, oferta_id, oferta["estado"], "verificada", SISTEMA)
    else:
        await db.execute(
            "UPDATE opo_ofertas SET motivos = ?, actualizado = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (json.dumps(motivos, ensure_ascii=False), oferta_id),
        )


async def verificar_manual(db: Conexion, oferta_id: int, quien: str, nota: str) -> None:
    """Una persona revisa la oferta en la cola y la da por verificada."""
    oferta = await _exigir(db, oferta_id, "encontrada")
    if (oferta["motivos"] or oferta["dudas"]) and not nota.strip():
        raise ErrorEstado(
            "La oferta tiene motivos o dudas pendientes: escriba qué revisó."
        )
    await db.execute(
        "UPDATE opo_ofertas SET estado = 'verificada', verificado_por = ?,"
        " verificado = CURRENT_TIMESTAMP, actualizado = CURRENT_TIMESTAMP"
        " WHERE id = ?",
        (quien, oferta_id),
    )
    await _historial(db, oferta_id, "encontrada", "verificada", quien, nota.strip())


async def aprobar(db: Conexion, oferta_id: int, quien: str) -> None:
    """Aprobada para el boletín. Solo una persona, solo si está verificada."""
    await _exigir(db, oferta_id, "verificada")
    await db.execute(
        "UPDATE opo_ofertas SET estado = 'aprobada', aprobado_por = ?,"
        " aprobado = CURRENT_TIMESTAMP, actualizado = CURRENT_TIMESTAMP"
        " WHERE id = ?",
        (quien, oferta_id),
    )
    await _historial(db, oferta_id, "verificada", "aprobada", quien)


async def descartar(db: Conexion, oferta_id: int, quien: str, motivo: str) -> None:
    if not motivo.strip():
        raise ErrorEstado("Escriba el motivo del descarte.")
    oferta = await _exigir(db, oferta_id, "encontrada", "verificada", "aprobada")
    await db.execute(
        "UPDATE opo_ofertas SET estado = 'descartada', motivo_descarte = ?,"
        " descartado_por = ?, descartado = CURRENT_TIMESTAMP,"
        " actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (motivo.strip(), quien, oferta_id),
    )
    await _historial(
        db, oferta_id, oferta["estado"], "descartada", quien, motivo.strip()
    )


EDITABLES = (
    "titulo",
    "entidad",
    "tipo",
    "url",
    "programas",
    "requisitos",
    "resumen",
    "fecha_cierre",
    "modalidad",
    "lugar",
)


async def editar(
    db: Conexion, oferta_id: int, cambios: dict[str, Any], quien: str
) -> dict[str, Any]:
    """Corrige datos de una oferta. Vuelve a «encontrada» para revisarla otra vez."""
    oferta = await _exigir(db, oferta_id, "encontrada", "verificada", "aprobada")
    cambios = {k: v for k, v in cambios.items() if k in EDITABLES and v is not None}
    if "programas" in cambios:
        desconocidos = [p for p in cambios["programas"] if p not in PROGRAMAS]
        if desconocidos:
            raise ErrorEstado(f"Programas desconocidos: {desconocidos}")
    columnas: list[str] = []
    valores: list[Any] = []
    for campo, valor in cambios.items():
        columnas.append(f"{campo} = ?")
        valores.append(json.dumps(valor) if campo == "programas" else valor)
    if "url" in cambios:
        columnas.append("url_clave = ?")
        valores.append(clave_url(cambios["url"]))
    if "entidad" in cambios:
        columnas.append("entidad_id = ?")
        valores.append(await entidad_por_nombre(db, cambios["entidad"]))
    columnas += [
        "estado = 'encontrada'",
        "dudas = '[]'",
        "verificado_por = NULL",
        "verificado = NULL",
        "aprobado_por = NULL",
        "aprobado = NULL",
        "actualizado = CURRENT_TIMESTAMP",
    ]
    await db.execute(
        f"UPDATE opo_ofertas SET {', '.join(columnas)} WHERE id = ?",  # noqa: S608
        (*valores, oferta_id),
    )
    await _historial(
        db,
        oferta_id,
        oferta["estado"],
        "encontrada",
        quien,
        "editó: " + ", ".join(sorted(cambios)),
    )
    nueva = await obtener(db, oferta_id)
    assert nueva is not None
    return nueva


async def publicar(db: Conexion, oferta_id: int, boletin_id: int, quien: str) -> None:
    await _exigir(db, oferta_id, "aprobada")
    await db.execute(
        "UPDATE opo_ofertas SET estado = 'publicada', boletin_id = ?,"
        " publicado = CURRENT_TIMESTAMP, actualizado = CURRENT_TIMESTAMP"
        " WHERE id = ?",
        (boletin_id, oferta_id),
    )
    await _historial(
        db, oferta_id, "aprobada", "publicada", quien, f"boletín {boletin_id}"
    )


async def conteos(db: Conexion) -> dict[str, int]:
    cur = await db.execute("SELECT estado, COUNT(*) FROM opo_ofertas GROUP BY estado")
    return {str(f[0]): int(f[1]) for f in await cur.fetchall()}


# ---------------------------------------------------------------------------
# Entidades y empresas
# ---------------------------------------------------------------------------

TIPOS_ENTIDAD = ("empresa", "entidad_publica", "ong", "universidad", "otra")


async def listar_entidades(db: Conexion) -> list[dict[str, Any]]:
    cur = await db.execute(
        "SELECT e.*, (SELECT COUNT(*) FROM opo_ofertas o WHERE o.entidad_id = e.id)"
        " AS ofertas FROM opo_entidades e ORDER BY e.aliada DESC, e.nombre"
    )
    return [_fila(f) for f in await cur.fetchall()]


async def guardar_entidad(
    db: Conexion, datos: dict[str, Any], quien: str, entidad_id: int | None = None
) -> int:
    nombre = str(datos.get("nombre", "")).strip()
    if not nombre:
        raise ErrorEstado("Escriba el nombre de la entidad.")
    if datos.get("tipo", "empresa") not in TIPOS_ENTIDAD:
        raise ErrorEstado("Tipo de entidad no válido.")
    valores = (
        nombre,
        clave_texto(nombre),
        datos.get("tipo", "empresa"),
        str(datos.get("sector") or ""),
        str(datos.get("sitio_web") or ""),
        1 if datos.get("aliada") else 0,
        str(datos.get("convenio") or ""),
        str(datos.get("notas") or ""),
    )
    if entidad_id is None:
        otra = await entidad_por_nombre(db, nombre)
        if otra is not None:
            raise ErrorEstado(f"Ya existe esa entidad (#{otra}).")
        cur = await db.execute(
            "INSERT INTO opo_entidades (nombre, clave, tipo, sector, sitio_web,"
            " aliada, convenio, notas, registrado_por)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*valores, quien),
        )
        entidad_id = int(cur.lastrowid or 0)
    else:
        cur = await db.execute(
            "UPDATE opo_entidades SET nombre = ?, clave = ?, tipo = ?, sector = ?,"
            " sitio_web = ?, aliada = ?, convenio = ?, notas = ?,"
            " actualizado = CURRENT_TIMESTAMP WHERE id = ?",
            (*valores, entidad_id),
        )
        if cur.rowcount == 0:
            raise LookupError(f"No existe la entidad {entidad_id}.")
    # Las ofertas con ese nombre quedan ligadas a la entidad.
    cur = await db.execute(
        "SELECT id, entidad FROM opo_ofertas WHERE entidad_id IS NULL"
    )
    clave = clave_texto(nombre)
    for f in await cur.fetchall():
        if clave_texto(f[1]) == clave:
            await db.execute(
                "UPDATE opo_ofertas SET entidad_id = ? WHERE id = ?",
                (entidad_id, f[0]),
            )
    return entidad_id
