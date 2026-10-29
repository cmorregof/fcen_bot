"""Persistencia mínima: consentimiento por chat y métricas agregadas.

Nunca se guarda texto de mensajes ni contenido de documentos: solo contadores.
"""

from __future__ import annotations

import aiosqlite

_ESQUEMA = (
    """
    CREATE TABLE IF NOT EXISTS admision_consentimiento (
        chat_id     INTEGER PRIMARY KEY,
        acepto      INTEGER NOT NULL DEFAULT 0,
        menor       INTEGER,
        acudiente   INTEGER NOT NULL DEFAULT 0,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admision_metricas (
        dia    TEXT NOT NULL,
        clave  TEXT NOT NULL,
        valor  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (dia, clave)
    )
    """,
)


async def asegurar_tablas(db: aiosqlite.Connection) -> None:
    for sentencia in _ESQUEMA:
        await db.execute(sentencia)
    await db.commit()


async def estado(db: aiosqlite.Connection, chat_id: int) -> dict[str, int | None]:
    cur = await db.execute(
        "SELECT acepto, menor, acudiente FROM admision_consentimiento"
        " WHERE chat_id = ?",
        (chat_id,),
    )
    fila = await cur.fetchone()
    if fila is None:
        return {"acepto": 0, "menor": None, "acudiente": 0}
    return {"acepto": fila[0], "menor": fila[1], "acudiente": fila[2]}


async def reiniciar(db: aiosqlite.Connection, chat_id: int) -> None:
    await db.execute(
        "INSERT INTO admision_consentimiento (chat_id) VALUES (?)"
        " ON CONFLICT(chat_id) DO UPDATE SET acepto = 0, menor = NULL,"
        " acudiente = 0, actualizado = CURRENT_TIMESTAMP",
        (chat_id,),
    )
    await db.commit()


async def fijar(db: aiosqlite.Connection, chat_id: int, campo: str, valor: int) -> None:
    if campo not in {"acepto", "menor", "acudiente"}:
        raise ValueError(campo)
    await db.execute(
        "INSERT INTO admision_consentimiento (chat_id) VALUES (?)"
        " ON CONFLICT(chat_id) DO NOTHING",
        (chat_id,),
    )
    await db.execute(
        f"UPDATE admision_consentimiento SET {campo} = ?,"
        " actualizado = CURRENT_TIMESTAMP WHERE chat_id = ?",
        (valor, chat_id),
    )
    await db.commit()


async def contar(db: aiosqlite.Connection, clave: str, n: int = 1) -> None:
    await db.execute(
        "INSERT INTO admision_metricas (dia, clave, valor)"
        " VALUES (date('now'), ?, ?)"
        " ON CONFLICT(dia, clave) DO UPDATE SET valor = valor + excluded.valor",
        (clave, n),
    )
    await db.commit()


async def totales(db: aiosqlite.Connection) -> dict[str, int]:
    cur = await db.execute(
        "SELECT clave, SUM(valor) FROM admision_metricas GROUP BY clave ORDER BY clave"
    )
    return {str(c): int(v) for c, v in await cur.fetchall()}
