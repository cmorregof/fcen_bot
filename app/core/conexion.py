"""Conexión a la base: SQLite (aiosqlite) o Postgres (psycopg), con una interfaz.

El código del bot escribe SQL en el dialecto común de SQLite y Postgres y usa
la interfaz de aiosqlite: ``execute`` → cursor con ``fetchone``, ``fetchall``,
``rowcount`` y ``lastrowid``; ``commit``, ``rollback`` y ``close``.

Con Postgres, :class:`ConexionPostgres` ofrece esa misma interfaz y traduce lo
poco que cambia entre los dos motores:

- marcadores ``?`` → ``%s``;
- en ``CREATE TABLE``: ``INTEGER PRIMARY KEY AUTOINCREMENT`` → ``BIGSERIAL``,
  ``INTEGER`` → ``BIGINT`` (los ids de Telegram no caben en 32 bits) y
  ``TIMESTAMP`` → ``TEXT``;
- ``CURRENT_TIMESTAMP`` y ``CURRENT_DATE`` → texto UTC con el mismo formato que
  guarda SQLite (``AAAA-MM-DD HH:MM:SS``), porque el código lee y compara las
  fechas como texto;
- ``lastrowid``: a un ``INSERT`` en una tabla con ``id`` serial se le agrega
  ``RETURNING id``.

Cada servicio usa su propio esquema de Postgres (``search_path``); nunca lee el
de otro. Lo que es propio de SQLite y no tiene traducción (``PRAGMA``,
``sqlite_master``, ``INSERT OR …``) falla con un error claro.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

import aiosqlite

# ---------------------------------------------------------------------------
# Interfaz común (la cumplen aiosqlite y ConexionPostgres)
# ---------------------------------------------------------------------------


class Cursor(Protocol):
    @property
    def rowcount(self) -> int: ...

    @property
    def lastrowid(self) -> int | None: ...

    async def fetchone(self) -> Any: ...

    async def fetchall(self) -> Iterable[Any]: ...


class Conexion(Protocol):
    def execute(
        self, sql: str, parameters: Iterable[Any] | None = None
    ) -> Awaitable[Cursor]: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...


# Una fila: se lee por posición o por nombre de columna, como sqlite3.Row.
Fila = Any


def es_postgres(db: Conexion) -> bool:
    return isinstance(db, ConexionPostgres)


# ---------------------------------------------------------------------------
# Utilidades que dependen del motor
# ---------------------------------------------------------------------------


async def tablas(db: Conexion) -> list[str]:
    """Tablas de la base (o del esquema) del servicio, sin las internas."""
    if es_postgres(db):
        cur = await db.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            " ORDER BY table_name"
        )
    else:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    return [str(f[0]) for f in await cur.fetchall()]


async def columnas(db: Conexion, tabla: str) -> list[str]:
    if es_postgres(db):
        cur = await db.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = ?"
            " ORDER BY ordinal_position",
            (tabla,),
        )
        return [str(f[0]) for f in await cur.fetchall()]
    cur = await db.execute(f'PRAGMA table_info("{tabla}")')
    return [str(f[1]) for f in await cur.fetchall()]


async def vaciar(db: Conexion, nombres: Sequence[str]) -> None:
    """Borra el contenido de las tablas y reinicia sus contadores de id."""
    if not nombres:
        return
    if es_postgres(db):
        lista = ", ".join(f'"{t}"' for t in nombres)
        await db.execute(f"TRUNCATE {lista} RESTART IDENTITY CASCADE")
        await db.commit()
        return
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        for tabla in nombres:
            await db.execute(f'DELETE FROM "{tabla}"')  # noqa: S608
        cur = await db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'"
        )
        if await cur.fetchone() is not None:
            await db.execute("DELETE FROM sqlite_sequence")
        await db.commit()
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


# ---------------------------------------------------------------------------
# Traducción de SQL
# ---------------------------------------------------------------------------

AHORA_UTC = "(to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))"
HOY_UTC = "(to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD'))"

_I = re.IGNORECASE
_DDL = re.compile(r"^\s*(CREATE\s+TABLE|ALTER\s+TABLE)\b", _I)
_SOLO_SQLITE = re.compile(
    r"\bPRAGMA\b|\bsqlite_(master|sequence|schema)\b|\bINSERT\s+OR\s+\w+"
    r"|\bstrftime\s*\(|\bdatetime\s*\(|\bdate\s*\(\s*'now'|\bjulianday\s*\("
    r"|\bAUTOINCREMENT\b",
    _I,
)
_INSERT = re.compile(r'^\s*INSERT\s+INTO\s+"?(\w+)"?', _I)
_CREA_O_BORRA = re.compile(r"^\s*(CREATE|DROP|ALTER)\s+TABLE\b", _I)
_DDL_IDEMPOTENTE = re.compile(
    r"^\s*CREATE\s+(TABLE|(UNIQUE\s+)?INDEX)\s+IF\s+NOT\s+EXISTS\b", _I
)


class SQLNoPortable(ValueError):
    """SQL propio de SQLite que no tiene traducción a Postgres."""


def traducir(sql: str) -> str:
    """Pasa una sentencia del dialecto común (estilo SQLite) a Postgres.

    No toca los marcadores ``?``: eso lo hace :func:`marcadores`.
    """
    s = sql
    if _DDL.match(s):
        s = re.sub(
            r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
            "BIGSERIAL PRIMARY KEY",
            s,
            flags=_I,
        )
        s = re.sub(r"\bINTEGER\b", "BIGINT", s, flags=_I)
        s = re.sub(r"\bTIMESTAMP\b", "TEXT", s, flags=_I)
        s = re.sub(r"\bREAL\b", "DOUBLE PRECISION", s, flags=_I)
        s = re.sub(r"\bBLOB\b", "BYTEA", s, flags=_I)
    elif _SOLO_SQLITE.search(s):
        raise SQLNoPortable(f"SQL propio de SQLite, sin traducción: {sql.strip()}")
    s = re.sub(r"\bCURRENT_TIMESTAMP\b", AHORA_UTC, s, flags=_I)
    s = re.sub(r"\bCURRENT_DATE\b", HOY_UTC, s, flags=_I)
    return s


def marcadores(sql: str, *, con_nombre: bool = False) -> str:
    """Marcadores de SQLite → psycopg, fuera de las comillas.

    ``?`` → ``%s``; con ``con_nombre``, ``:nombre`` → ``%(nombre)s``. Todo
    ``%`` pasa a ``%%``.
    """
    salida: list[str] = []
    comilla: str | None = None
    i = 0
    while i < len(sql):
        c = sql[i]
        if comilla:
            if c == comilla:
                comilla = None
        elif c in ("'", '"'):
            comilla = c
        elif c == "?":
            salida.append("%s")
            i += 1
            continue
        elif c == ":" and con_nombre:
            m = _NOMBRE.match(sql, i + 1)
            if m and (i == 0 or sql[i - 1] != ":"):
                salida.append(f"%({m.group(0)})s")
                i = m.end()
                continue
        salida.append("%%" if c == "%" else c)
        i += 1
    return "".join(salida)


_NOMBRE = re.compile(r"[A-Za-z_]\w*")


def _parametro(valor: Any) -> Any:
    # Lo mismo que hace sqlite3 con estos tipos: el código los guarda como
    # enteros y texto, y así quedan iguales en los dos motores.
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, datetime):
        return valor.isoformat(" ")
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def _valor(valor: Any) -> Any:
    # SUM y AVG devuelven numeric en Postgres; SQLite, int o float.
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    return valor


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


class FilaPg(tuple[Any, ...]):
    """Como sqlite3.Row: por posición, por nombre (sin mayúsculas) y keys()."""

    _claves: tuple[str, ...]
    _indice: dict[str, int]

    def __new__(
        cls, valores: Iterable[Any], claves: tuple[str, ...], indice: dict[str, int]
    ) -> FilaPg:
        fila = super().__new__(cls, valores)
        fila._claves = claves
        fila._indice = indice
        return fila

    def keys(self) -> list[str]:
        return list(self._claves)

    def __getitem__(self, clave: Any) -> Any:
        if isinstance(clave, str):
            try:
                return tuple.__getitem__(self, self._indice[clave.lower()])
            except KeyError:
                raise IndexError(f"No item with that key: {clave}") from None
        return tuple.__getitem__(self, clave)


def _fabrica_filas(cursor: Any) -> Any:
    descripcion = cursor.description or ()
    claves = tuple(str(c.name) for c in descripcion)
    indice = {c.lower(): i for i, c in reversed(list(enumerate(claves)))}

    def hacer(valores: Sequence[Any]) -> FilaPg:
        return FilaPg((_valor(v) for v in valores), claves, indice)

    return hacer


class CursorPg:
    def __init__(
        self, filas: list[FilaPg], rowcount: int, lastrowid: int | None
    ) -> None:
        self._filas = filas
        self._pos = 0
        self._rowcount = rowcount
        self._lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    async def fetchone(self) -> FilaPg | None:
        if self._pos >= len(self._filas):
            return None
        fila = self._filas[self._pos]
        self._pos += 1
        return fila

    async def fetchall(self) -> list[FilaPg]:
        resto = self._filas[self._pos :]
        self._pos = len(self._filas)
        return resto

    async def close(self) -> None:
        return None


# Por (url, esquema): tablas con id serial y DDL idempotente ya aplicado. Así
# un CREATE TABLE IF NOT EXISTS que se repite en cada petición no viaja al
# servidor una y otra vez.
_SERIALES: dict[tuple[str, str], dict[str, bool]] = {}
_DDL_HECHO: set[tuple[str, str, str]] = set()
_ESQUEMAS_LISTOS: set[tuple[str, str]] = set()

_ESQUEMA_VALIDO = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class ConexionPostgres:
    def __init__(self, conn: Any, url: str, esquema: str) -> None:
        self._conn = conn
        self._clave = (url, esquema)
        self._ddl_pendiente: list[str] = []
        self.esquema = esquema

    @classmethod
    async def abrir(cls, url: str, esquema: str) -> ConexionPostgres:
        import psycopg

        if not _ESQUEMA_VALIDO.match(esquema):
            raise ValueError(f"Nombre de esquema inválido: {esquema!r}")
        conn = await psycopg.AsyncConnection.connect(
            url, row_factory=_fabrica_filas, connect_timeout=10
        )
        db = cls(conn, url, esquema)
        if (url, esquema) not in _ESQUEMAS_LISTOS:
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{esquema}"')
            await conn.commit()
            _ESQUEMAS_LISTOS.add((url, esquema))
        # Solo el esquema del servicio: sin "public", para no leer lo de otro.
        await conn.execute(f'SET search_path TO "{esquema}"')
        await conn.commit()
        return db

    async def execute(
        self, sql: str, parameters: Iterable[Any] | None = None
    ) -> CursorPg:
        if _DDL_IDEMPOTENTE.match(sql):
            clave_ddl = (*self._clave, " ".join(sql.split()))
            if clave_ddl in _DDL_HECHO:
                return CursorPg([], -1, None)
            self._ddl_pendiente.append(clave_ddl[2])
        if _CREA_O_BORRA.match(sql):
            _SERIALES.pop(self._clave, None)
        traducido = traducir(sql)
        lastrowid_de: str | None = None
        insert = _INSERT.match(traducido)
        if (
            insert
            and not re.search(r"\bRETURNING\b", traducido, _I)
            and await self._tiene_id_serial(insert.group(1))
        ):
            traducido = traducido.rstrip().rstrip(";") + " RETURNING id"
            lastrowid_de = insert.group(1)
        params: list[Any] | dict[str, Any] | None
        if parameters is None:
            params = None
        elif isinstance(parameters, Mapping):
            params = {k: _parametro(v) for k, v in parameters.items()}
            traducido = marcadores(traducido, con_nombre=True)
        else:
            params = [_parametro(p) for p in parameters]
            traducido = marcadores(traducido)
        async with self._conn.cursor() as cur:
            await cur.execute(traducido, params)
            filas: list[FilaPg] = (
                await cur.fetchall() if cur.description is not None else []
            )
            rowcount = cur.rowcount
        lastrowid = None
        if lastrowid_de is not None:
            lastrowid = int(filas[0][0]) if filas else None
            filas = []
        return CursorPg(filas, rowcount, lastrowid)

    async def _tiene_id_serial(self, tabla: str) -> bool:
        conocidas = _SERIALES.setdefault(self._clave, {})
        if tabla not in conocidas:
            async with self._conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM information_schema.columns"
                    " WHERE table_schema = current_schema() AND table_name = %s"
                    " AND column_name = 'id' AND column_default LIKE 'nextval%%'",
                    (tabla,),
                )
                conocidas[tabla] = await cur.fetchone() is not None
        return conocidas[tabla]

    async def commit(self) -> None:
        await self._conn.commit()
        for sql in self._ddl_pendiente:
            _DDL_HECHO.add((*self._clave, sql))
        self._ddl_pendiente.clear()

    async def rollback(self) -> None:
        await self._conn.rollback()
        self._ddl_pendiente.clear()

    async def close(self) -> None:
        self._ddl_pendiente.clear()
        await self._conn.close()


def olvidar_cache(url: str, esquema: str) -> None:
    """Para pruebas y migración: el esquema se borró o se recreó."""
    _SERIALES.pop((url, esquema), None)
    _ESQUEMAS_LISTOS.discard((url, esquema))
    for clave in [c for c in _DDL_HECHO if c[:2] == (url, esquema)]:
        _DDL_HECHO.discard(clave)


def servidor_sin_credenciales(url: str) -> str:
    """``host:puerto/base`` de una URL de Postgres, sin usuario ni clave."""
    partes = urlsplit(url)
    host = partes.hostname or "socket local"
    puerto = f":{partes.port}" if partes.port else ""
    return f"{host}{puerto}{partes.path or ''}"


async def probar_postgres(url: str, esquema: str, timeout: float = 5.0) -> str | None:
    """None si el servidor responde; si no, el tipo de error (sin detalles)."""
    import asyncio

    try:
        db = await asyncio.wait_for(ConexionPostgres.abrir(url, esquema), timeout)
    except Exception as exc:  # noqa: BLE001 - se informa solo el tipo
        return type(exc).__name__
    try:
        await asyncio.wait_for(db.execute("SELECT 1"), timeout)
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__
    finally:
        await db.close()
    return None


async def abrir_sqlite(ruta: Any) -> aiosqlite.Connection:
    db = await aiosqlite.connect(ruta)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA journal_mode = WAL")
    return db
