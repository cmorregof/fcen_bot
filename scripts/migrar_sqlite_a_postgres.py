"""Copia la base SQLite de un servicio al esquema de ese servicio en Postgres.

Uso (con MIGRACION_DATABASE_URL o DATABASE_URL en el entorno; ver
docs/base-de-datos.md):

    uv run python scripts/migrar_sqlite_a_postgres.py \\
        --sqlite /data/actas/fcen.db --servicio actas

- Lee la SQLite en modo solo lectura, en una sola transacción (una foto
  consistente aunque el servicio siga escribiendo): no la modifica.
- Crea el esquema y las tablas que falten (con la misma traducción que usa el
  servicio) y copia las filas en una sola transacción.
- Es idempotente: una fila que ya está (misma clave) no se duplica; correrlo
  dos veces deja lo mismo.
- Al terminar compara los conteos por tabla. Si alguno no coincide, deshace la
  copia y sale con código 1.
- ``--solo-verificar`` solo compara conteos, sin escribir.

No imprime datos de las filas, solo nombres de tablas y conteos.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.core.conexion import (  # noqa: E402
    servidor_sin_credenciales,
    traducir,
)

SERVICIOS = ("actas", "calidad", "admision")
_ESQUEMA_VALIDO = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _q(nombre: str) -> str:
    return '"' + nombre.replace('"', '""') + '"'


def abrir_sqlite(ruta: Path) -> sqlite3.Connection:
    if not ruta.is_file():
        raise SystemExit(f"No existe la base SQLite {ruta}.")
    src = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, isolation_level=None)
    src.execute("BEGIN")  # todas las lecturas ven el mismo estado de la base
    return src


def tablas_sqlite(src: sqlite3.Connection) -> dict[str, str]:
    """Nombre → CREATE TABLE, sin las tablas internas de SQLite."""
    filas = src.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
        " AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {str(n): str(s) for n, s in filas}


def indices_sqlite(src: sqlite3.Connection) -> list[str]:
    filas = src.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
    ).fetchall()
    return [str(f[0]) for f in filas]


def columnas_sqlite(src: sqlite3.Connection, tabla: str) -> list[tuple[str, str]]:
    return [
        (str(f[1]), str(f[2] or "TEXT"))
        for f in src.execute(f"PRAGMA table_info({_q(tabla)})")
    ]


def en_orden(src: sqlite3.Connection, nombres: Sequence[str]) -> list[str]:
    """Primero las tablas a las que otras apuntan (llaves foráneas)."""
    depende = {
        t: {
            str(f[2])
            for f in src.execute(f"PRAGMA foreign_key_list({_q(t)})")
            if str(f[2]) != t and str(f[2]) in nombres
        }
        for t in nombres
    }
    orden: list[str] = []
    while depende:
        listas = sorted(t for t, d in depende.items() if not d - set(orden))
        if not listas:  # ciclo: el resto en orden alfabético
            listas = sorted(depende)
        for t in listas:
            orden.append(t)
            depende.pop(t)
    return orden


def con_if_not_exists(sql: str) -> str:
    return re.sub(
        r"^\s*CREATE\s+(UNIQUE\s+)?(TABLE|INDEX)\s+(IF\s+NOT\s+EXISTS\s+)?",
        lambda m: f"CREATE {m.group(1) or ''}{m.group(2)} IF NOT EXISTS ",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )


def columnas_pg(dst: psycopg.Connection[Any], tabla: str) -> list[str]:
    filas = dst.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = %s",
        (tabla,),
    ).fetchall()
    return [str(f[0]) for f in filas]


def tiene_clave_unica(dst: psycopg.Connection[Any], tabla: str) -> bool:
    fila = dst.execute(
        "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = current_schema() AND c.relname = %s AND i.indisunique",
        (tabla,),
    ).fetchone()
    return fila is not None


def contar(cur: Any, tabla: str) -> int:
    fila = cur.execute(f"SELECT COUNT(*) FROM {_q(tabla)}").fetchone()
    return int(fila[0]) if fila else 0


def crear_tablas(
    src: sqlite3.Connection, dst: psycopg.Connection[Any], tablas: dict[str, str]
) -> None:
    for tabla in en_orden(src, list(tablas)):
        dst.execute(traducir(con_if_not_exists(tablas[tabla])))
        # Si el servicio ya la creó con menos columnas, se agregan las que faltan.
        existentes = set(columnas_pg(dst, tabla))
        for columna, tipo in columnas_sqlite(src, tabla):
            if columna not in existentes:
                dst.execute(
                    traducir(f"ALTER TABLE {_q(tabla)} ADD COLUMN {_q(columna)} {tipo}")
                )
    for sql in indices_sqlite(src):
        dst.execute(traducir(con_if_not_exists(sql)))


def copiar_tabla(
    src: sqlite3.Connection, dst: psycopg.Connection[Any], tabla: str
) -> int:
    columnas = [c for c, _ in columnas_sqlite(src, tabla)]
    filas = src.execute(
        f"SELECT {', '.join(_q(c) for c in columnas)} FROM {_q(tabla)}"
    ).fetchall()
    if not filas:
        return 0
    if not tiene_clave_unica(dst, tabla):
        # Sin clave no hay cómo saber si una fila ya está: solo se copia si
        # la tabla destino está vacía.
        if contar(dst, tabla):
            print(f"  {tabla}: sin clave única y ya tiene filas; no se copia.")
            return 0
        sufijo = ""
    else:
        sufijo = " ON CONFLICT DO NOTHING"
    sql = (
        f"INSERT INTO {_q(tabla)} ({', '.join(_q(c) for c in columnas)})"
        f" VALUES ({', '.join(['%s'] * len(columnas))}){sufijo}"
    )
    with dst.cursor() as cur:
        cur.executemany(sql, filas)
    return len(filas)


def ajustar_secuencias(dst: psycopg.Connection[Any], tablas: Sequence[str]) -> None:
    """Los ids seriales siguen después del mayor id copiado."""
    for tabla in tablas:
        fila = dst.execute(
            "SELECT pg_get_serial_sequence(%s, 'id') FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = %s"
            " AND column_name = 'id'",
            (_q(tabla), tabla),
        ).fetchone()
        if fila and fila[0]:
            dst.execute(
                f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {_q(tabla)}), 1),"
                f" (SELECT MAX(id) FROM {_q(tabla)}) IS NOT NULL)",
                (fila[0],),
            )


def verificar(
    src: sqlite3.Connection, dst: psycopg.Connection[Any], tablas: Sequence[str]
) -> bool:
    print(f"{'tabla':<32}{'sqlite':>10}{'postgres':>10}")
    bien = True
    for tabla in tablas:
        a = contar(src, tabla)
        existe = dst.execute(
            "SELECT 1 FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_name = %s",
            (tabla,),
        ).fetchone()
        b = contar(dst, tabla) if existe else -1
        marca = "" if a == b else "  ← no coincide"
        bien = bien and a == b
        print(f"{tabla:<32}{a:>10}{b:>10}{marca}")
    return bien


def migrar(ruta: Path, url: str, esquema: str, *, solo_verificar: bool = False) -> bool:
    if not _ESQUEMA_VALIDO.match(esquema):
        raise SystemExit(f"Esquema inválido: {esquema!r}")
    src = abrir_sqlite(ruta)
    tablas = tablas_sqlite(src)
    print(
        f"SQLite {ruta} → Postgres {servidor_sin_credenciales(url)},"
        f" esquema {esquema} ({len(tablas)} tablas)"
    )
    with psycopg.connect(url) as dst:
        if solo_verificar:
            dst.execute(f"SET search_path TO {_q(esquema)}")
            return verificar(src, dst, sorted(tablas))
        dst.execute(f"CREATE SCHEMA IF NOT EXISTS {_q(esquema)}")
        dst.execute(f"SET search_path TO {_q(esquema)}")
        crear_tablas(src, dst, tablas)
        orden = en_orden(src, list(tablas))
        for tabla in orden:
            n = copiar_tabla(src, dst, tabla)
            print(f"  {tabla}: {n} filas leídas")
        ajustar_secuencias(dst, orden)
        if not verificar(src, dst, sorted(tablas)):
            dst.rollback()
            print("Los conteos no coinciden: no se guardó nada.")
            return False
        dst.commit()
    print("Listo: conteos iguales en todas las tablas.")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sqlite", type=Path, required=True, help="archivo .db de origen")
    p.add_argument("--servicio", choices=SERVICIOS, required=True)
    p.add_argument(
        "--esquema", help="esquema destino (por defecto, el nombre del servicio)"
    )
    p.add_argument("--solo-verificar", action="store_true", help="solo compara conteos")
    args = p.parse_args(argv)
    # MIGRACION_DATABASE_URL deja copiar antes del corte: el servicio sigue en
    # SQLite mientras no tenga DATABASE_URL.
    url = os.environ.get("MIGRACION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgres://")):
        print(
            "Falta MIGRACION_DATABASE_URL o DATABASE_URL (postgresql://…).",
            file=sys.stderr,
        )
        return 2
    esquema = args.esquema or args.servicio
    if args.servicio != "actas" and esquema == "actas":
        print("Solo actas usa el esquema actas.", file=sys.stderr)
        return 2
    ok = migrar(args.sqlite, url, esquema, solo_verificar=args.solo_verificar)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
