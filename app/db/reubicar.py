"""Pasa al Área Curricular de Posgrados de Ciencias Exactas (clave
`posgrados_matematicas`) lo que quedó en la del área.

Hasta noviembre de 2026 los posgrados de matemáticas colgaban del Área
Curricular de Matemáticas y Estadística, así que la administrativa de pregrado
veía los casos de posgrado. Ahora tienen su propia dirección
(app/core/programas.py). Esta migración es idempotente y usa SQL portable
(SQLite y Postgres). Un caso pasa a la nueva dirección si:

1. su programa es de la nueva dirección;
2. el plan que leyó la extracción es de un programa de la nueva dirección
   (antes «Doctorado en Ciencias - Matemáticas» se tomaba por el pregrado de
   Matemáticas, o no se reconocía);
3. lo registró una persona que hoy está en la nueva dirección (web o bot).
   Si su programa era de pregrado, queda sin programa y se elige de nuevo.

Corre al iniciar la base y cada vez que un admin guarda un usuario en
/usuarios, para que los casos se muevan apenas se cambia el área de alguien.
"""

from __future__ import annotations

import logging

from app.core.conexion import Conexion, tablas
from app.core.programas import PROGRAMAS, identificar_programa, programas_de
from app.schemas.caso import ExtraccionCaso

logger = logging.getLogger(__name__)

ORIGEN = "matematicas"
DESTINO = "posgrados_matematicas"


async def _personas_del_destino(db: Conexion, existentes: list[str]) -> set[str]:
    """Cómo aparece en caso_eventos.persona quien hoy es de la nueva dirección."""
    personas: set[str] = set()
    if "web_usuarios" in existentes:
        cur = await db.execute(
            "SELECT correo, nombre FROM web_usuarios WHERE direccion = ?", (DESTINO,)
        )
        for correo, nombre in await cur.fetchall():
            personas.update(str(x) for x in (correo, nombre) if x)
    if "usuarios" in existentes:
        cur = await db.execute(
            "SELECT telegram_id, nombre FROM usuarios WHERE direccion = ?", (DESTINO,)
        )
        for telegram_id, nombre in await cur.fetchall():
            personas.update(str(x) for x in (telegram_id, nombre) if x)
    return personas


def _programa_leido(extraccion_json: str | None) -> str | None:
    if not extraccion_json:
        return None
    try:
        sia = ExtraccionCaso.model_validate_json(extraccion_json).sia
    except ValueError:
        return None
    if sia is None:
        return None
    programa = identificar_programa(sia.plan_codigo, sia.plan_nombre)
    return programa.clave if programa else None


async def reubicar_posgrados(db: Conexion) -> int:
    """Devuelve cuántos casos cambiaron de dirección. No hace commit."""
    existentes = await tablas(db)
    if "casos" not in existentes:
        return 0
    del_destino = {p.clave for p in programas_de(DESTINO)}
    personas = await _personas_del_destino(db, existentes)

    cur = await db.execute(
        "SELECT c.id, c.programa, c.extraccion_json, e.persona FROM casos c"
        " LEFT JOIN caso_eventos e ON e.caso_id = c.id AND e.accion = 'registrar'"
        " WHERE c.direccion = ?",
        (ORIGEN,),
    )
    cambios: dict[int, str | None] = {}
    for caso_id, programa, extraccion_json, persona in await cur.fetchall():
        leido = _programa_leido(extraccion_json)
        if programa in del_destino:
            cambios[int(caso_id)] = programa
        elif leido in del_destino:
            cambios[int(caso_id)] = leido
        elif persona is not None and str(persona) in personas:
            cambios[int(caso_id)] = None

    for caso_id, programa in cambios.items():
        await db.execute(
            "UPDATE casos SET direccion = ?, programa = ? WHERE id = ?",
            (DESTINO, programa, caso_id),
        )

    if "firmas" in existentes and del_destino:
        marcas = ",".join("?" for _ in del_destino)
        await db.execute(
            f"UPDATE firmas SET direccion = ? WHERE direccion = ?"
            f" AND programa IN ({marcas})",
            (DESTINO, ORIGEN, *sorted(del_destino)),
        )
    if cambios:
        logger.info("%d casos pasaron a %s: %s", len(cambios), DESTINO, sorted(cambios))
    assert all(p is None or p in PROGRAMAS for p in cambios.values())
    return len(cambios)
