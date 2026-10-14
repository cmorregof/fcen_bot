"""Consultas. Devuelven objetos del dominio, nunca filas sueltas."""

from __future__ import annotations

import json
from dataclasses import dataclass

import aiosqlite

from app.schemas.caso import Caso, Concepto, EstadoCaso, ExtraccionCaso, Sentido

# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usuario:
    telegram_id: int
    nombre: str | None
    direccion: str | None


async def get_usuario(db: aiosqlite.Connection, telegram_id: int) -> Usuario | None:
    cur = await db.execute(
        "SELECT telegram_id, nombre, direccion FROM usuarios WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return Usuario(int(row["telegram_id"]), row["nombre"], row["direccion"])


async def contar_usuarios(db: aiosqlite.Connection) -> int:
    cur = await db.execute("SELECT COUNT(*) FROM usuarios")
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def registrar_usuario(
    db: aiosqlite.Connection, telegram_id: int, nombre: str | None
) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO usuarios (telegram_id, nombre) VALUES (?, ?)",
        (telegram_id, nombre),
    )
    await db.commit()


async def asignar_direccion(
    db: aiosqlite.Connection, telegram_id: int, direccion: str
) -> None:
    await db.execute(
        "UPDATE usuarios SET direccion = ? WHERE telegram_id = ?",
        (direccion, telegram_id),
    )
    await db.commit()


async def usuarios_de(db: aiosqlite.Connection, direccion: str) -> list[Usuario]:
    cur = await db.execute(
        "SELECT telegram_id, nombre, direccion FROM usuarios WHERE direccion = ?",
        (direccion,),
    )
    return [
        Usuario(int(r["telegram_id"]), r["nombre"], r["direccion"])
        for r in await cur.fetchall()
    ]


# ---------------------------------------------------------------------------
# Deduplicación de webhooks
# ---------------------------------------------------------------------------


async def marcar_update(db: aiosqlite.Connection, update_id: int) -> bool:
    """True si el update es nuevo."""
    cur = await db.execute(
        "INSERT OR IGNORE INTO updates_vistos (update_id) VALUES (?)", (update_id,)
    )
    await db.commit()
    return cur.rowcount == 1


# ---------------------------------------------------------------------------
# Estado del chat
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstadoChat:
    caso_abierto_id: int | None
    esperando: str | None
    esperando_caso: int | None


