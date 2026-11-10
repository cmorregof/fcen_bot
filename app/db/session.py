"""Base del servicio con SQL explícito y migraciones idempotentes.

Sin DATABASE_URL, SQLite en settings.db_path (local, pruebas y el despliegue
actual). Con DATABASE_URL, Postgres en el esquema del servicio. Ver
app/core/conexion.py y docs/base-de-datos.md.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from app.core.conexion import Conexion, ConexionPostgres, abrir_sqlite, columnas, tablas
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
    # Línea única de estados (app/services/flujo.py): una fila por transición.
    # `fecha` es cuándo ocurrió (NULL si no quedó registrada, casos anteriores);
    # `registrado`, cuándo se guardó.
    """
    CREATE TABLE IF NOT EXISTS caso_eventos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        caso_id     INTEGER NOT NULL REFERENCES casos(id),
        accion      TEXT NOT NULL,
        desde       TEXT,
        hacia       TEXT NOT NULL,
        fecha       TEXT,
        rol         TEXT NOT NULL,
        persona     TEXT,
        canal       TEXT NOT NULL,
        detalle     TEXT,
        registrado  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_caso_eventos ON caso_eventos(caso_id, id)",
    # Firma del oficio y del acta de un programa (app/services/firma.py): quién
    # firmó, cuándo, con qué radicado y datos de la sesión, y qué casos entraron.
    """
    CREATE TABLE IF NOT EXISTS firmas (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        direccion     TEXT NOT NULL,
        programa      TEXT NOT NULL,
        radicado      TEXT NOT NULL UNIQUE,
        numero_acta   TEXT NOT NULL,
        fecha_sesion  TEXT NOT NULL,
        hora          TEXT NOT NULL,
        lugar         TEXT NOT NULL,
        caso_ids      TEXT NOT NULL,
        firmante      TEXT NOT NULL,
        firmado_por   TEXT NOT NULL,
        rol           TEXT NOT NULL,
        canal         TEXT NOT NULL,
        con_imagen    INTEGER NOT NULL,
        firmado       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # Cada documento final (oficio o acta, .docx o PDF) con su SHA-256.
    """
    CREATE TABLE IF NOT EXISTS firma_archivos (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        firma_id   INTEGER NOT NULL REFERENCES firmas(id),
        documento  TEXT NOT NULL,
        formato    TEXT NOT NULL,
        ruta       TEXT NOT NULL,
        sha256     TEXT NOT NULL,
        UNIQUE (firma_id, documento, formato)
    )
    """,
    # Datos de firma que esperan la confirmación en el bot (uno por chat).
    """
    CREATE TABLE IF NOT EXISTS firmas_pendientes (
        chat_id       INTEGER PRIMARY KEY,
        programa      TEXT NOT NULL,
        radicado      TEXT NOT NULL,
        numero_acta   TEXT NOT NULL,
        fecha_sesion  TEXT NOT NULL,
        hora          TEXT NOT NULL,
        lugar         TEXT NOT NULL,
        caso_ids      TEXT NOT NULL,
        creado        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # Actas del comité de cada programa (app/services/actas_comite.py): número
    # consecutivo por programa y año, fecha de la sesión y casos. `numero` es
    # NULL solo en las históricas, anteriores al consecutivo.
    """
    CREATE TABLE IF NOT EXISTS actas_comite (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        direccion     TEXT NOT NULL,
        programa      TEXT NOT NULL,
        anio          INTEGER,
        numero        INTEGER,
        fecha_sesion  TEXT,
        estado        TEXT NOT NULL,
        firma_id      INTEGER REFERENCES firmas(id),
        cerrada_por   TEXT,
        canal         TEXT NOT NULL,
        docx_ruta     TEXT,
        docx_sha256   TEXT,
        cerrada       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_actas_comite_numero "
    "ON actas_comite(programa, anio, numero)",
    """
    CREATE TABLE IF NOT EXISTS acta_comite_casos (
        acta_id  INTEGER NOT NULL REFERENCES actas_comite(id),
        caso_id  INTEGER NOT NULL REFERENCES casos(id),
        PRIMARY KEY (acta_id, caso_id)
    )
    """,
)


# Columnas agregadas después de la primera versión: (tabla, columna, tipo).
_COLUMNAS_NUEVAS = (
    ("borradores", "ultima_modificacion", "TEXT"),
    # Cuándo se registró la recomendación del comité (indicadores de tiempos).
    ("casos", "recomendado", "TIMESTAMP"),
    # Línea única de estados (app/services/flujo.py).
    ("casos", "etapa", "TEXT"),
    ("casos", "prerrevision", "TEXT"),
)


async def init_db(db: Conexion) -> None:
    actas_nuevas = "actas_comite" not in await tablas(db)
    for sentencia in _ESQUEMA:
        await db.execute(sentencia)
    for tabla, columna, tipo in _COLUMNAS_NUEVAS:
        if columna not in await columnas(db, tabla):
            await db.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_casos_etapa ON casos(etapa)")
    # Da etapa e historia a los casos anteriores a la línea única (idempotente).
    from app.services import flujo

    await flujo.migrar(db)
    # Lleva las firmas y los casos cerrados antes del consecutivo a las actas
    # del comité (idempotente; ver app/services/actas_comite.py).
    from app.services import actas_comite

    await actas_comite.migrar(db, tabla_nueva=actas_nuevas)
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
