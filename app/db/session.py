"""Base del servicio con SQL explícito y migraciones idempotentes.

Sin DATABASE_URL, SQLite en settings.db_path (local, pruebas y el despliegue
actual). Con DATABASE_URL, Postgres en el esquema del servicio. Ver
app/core/conexion.py y docs/base-de-datos.md.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from app.core.conexion import Conexion, ConexionPostgres, abrir_sqlite, columnas
from app.core.config import settings

_ESQUEMA = (
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        telegram_id  INTEGER PRIMARY KEY,
        nombre       TEXT,
        direccion    TEXT,
        creado       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS updates_vistos (
        update_id  INTEGER PRIMARY KEY,
        visto      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS casos (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id          INTEGER NOT NULL,
        user_id          INTEGER NOT NULL,
        direccion        TEXT    NOT NULL,
        programa         TEXT,
        estado           TEXT    NOT NULL DEFAULT 'abierto',
        sentido          TEXT    NOT NULL DEFAULT 'pendiente',
        texto            TEXT    NOT NULL DEFAULT '',
        extraccion_json  TEXT,
        nota_comite      TEXT,
        error            TEXT,
        borrador_id      INTEGER,
        creado           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        actualizado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS caso_archivos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        caso_id     INTEGER NOT NULL REFERENCES casos(id),
        tipo        TEXT    NOT NULL,
        ruta        TEXT,
        nombre      TEXT,
        file_unique_id TEXT,
        creado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (caso_id, file_unique_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS estado_chat (
        chat_id          INTEGER PRIMARY KEY,
        caso_abierto_id  INTEGER,
        esperando        TEXT,
        esperando_caso   INTEGER,
        actualizado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS borradores (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        programa    TEXT NOT NULL,
        caso_ids    TEXT NOT NULL,
        docx_path   TEXT,
        pdf_path    TEXT,
        ultima_modificacion TEXT,
        creado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS uso_modelo (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        caso_id        INTEGER,
        operacion      TEXT NOT NULL,
        modelo         TEXT NOT NULL,
        input_tokens   INTEGER NOT NULL,
        output_tokens  INTEGER NOT NULL,
        creado         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conceptos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        caso_id     INTEGER NOT NULL REFERENCES casos(id),
        miembro     TEXT NOT NULL,
        tratamiento TEXT,
        texto       TEXT NOT NULL,
        creado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (caso_id, miembro)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_casos_estado ON casos(estado, programa)",
    # A quién ya salió el reporte mensual de cada mes (AAAA-MM): un área o
    # «vicedecanatura». Un re-run del cron envía solo a los que faltan.
    """
    CREATE TABLE IF NOT EXISTS reportes_mensuales (
        mes        TEXT NOT NULL,
        destino    TEXT NOT NULL,
        enviados   INTEGER NOT NULL,
        enviado    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (mes, destino)
    )
    """,
    # Actas del Consejo (Facultad, Sede o Superior) y su cruce con los casos.
    """
    CREATE TABLE IF NOT EXISTS actas_consejo (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        direccion        TEXT,
        instancia        TEXT NOT NULL,
        numero           TEXT,
        fecha            TEXT,
        archivo_nombre   TEXT,
        texto            TEXT NOT NULL,
        subido_por       TEXT NOT NULL,
        creado           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS acta_consejo_decisiones (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        acta_id               INTEGER NOT NULL REFERENCES actas_consejo(id),
        orden                 INTEGER NOT NULL,
        leida_json            TEXT NOT NULL,
        sentido               TEXT NOT NULL,
        cruce                 TEXT NOT NULL,
        motivo                TEXT,
        candidatos            TEXT NOT NULL DEFAULT '[]',
        caso_id               INTEGER,
        estado                TEXT NOT NULL DEFAULT 'pendiente',
        revisado_por          TEXT,
        revisado              TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decisiones_consejo (
        caso_id          INTEGER PRIMARY KEY REFERENCES casos(id),
        acta_id          INTEGER NOT NULL REFERENCES actas_consejo(id),
        decision_id      INTEGER NOT NULL,
        instancia        TEXT NOT NULL,
        sentido          TEXT NOT NULL,
        texto_decision   TEXT NOT NULL,
        acta_numero      TEXT,
        acta_fecha       TEXT,
        fragmento        TEXT NOT NULL,
        confirmado_por   TEXT NOT NULL,
        confirmado       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notificaciones (
        caso_id            INTEGER PRIMARY KEY REFERENCES casos(id),
        acto               TEXT NOT NULL DEFAULT 'oficio',
        numero             TEXT,
        fecha_ingreso      TEXT,
        fecha_expedicion   TEXT,
        fecha_notificacion TEXT,
        registrado_por     TEXT NOT NULL,
        actualizado        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


# Columnas agregadas después de la primera versión: (tabla, columna, tipo).
_COLUMNAS_NUEVAS = (
    ("borradores", "ultima_modificacion", "TEXT"),
    # Cuándo se registró la recomendación del comité (indicadores de tiempos).
    ("casos", "recomendado", "TIMESTAMP"),
)


async def init_db(db: Conexion) -> None:
    for sentencia in _ESQUEMA:
        await db.execute(sentencia)
    for tabla, columna, tipo in _COLUMNAS_NUEVAS:
        if columna not in await columnas(db, tabla):
            await db.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
    await db.commit()


# Con Postgres el esquema se revisa una vez por proceso, no en cada conexión.
_INICIADAS: set[tuple[str, str]] = set()


def motor() -> str:
    return "postgres" if settings.database_url else "sqlite"


async def connect() -> Conexion:
    if settings.database_url:
        clave = (settings.database_url, settings.db_schema)
        pg = await ConexionPostgres.abrir(*clave)
        if clave not in _INICIADAS:
            try:
                await init_db(pg)
            except BaseException:
                await pg.close()
                raise
            _INICIADAS.add(clave)
        return pg
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await abrir_sqlite(settings.db_path)
    await init_db(db)
    return db


def olvidar_iniciadas() -> None:
    """Para pruebas: un esquema nuevo vuelve a crear sus tablas."""
    _INICIADAS.clear()


async def get_db() -> AsyncGenerator[Conexion, None]:
    db = await connect()
    try:
        yield db
    finally:
        await db.close()