async def get_estado(db: aiosqlite.Connection, chat_id: int) -> EstadoChat:
    cur = await db.execute(
        "SELECT caso_abierto_id, esperando, esperando_caso FROM estado_chat "
        "WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return EstadoChat(None, None, None)
    return EstadoChat(row["caso_abierto_id"], row["esperando"], row["esperando_caso"])


async def set_estado(
    db: aiosqlite.Connection,
    chat_id: int,
    *,
    caso_abierto_id: int | None,
    esperando: str | None = None,
    esperando_caso: int | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO estado_chat (chat_id, caso_abierto_id, esperando, esperando_caso)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            caso_abierto_id = excluded.caso_abierto_id,
            esperando = excluded.esperando,
            esperando_caso = excluded.esperando_caso,
            actualizado = CURRENT_TIMESTAMP
        """,
        (chat_id, caso_abierto_id, esperando, esperando_caso),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------


async def crear_caso(
    db: aiosqlite.Connection, *, chat_id: int, user_id: int, direccion: str
) -> int:
    cur = await db.execute(
        "INSERT INTO casos (chat_id, user_id, direccion) VALUES (?, ?, ?)",
        (chat_id, user_id, direccion),
    )
    await db.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


async def agregar_texto(db: aiosqlite.Connection, caso_id: int, texto: str) -> None:
    await db.execute(
        """
        UPDATE casos
        SET texto = CASE WHEN texto = '' THEN ? ELSE texto || char(10) || ? END,
            actualizado = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (texto, texto, caso_id),
    )
    await db.commit()


async def agregar_archivo(
    db: aiosqlite.Connection,
    caso_id: int,
    *,
    tipo: str,
    ruta: str | None,
    nombre: str | None,
    file_unique_id: str,
) -> bool:
    cur = await db.execute(
        "INSERT OR IGNORE INTO caso_archivos (caso_id, tipo, ruta, nombre, "
        "file_unique_id) VALUES (?, ?, ?, ?, ?)",
        (caso_id, tipo, ruta, nombre, file_unique_id),
    )
    await db.commit()
    return cur.rowcount == 1


async def get_archivo(
    db: aiosqlite.Connection, caso_id: int, file_unique_id: str
) -> tuple[str, str | None, str | None] | None:
    """(tipo, ruta, nombre) de un archivo del caso."""
    cur = await db.execute(
        "SELECT tipo, ruta, nombre FROM caso_archivos WHERE caso_id = ? "
        "AND file_unique_id = ?",
        (caso_id, file_unique_id),
    )
    row = await cur.fetchone()
    return (str(row["tipo"]), row["ruta"], row["nombre"]) if row else None


async def set_tipo_archivo(
    db: aiosqlite.Connection,
    caso_id: int,
    file_unique_id: str,
    *,
    tipo: str,
    ruta: str | None,
) -> None:
    await db.execute(
        "UPDATE caso_archivos SET tipo = ?, ruta = ? WHERE caso_id = ? "
        "AND file_unique_id = ?",
        (tipo, ruta, caso_id, file_unique_id),
    )
    await db.execute(
        "UPDATE casos SET actualizado = CURRENT_TIMESTAMP WHERE id = ?", (caso_id,)
    )
    await db.commit()


async def _archivos(
    db: aiosqlite.Connection, caso_id: int
) -> tuple[list[str], list[str]]:
    cur = await db.execute(
        "SELECT tipo, ruta, nombre FROM caso_archivos WHERE caso_id = ? ORDER BY id",
        (caso_id,),
    )
    imagenes: list[str] = []
    anexos: list[str] = []
    for row in await cur.fetchall():
        if row["tipo"] == "imagen" and row["ruta"]:
            imagenes.append(str(row["ruta"]))
        elif row["tipo"] == "formato":
            continue  # su texto ya está en el caso
        else:
            anexos.append(str(row["nombre"] or "archivo"))
    return imagenes, anexos


async def conceptos_de(db: aiosqlite.Connection, caso_id: int) -> list[Concepto]:
    cur = await db.execute(
        "SELECT miembro, tratamiento, texto FROM conceptos WHERE caso_id = ? "
        "ORDER BY id",
        (caso_id,),
    )
    return [
        Concepto(miembro=r["miembro"], tratamiento=r["tratamiento"], texto=r["texto"])
        for r in await cur.fetchall()
    ]


async def guardar_concepto(
    db: aiosqlite.Connection,
    caso_id: int,
    *,
    miembro: str,
    tratamiento: str | None,
    texto: str,
) -> None:
    """Un concepto por miembro y caso: si llega otro, reemplaza al anterior."""
    await db.execute(
        """
        INSERT INTO conceptos (caso_id, miembro, tratamiento, texto)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(caso_id, miembro) DO UPDATE SET
            tratamiento = excluded.tratamiento,
            texto = excluded.texto,
            creado = CURRENT_TIMESTAMP
        """,
        (caso_id, miembro, tratamiento, texto),
    )
    # El borrador del día se rehace si cambió algún caso.
    await db.execute(
        "UPDATE casos SET actualizado = CURRENT_TIMESTAMP WHERE id = ?", (caso_id,)
    )
    await db.commit()


async def borrar_concepto(db: aiosqlite.Connection, caso_id: int, miembro: str) -> bool:
    cur = await db.execute(
        "DELETE FROM conceptos WHERE caso_id = ? AND miembro = ?", (caso_id, miembro)
    )
    await db.execute(
        "UPDATE casos SET actualizado = CURRENT_TIMESTAMP WHERE id = ?", (caso_id,)
    )
    await db.commit()
    return (cur.rowcount or 0) > 0


async def _row_to_caso(db: aiosqlite.Connection, row: aiosqlite.Row) -> Caso:
    imagenes, anexos = await _archivos(db, int(row["id"]))
    extraccion = (
        ExtraccionCaso.model_validate_json(row["extraccion_json"])
        if row["extraccion_json"]
        else None
    )
    return Caso(
        id=int(row["id"]),
        chat_id=int(row["chat_id"]),
        direccion=str(row["direccion"]),
        programa=row["programa"],
        estado=EstadoCaso(row["estado"]),
        sentido=Sentido(row["sentido"]),
        texto=str(row["texto"] or ""),
        imagenes=imagenes,
        anexos_archivos=anexos,
        extraccion=extraccion,
        nota_comite=row["nota_comite"],
        conceptos=await conceptos_de(db, int(row["id"])),
        creado=str(row["creado"]) if row["creado"] else None,
    )


async def get_caso(db: aiosqlite.Connection, caso_id: int) -> Caso | None:
    cur = await db.execute("SELECT * FROM casos WHERE id = ?", (caso_id,))
    row = await cur.fetchone()
    return await _row_to_caso(db, row) if row else None


async def set_estado_caso(
    db: aiosqlite.Connection,
    caso_id: int,
    estado: EstadoCaso,
    *,
    error: str | None = None,
) -> None:
    await db.execute(
        "UPDATE casos SET estado = ?, error = ?, actualizado = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (estado.value, error, caso_id),
    )
    await db.commit()


async def guardar_extraccion(
    db: aiosqlite.Connection,
    caso_id: int,
    extraccion: ExtraccionCaso,
    programa: str | None,
) -> None:
    await db.execute(
        "UPDATE casos SET extraccion_json = ?, programa = ?, estado = ?, error = NULL, "
        "actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (
            extraccion.model_dump_json(),
            programa,
            EstadoCaso.LISTO.value,
            caso_id,
        ),
    )
    await db.commit()


