"""Capa de conexión con Postgres y migración desde SQLite.

La traducción de SQL se prueba siempre. Lo que necesita un servidor corre solo
con TEST_DATABASE_URL (en CI, el job «postgres»); sin ella se salta. Con
TEST_DATABASE_URL, además, toda la suite corre contra Postgres (conftest.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from app.core import conexion
from app.core.conexion import (
    ConexionPostgres,
    SQLNoPortable,
    marcadores,
    servidor_sin_credenciales,
    traducir,
)
from app.core.config import Settings, settings
from app.db import repo, session
from app.servicios.admision import almacen
from app.servicios.calidad.db import init_calidad
from scripts import migrar_sqlite_a_postgres as migrar
from tests.conftest import TEST_DATABASE_URL

con_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="necesita TEST_DATABASE_URL (Postgres)"
)

# --- traducción (sin servidor) ---------------------------------------------


def test_traduce_ddl_a_postgres() -> None:
    sql = traducir(
        "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " chat_id INTEGER NOT NULL, nota REAL, creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    assert "BIGSERIAL PRIMARY KEY" in sql
    assert "chat_id BIGINT NOT NULL" in sql
    assert "nota DOUBLE PRECISION" in sql
    assert "creado TEXT DEFAULT (to_char(now() AT TIME ZONE 'UTC'" in sql
    assert "AUTOINCREMENT" not in sql


def test_fechas_quedan_como_texto_utc() -> None:
    sql = traducir("UPDATE casos SET actualizado = CURRENT_TIMESTAMP WHERE id = ?")
    assert "'YYYY-MM-DD HH24:MI:SS'" in sql
    assert "'YYYY-MM-DD')" in traducir("INSERT INTO m (dia) VALUES (CURRENT_DATE)")


def test_marcadores_respetan_las_comillas() -> None:
    assert (
        marcadores("SELECT '¿?' , x FROM t WHERE a = ? AND b LIKE 'a%'")
        == "SELECT '¿?' , x FROM t WHERE a = %s AND b LIKE 'a%%'"
    )
    assert (
        marcadores("SET a = :uno, b = ':dos' WHERE c = :uno", con_nombre=True)
        == "SET a = %(uno)s, b = ':dos' WHERE c = %(uno)s"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA foreign_keys = ON",
        "SELECT name FROM sqlite_master",
        "INSERT OR IGNORE INTO t (a) VALUES (?)",
        "INSERT OR REPLACE INTO t (a) VALUES (?)",
        "SELECT strftime('%Y', creado) FROM t",
        "INSERT INTO m (dia) VALUES (date('now'))",
    ],
)
def test_sql_solo_de_sqlite_falla_claro(sql: str) -> None:
    with pytest.raises(SQLNoPortable):
        traducir(sql)


def test_servidor_sin_credenciales() -> None:
    url = "postgresql://postgres:clave@postgres.railway.internal:5432/railway"
    assert servidor_sin_credenciales(url) == "postgres.railway.internal:5432/railway"


def test_esquema_por_servicio_y_validacion(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DB_SCHEMA", "MEMORIA_PRACTICA", "DB_PATH", "DATA_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BOT_SERVICIO", "calidad")
    assert Settings().db_schema == "calidad"
    monkeypatch.setenv("MEMORIA_PRACTICA", "true")
    assert Settings().db_schema == "practica_calidad"
    monkeypatch.delenv("MEMORIA_PRACTICA")
    monkeypatch.setenv("DB_SCHEMA", "actas")
    with pytest.raises(ValueError, match="esquema de actas"):
        Settings()
    monkeypatch.setenv("DB_SCHEMA", 'calidad"; DROP')
    with pytest.raises(ValueError, match="no es un esquema válido"):
        Settings()


# --- con servidor -----------------------------------------------------------


@pytest.fixture
def esquema_extra() -> Iterator[str]:
    """Un esquema adicional, que se borra al terminar."""
    nombre = f"prueba_{uuid.uuid4().hex[:12]}"
    yield nombre
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{nombre}" CASCADE')
    conexion.olvidar_cache(TEST_DATABASE_URL, nombre)


@con_postgres
async def test_un_servicio_no_ve_las_tablas_de_otro(esquema_extra: str) -> None:
    db = await session.connect()  # esquema de la prueba (como «actas»)
    await repo.registrar_usuario(db, 7_000_000_001, "Persona Ficticia")
    await db.close()
    otro = await ConexionPostgres.abrir(TEST_DATABASE_URL, esquema_extra)
    try:
        assert await conexion.tablas(otro) == []
        with pytest.raises(psycopg.errors.UndefinedTable):
            await otro.execute("SELECT * FROM usuarios")
    finally:
        await otro.close()


@con_postgres
async def test_ids_grandes_lastrowid_y_filas_por_nombre() -> None:
    db = await session.connect()
    try:
        # Los ids de Telegram pasan de 32 bits.
        await repo.registrar_usuario(db, 7_000_000_001, "Persona Ficticia")
        usuario = await repo.get_usuario(db, 7_000_000_001)
        assert usuario is not None
        uno = await repo.crear_caso(
            db, chat_id=-1001234567890, user_id=1, direccion="fisica"
        )
        dos = await repo.crear_caso(
            db, chat_id=-1001234567890, user_id=1, direccion="fisica"
        )
        assert (uno, dos) == (1, 2)
        cur = await db.execute("SELECT id, chat_id FROM casos WHERE id = ?", (dos,))
        fila = await cur.fetchone()
        assert fila["chat_id"] == fila[1] == -1001234567890
        assert dict(fila) == {"id": 2, "chat_id": -1001234567890}
        cur = await db.execute("SELECT COALESCE(SUM(id), 0) FROM casos")
        total = (await cur.fetchone())[0]
        assert total == 3 and isinstance(total, int)
    finally:
        await db.close()


async def _sqlite_ficticia(ruta: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Una base SQLite de los tres servicios con datos ficticios."""
    with monkeypatch.context() as m:
        m.setattr(settings, "database_url", "")
        m.setattr(settings, "db_path", ruta)
        db = await session.connect()
        await init_calidad(db)
        await almacen.asegurar_tablas(db)
        await repo.registrar_usuario(db, 7_000_000_001, "Persona Ficticia")
        for _ in range(3):
            await repo.crear_caso(db, chat_id=1, user_id=1, direccion="fisica")
        await repo.registrar_uso(
            db,
            caso_id=1,
            operacion="extraccion",
            modelo="modelo",
            input_tokens=10,
            output_tokens=5,
        )
        await almacen.contar(db, "preguntas", 2)
        await db.commit()
        await db.close()


