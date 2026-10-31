"""Tablas del servicio de oportunidades. Se crean desde este paquete.

No hay tablas de estudiantes: el servicio guarda ofertas, entidades, corridas
y boletines. Los boletines no guardan destinatarios.
"""

from __future__ import annotations

from app.core.conexion import Conexion

_ESQUEMA = (
    """
    CREATE TABLE IF NOT EXISTS opo_entidades (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre         TEXT NOT NULL,
        clave          TEXT NOT NULL UNIQUE,
        tipo           TEXT NOT NULL DEFAULT 'empresa',
        sector         TEXT NOT NULL DEFAULT '',
        sitio_web      TEXT NOT NULL DEFAULT '',
        aliada         INTEGER NOT NULL DEFAULT 0,
        convenio       TEXT NOT NULL DEFAULT '',
        notas          TEXT NOT NULL DEFAULT '',
        registrado_por TEXT NOT NULL,
        creado         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        actualizado    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opo_corridas (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        origen         TEXT NOT NULL,
        estado         TEXT NOT NULL DEFAULT 'corriendo',
        fuentes_json   TEXT NOT NULL DEFAULT '[]',
        encontradas    INTEGER NOT NULL DEFAULT 0,
        nuevas         INTEGER NOT NULL DEFAULT 0,
        verificadas    INTEGER NOT NULL DEFAULT 0,
        en_revision    INTEGER NOT NULL DEFAULT 0,
        input_tokens   INTEGER NOT NULL DEFAULT 0,
        output_tokens  INTEGER NOT NULL DEFAULT 0,
        costo_usd      TEXT NOT NULL DEFAULT '0',
        error          TEXT,
        iniciada       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        terminada      TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opo_ofertas (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        fuente           TEXT NOT NULL,
        url              TEXT NOT NULL,
        url_clave        TEXT NOT NULL,
        titulo           TEXT NOT NULL,
        entidad          TEXT NOT NULL,
        entidad_id       INTEGER REFERENCES opo_entidades(id),
        tipo             TEXT NOT NULL,
        programas        TEXT NOT NULL DEFAULT '[]',
        areas            TEXT NOT NULL DEFAULT '[]',
        resumen          TEXT NOT NULL DEFAULT '',
        requisitos       TEXT NOT NULL DEFAULT '',
        fecha_cierre     TEXT,
        modalidad        TEXT NOT NULL DEFAULT 'sin_dato',
        lugar            TEXT NOT NULL DEFAULT '',
        estado           TEXT NOT NULL DEFAULT 'encontrada',
        motivos          TEXT NOT NULL DEFAULT '[]',
        dudas            TEXT NOT NULL DEFAULT '[]',
        motivo_descarte  TEXT,
        corrida_id       INTEGER,
        verificado_por   TEXT,
        verificado       TIMESTAMP,
        aprobado_por     TEXT,
        aprobado         TIMESTAMP,
        publicado        TIMESTAMP,
        boletin_id       INTEGER,
        descartado_por   TEXT,
        descartado       TIMESTAMP,
        creado           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        actualizado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # Cada cambio de estado, con quién y por qué: la traza de la revisión humana.
    """
    CREATE TABLE IF NOT EXISTS opo_historial (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        oferta_id   INTEGER NOT NULL REFERENCES opo_ofertas(id),
        de_estado   TEXT,
        a_estado    TEXT NOT NULL,
        quien       TEXT NOT NULL,
        nota        TEXT NOT NULL DEFAULT '',
        creado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opo_boletines (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        semana         TEXT NOT NULL UNIQUE,
        estado         TEXT NOT NULL DEFAULT 'borrador',
        oferta_ids     TEXT NOT NULL DEFAULT '[]',
        texto          TEXT NOT NULL,
        html           TEXT NOT NULL,
        generado_por   TEXT NOT NULL,
        generado       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        aprobado_por   TEXT,
        aprobado       TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_opo_ofertas_estado ON opo_ofertas(estado)",
    "CREATE INDEX IF NOT EXISTS idx_opo_ofertas_url ON opo_ofertas(url_clave)",
)


async def init_oportunidades(db: Conexion) -> None:
    for sentencia in _ESQUEMA:
        await db.execute(sentencia)
    await db.commit()