async def actualizar_extraccion(
    db: aiosqlite.Connection,
    caso_id: int,
    extraccion: ExtraccionCaso,
    programa: str | None,
) -> None:
    """Como guardar_extraccion, pero sin tocar el estado (correcciones)."""
    await db.execute(
        "UPDATE casos SET extraccion_json = ?, programa = ?, "
        "actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (extraccion.model_dump_json(), programa, caso_id),
    )
    await db.commit()


async def reabrir_interrumpidos(db: aiosqlite.Connection) -> int:
    """Al arrancar: los casos que quedaron a mitad de lectura vuelven a abiertos."""
    cur = await db.execute(
        "UPDATE casos SET estado = ? WHERE estado = ?",
        (EstadoCaso.ABIERTO.value, EstadoCaso.PROCESANDO.value),
    )
    await db.commit()
    return cur.rowcount


async def set_programa(db: aiosqlite.Connection, caso_id: int, programa: str) -> None:
    await db.execute(
        "UPDATE casos SET programa = ?, actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (programa, caso_id),
    )
    await db.commit()


async def set_sentido(db: aiosqlite.Connection, caso_id: int, sentido: Sentido) -> None:
    await db.execute(
        "UPDATE casos SET sentido = ?, actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (sentido.value, caso_id),
    )
    await db.commit()


async def set_nota(db: aiosqlite.Connection, caso_id: int, nota: str | None) -> None:
    await db.execute(
        "UPDATE casos SET nota_comite = ?, actualizado = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (nota, caso_id),
    )
    await db.commit()


async def casos_listos(db: aiosqlite.Connection, *, direccion: str) -> list[Caso]:
    """Casos procesados que todavía no se han cerrado: forman el borrador en curso."""
    cur = await db.execute(
        "SELECT * FROM casos WHERE direccion = ? AND estado = ? ORDER BY id",
        (direccion, EstadoCaso.LISTO.value),
    )
    return [await _row_to_caso(db, row) for row in await cur.fetchall()]


