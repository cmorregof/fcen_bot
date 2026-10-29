"""Tablas del servicio de calidad. Se crean desde este paquete, sin migraciones.

Las tablas del formato plano anterior (cal_tareas, cal_historial, cal_evidencias)
ya no se crean; si existen en una base vieja, quedan sin uso y no se borran.
"""

from __future__ import annotations

import aiosqlite

_ESQUEMA = (
    """
    CREATE TABLE IF NOT EXISTS cal_usuarios (
        telegram_id  INTEGER PRIMARY KEY,
        nombre       TEXT,
        creado       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_importaciones (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        archivo      TEXT,
        usuario_id   INTEGER,
        creadas      INTEGER NOT NULL,
        actualizadas INTEGER NOT NULL,
        sin_cambios  INTEGER NOT NULL,
        creado       TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_planes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        programa        TEXT NOT NULL,
        programa_clave  TEXT NOT NULL UNIQUE,
        datos_json      TEXT NOT NULL,
        importacion_id  INTEGER NOT NULL REFERENCES cal_importaciones(id),
        actualizado     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_acciones (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        programa_clave  TEXT NOT NULL,
        codigo          TEXT NOT NULL,
        importacion_id  INTEGER REFERENCES cal_importaciones(id),
        UNIQUE (programa_clave, codigo)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_cortes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        accion_id       INTEGER NOT NULL REFERENCES cal_acciones(id),
        clave           TEXT NOT NULL,
        rotulo          TEXT NOT NULL,
        fecha           TEXT,
        descripcion     TEXT NOT NULL,
        evidencias      TEXT NOT NULL,
        importacion_id  INTEGER NOT NULL REFERENCES cal_importaciones(id),
        UNIQUE (accion_id, clave)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_cambios (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        accion_id       INTEGER NOT NULL REFERENCES cal_acciones(id),
        importacion_id  INTEGER NOT NULL REFERENCES cal_importaciones(id),
        tipo            TEXT NOT NULL,
        cambios_json    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_soportes (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        accion_id           INTEGER NOT NULL REFERENCES cal_acciones(id),
        tipo                TEXT NOT NULL,
        valor               TEXT NOT NULL,
        referencia          TEXT,
        registrado_por      INTEGER NOT NULL,
        registrado_nombre   TEXT,
        creado              TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_estado_chat (
        chat_id     INTEGER PRIMARY KEY,
        esperando   TEXT NOT NULL,
        dato        TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cal_soportes_accion ON cal_soportes(accion_id)",
)


async def init_calidad(db: aiosqlite.Connection) -> None:
    for sentencia in _ESQUEMA:
        await db.execute(sentencia)
    await db.commit()
