"""Tablas del servicio de calidad. Se crean desde este paquete, sin migraciones."""

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
    CREATE TABLE IF NOT EXISTS cal_tareas (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        programa            TEXT NOT NULL,
        programa_clave      TEXT NOT NULL,
        codigo              TEXT NOT NULL,
        tarea               TEXT NOT NULL,
        dependencia         TEXT NOT NULL,
        cargo               TEXT NOT NULL,
        fecha_limite        TEXT NOT NULL,
        evidencia_esperada  TEXT NOT NULL,
        factor_cna          TEXT NOT NULL DEFAULT '',
        eje_plan_accion     TEXT NOT NULL DEFAULT '',
        importacion_id      INTEGER REFERENCES cal_importaciones(id),
        UNIQUE (programa_clave, codigo)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_historial (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tarea_id        INTEGER NOT NULL REFERENCES cal_tareas(id),
        importacion_id  INTEGER NOT NULL REFERENCES cal_importaciones(id),
        accion          TEXT NOT NULL,
        cambios_json    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cal_evidencias (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        tarea_id            INTEGER NOT NULL REFERENCES cal_tareas(id),
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
    "CREATE INDEX IF NOT EXISTS idx_cal_evid_tarea ON cal_evidencias(tarea_id)",
)


async def init_calidad(db: aiosqlite.Connection) -> None:
    for sentencia in _ESQUEMA:
        await db.execute(sentencia)
    await db.commit()