async def cerrar_casos(db: aiosqlite.Connection, caso_ids: list[int]) -> None:
    if not caso_ids:
        return
    marcas = ",".join("?" for _ in caso_ids)
    await db.execute(
        f"UPDATE casos SET estado = ?, actualizado = CURRENT_TIMESTAMP "
        f"WHERE id IN ({marcas}) AND estado = ?",
        (EstadoCaso.CERRADO.value, *caso_ids, EstadoCaso.LISTO.value),
    )
    await db.commit()


@dataclass(frozen=True)
class FirmaBorrador:
    caso_ids: tuple[int, ...]
    ultima_modificacion: str


async def firma_actual(
    db: aiosqlite.Connection, *, direccion: str, programa: str
) -> FirmaBorrador:
    """Qué casos y hasta cuándo modificados componen hoy el borrador del programa."""
    cur = await db.execute(
        "SELECT id, actualizado FROM casos WHERE direccion = ? AND programa = ? "
        "AND estado = ? ORDER BY id",
        (direccion, programa, EstadoCaso.LISTO.value),
    )
    filas = await cur.fetchall()
    ids = tuple(int(r["id"]) for r in filas)
    ultima = max((str(r["actualizado"]) for r in filas), default="")
    return FirmaBorrador(ids, ultima)


async def ultimo_borrador(
    db: aiosqlite.Connection, programa: str
) -> FirmaBorrador | None:
    cur = await db.execute(
        "SELECT caso_ids, ultima_modificacion FROM borradores WHERE programa = ? "
        "ORDER BY id DESC LIMIT 1",
        (programa,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return FirmaBorrador(
        tuple(json.loads(row["caso_ids"])), str(row["ultima_modificacion"] or "")
    )


async def casos_recientes(
    db: aiosqlite.Connection, *, direccion: str, limite: int = 15
) -> list[Caso]:
    cur = await db.execute(
        "SELECT * FROM casos WHERE direccion = ? AND estado != ? "
        "ORDER BY id DESC LIMIT ?",
        (direccion, EstadoCaso.DESCARTADO.value, limite),
    )
    return [await _row_to_caso(db, row) for row in await cur.fetchall()]


async def registrar_borrador(
    db: aiosqlite.Connection,
    *,
    programa: str,
    caso_ids: list[int],
    docx_path: str,
    pdf_path: str | None,
    ultima_modificacion: str,
) -> int:
    """Se registra solo después de entregar. `ultima_modificacion` es la que se
    leyó al armar el documento: un cambio posterior se detecta al día siguiente."""
    cur = await db.execute(
        "INSERT INTO borradores (programa, caso_ids, docx_path, pdf_path, "
        "ultima_modificacion) VALUES (?, ?, ?, ?, ?)",
        (programa, json.dumps(caso_ids), docx_path, pdf_path, ultima_modificacion),
    )
    await db.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Uso del modelo (para estimar el costo mensual)
# ---------------------------------------------------------------------------


async def registrar_uso(
    db: aiosqlite.Connection,
    *,
    caso_id: int | None,
    operacion: str,
    modelo: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    await db.execute(
        "INSERT INTO uso_modelo (caso_id, operacion, modelo, input_tokens, "
        "output_tokens) VALUES (?, ?, ?, ?, ?)",
        (caso_id, operacion, modelo, input_tokens, output_tokens),
    )
    await db.commit()


@dataclass(frozen=True)
class UsoMes:
    llamadas: int
    casos: int
    input_tokens: int
    output_tokens: int


async def uso_del_mes(db: aiosqlite.Connection, mes: str) -> UsoMes:
    """`mes` en formato AAAA-MM (UTC)."""
    cur = await db.execute(
        "SELECT COUNT(*), COUNT(DISTINCT caso_id), COALESCE(SUM(input_tokens), 0), "
        "COALESCE(SUM(output_tokens), 0) FROM uso_modelo "
        "WHERE strftime('%Y-%m', creado) = ?",
        (mes,),
    )
    row = await cur.fetchone()
    if row is None:
        return UsoMes(0, 0, 0, 0)
    return UsoMes(int(row[0]), int(row[1]), int(row[2]), int(row[3]))