@con_postgres
async def test_migracion_copia_es_idempotente_y_verifica(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, esquema_extra: str
) -> None:
    origen = tmp_path / "origen.db"
    await _sqlite_ficticia(origen, monkeypatch)

    assert migrar.migrar(origen, TEST_DATABASE_URL, esquema_extra)
    # Dos veces: no duplica nada.
    assert migrar.migrar(origen, TEST_DATABASE_URL, esquema_extra)
    assert migrar.migrar(origen, TEST_DATABASE_URL, esquema_extra, solo_verificar=True)

    # El servicio lee lo copiado y los ids nuevos siguen después de los viejos.
    monkeypatch.setattr(settings, "db_schema", esquema_extra)
    session.olvidar_iniciadas()
    db = await session.connect()
    try:
        assert await repo.get_usuario(db, 7_000_000_001) is not None
        assert await repo.crear_caso(db, chat_id=1, user_id=1, direccion="fisica") == 4
        assert await almacen.totales(db) == {"preguntas": 2}
        await db.commit()
    finally:
        await db.close()

    # Con una fila que la SQLite no tiene, la verificación falla.
    assert not migrar.migrar(origen, TEST_DATABASE_URL, esquema_extra)
    assert not migrar.migrar(
        origen, TEST_DATABASE_URL, esquema_extra, solo_verificar=True
    )


@con_postgres
def test_migracion_exige_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRACION_DATABASE_URL", raising=False)
    assert migrar.main(["--sqlite", "x.db", "--servicio", "actas"]) == 2
