"""Consultas. Devuelven objetos del dominio, nunca filas sueltas."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.conexion import Conexion, Fila
from app.schemas.anexo import AnexoLeido, LecturaAnexo
from app.schemas.caso import Caso, Concepto, EstadoCaso, ExtraccionCaso, Sentido
from app.schemas.consejo import DecisionConsejo, Instancia, SentidoConsejo

# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usuario:
    telegram_id: int
    nombre: str | None
    direccion: str | None


async def get_usuario(db: Conexion, telegram_id: int) -> Usuario | None:
    cur = await db.execute(
        "SELECT telegram_id, nombre, direccion FROM usuarios WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return Usuario(int(row["telegram_id"]), row["nombre"], row["direccion"])


async def contar_usuarios(db: Conexion) -> int:
    cur = await db.execute("SELECT COUNT(*) FROM usuarios")
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def registrar_usuario(db: Conexion, telegram_id: int, nombre: str | None) -> None:
    await db.execute(
        "INSERT INTO usuarios (telegram_id, nombre) VALUES (?, ?)"
        " ON CONFLICT DO NOTHING",
        (telegram_id, nombre),
    )
    await db.commit()


async def asignar_direccion(db: Conexion, telegram_id: int, direccion: str) -> None:
    await db.execute(
        "UPDATE usuarios SET direccion = ? WHERE telegram_id = ?",
        (direccion, telegram_id),
    )
    await db.commit()


async def usuarios_de(db: Conexion, direccion: str) -> list[Usuario]:
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


async def marcar_update(db: Conexion, update_id: int) -> bool:
    """True si el update es nuevo."""
    cur = await db.execute(
        "INSERT INTO updates_vistos (update_id) VALUES (?) ON CONFLICT DO NOTHING",
        (update_id,),
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


async def get_estado(db: Conexion, chat_id: int) -> EstadoChat:
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
    db: Conexion,
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
    db: Conexion,
    *,
    chat_id: int,
    user_id: int,
    direccion: str,
    canal: str = "telegram",
    persona: str | None = None,
    rol: str = "administrativa",
) -> int:
    """Crea la ficha y abre su línea de estados («llegada»)."""
    from app.services import flujo

    cur = await db.execute(
        "INSERT INTO casos (chat_id, user_id, direccion) VALUES (?, ?, ?)",
        (chat_id, user_id, direccion),
    )
    assert cur.lastrowid is not None
    caso_id = int(cur.lastrowid)
    cur = await db.execute("SELECT creado FROM casos WHERE id = ?", (caso_id,))
    fila = await cur.fetchone()
    await flujo.transicionar(
        db,
        caso_id,
        flujo.Accion.REGISTRAR,
        rol=rol,
        persona=persona,
        canal=canal,
        fecha=str(fila["creado"]) if fila and fila["creado"] else None,
    )
    return caso_id


async def agregar_texto(db: Conexion, caso_id: int, texto: str) -> None:
    await db.execute(
        """
        UPDATE casos
        SET texto = CASE WHEN texto = '' THEN ? ELSE texto || ? END,
            actualizado = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (texto, "\n" + texto, caso_id),
    )
    await db.commit()


async def agregar_archivo(
    db: Conexion,
    caso_id: int,
    *,
    tipo: str,
    ruta: str | None,
    nombre: str | None,
    file_unique_id: str,
    bytes_: int | None = None,
) -> bool:
    cur = await db.execute(
        "INSERT INTO caso_archivos (caso_id, tipo, ruta, nombre, "
        "file_unique_id, bytes) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (caso_id, tipo, ruta, nombre, file_unique_id, bytes_),
    )
    await db.commit()
    return cur.rowcount == 1


@dataclass(frozen=True)
class Archivo:
    """Un adjunto del caso (app/services/adjuntos.py)."""

    id: int
    tipo: str
    ruta: str | None
    nombre: str | None
    file_unique_id: str | None
    bytes_: int | None
    creado: str | None
    leido: str | None  # cuándo entró a una lectura del modelo
    resumen: str | None = None  # JSON de LecturaAnexo (app/services/anexos.py)


def _archivo(r: Fila) -> Archivo:
    return Archivo(
        id=int(r["id"]),
        tipo=str(r["tipo"]),
        ruta=r["ruta"],
        nombre=r["nombre"],
        file_unique_id=r["file_unique_id"],
        bytes_=int(r["bytes"]) if r["bytes"] is not None else None,
        creado=str(r["creado"]) if r["creado"] else None,
        leido=str(r["leido"]) if r["leido"] else None,
        resumen=r["resumen"],
    )


_COLS_ARCHIVO = "id, tipo, ruta, nombre, file_unique_id, bytes, creado, leido, resumen"


async def archivos_de(
    db: Conexion, caso_id: int, *, derivados: bool = True
) -> list[Archivo]:
    """Los adjuntos del caso en orden de llegada. Sin `derivados`, se omiten
    las páginas convertidas de un PDF escaneado (van con su PDF)."""
    cur = await db.execute(
        f"SELECT {_COLS_ARCHIVO} FROM caso_archivos WHERE caso_id = ? ORDER BY id",
        (caso_id,),
    )
    todos = [_archivo(r) for r in await cur.fetchall()]
    if derivados:
        return todos
    unicos = {a.file_unique_id for a in todos if a.file_unique_id}
    return [a for a in todos if not _es_pagina(a.file_unique_id, unicos)]


def _es_pagina(unico: str | None, unicos: set[str]) -> bool:
    if not unico or "_p" not in unico:
        return False
    base, _, n = unico.rpartition("_p")
    return n.isdigit() and base in unicos


async def get_archivo_por_id(
    db: Conexion, caso_id: int, archivo_id: int
) -> Archivo | None:
    cur = await db.execute(
        f"SELECT {_COLS_ARCHIVO} FROM caso_archivos WHERE caso_id = ? AND id = ?",
        (caso_id, archivo_id),
    )
    r = await cur.fetchone()
    return _archivo(r) if r else None


async def borrar_archivo(db: Conexion, caso_id: int, archivo_id: int) -> None:
    """Sin commit: lo hace quien borra, junto con el evento."""
    await db.execute(
        "DELETE FROM caso_archivos WHERE caso_id = ? AND id = ?", (caso_id, archivo_id)
    )
    await db.execute(
        "UPDATE casos SET actualizado = CURRENT_TIMESTAMP WHERE id = ?", (caso_id,)
    )


async def set_resumen_archivo(
    db: Conexion, caso_id: int, archivo_id: int, resumen: str | None
) -> None:
    """Guarda (o quita, con None) el resumen de un anexo del estudiante."""
    await db.execute(
        "UPDATE caso_archivos SET resumen = ? WHERE caso_id = ? AND id = ?",
        (resumen, caso_id, archivo_id),
    )
    await db.execute(
        "UPDATE casos SET actualizado = CURRENT_TIMESTAMP WHERE id = ?", (caso_id,)
    )
    await db.commit()


async def set_texto(db: Conexion, caso_id: int, texto: str) -> None:
    """Sin commit (se usa al quitar el texto de un formato borrado)."""
    await db.execute(
        "UPDATE casos SET texto = ?, actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (texto, caso_id),
    )


async def marcar_leidos(db: Conexion, caso_id: int) -> None:
    """Los adjuntos que había en el caso cuando el modelo lo leyó."""
    await db.execute(
        "UPDATE caso_archivos SET leido = CURRENT_TIMESTAMP "
        "WHERE caso_id = ? AND leido IS NULL",
        (caso_id,),
    )
    await db.commit()


async def get_archivo(
    db: Conexion, caso_id: int, file_unique_id: str
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
    db: Conexion,
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
    db: Conexion, caso_id: int
) -> tuple[list[str], list[str], list[AnexoLeido]]:
    cur = await db.execute(
        "SELECT id, tipo, ruta, nombre, resumen FROM caso_archivos "
        "WHERE caso_id = ? ORDER BY id",
        (caso_id,),
    )
    imagenes: list[str] = []
    anexos: list[str] = []
    leidos: list[AnexoLeido] = []
    for row in await cur.fetchall():
        if row["tipo"] == "imagen" and row["ruta"]:
            imagenes.append(str(row["ruta"]))
        elif row["tipo"] == "formato":
            continue  # su texto ya está en el caso
        else:
            anexos.append(str(row["nombre"] or "archivo"))
            if row["resumen"]:
                try:
                    lectura = LecturaAnexo.model_validate_json(row["resumen"])
                except ValueError:
                    continue
                leidos.append(
                    AnexoLeido(
                        archivo_id=int(row["id"]),
                        nombre=str(row["nombre"] or "archivo"),
                        lectura=lectura,
                    )
                )
    return imagenes, anexos, leidos


async def conceptos_de(db: Conexion, caso_id: int) -> list[Concepto]:
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
    db: Conexion,
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


async def borrar_concepto(db: Conexion, caso_id: int, miembro: str) -> bool:
    cur = await db.execute(
        "DELETE FROM conceptos WHERE caso_id = ? AND miembro = ?", (caso_id, miembro)
    )
    await db.execute(
        "UPDATE casos SET actualizado = CURRENT_TIMESTAMP WHERE id = ?", (caso_id,)
    )
    await db.commit()
    return (cur.rowcount or 0) > 0


async def decision_consejo(db: Conexion, caso_id: int) -> DecisionConsejo | None:
    """La decisión del Consejo confirmada para el caso, si la hay."""
    cur = await db.execute(
        "SELECT * FROM decisiones_consejo WHERE caso_id = ?", (caso_id,)
    )
    r = await cur.fetchone()
    if r is None:
        return None
    return DecisionConsejo(
        caso_id=int(r["caso_id"]),
        instancia=Instancia(r["instancia"]),
        sentido=SentidoConsejo(r["sentido"]),
        texto_decision=r["texto_decision"],
        acta_numero=r["acta_numero"],
        acta_fecha=r["acta_fecha"],
        fragmento=r["fragmento"],
        confirmado_por=r["confirmado_por"],
        confirmado=str(r["confirmado"]) if r["confirmado"] else None,
    )


async def _row_to_caso(db: Conexion, row: Fila) -> Caso:
    imagenes, anexos, leidos = await _archivos(db, int(row["id"]))
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
        anexos_leidos=leidos,
        extraccion=extraccion,
        nota_comite=row["nota_comite"],
        conceptos=await conceptos_de(db, int(row["id"])),
        creado=str(row["creado"]) if row["creado"] else None,
        consejo=await decision_consejo(db, int(row["id"])),
        etapa=row["etapa"],
        prerrevision=row["prerrevision"],
        archivado=str(row["archivado"]) if row["archivado"] else None,
    )


async def get_caso(db: Conexion, caso_id: int) -> Caso | None:
    cur = await db.execute("SELECT * FROM casos WHERE id = ?", (caso_id,))
    row = await cur.fetchone()
    return await _row_to_caso(db, row) if row else None


async def set_estado_caso(
    db: Conexion,
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
    db: Conexion,
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
    db: Conexion,
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


async def reabrir_interrumpidos(db: Conexion) -> int:
    """Al arrancar: los casos que quedaron a mitad de lectura vuelven a abiertos."""
    cur = await db.execute(
        "UPDATE casos SET estado = ? WHERE estado = ?",
        (EstadoCaso.ABIERTO.value, EstadoCaso.PROCESANDO.value),
    )
    await db.commit()
    return cur.rowcount


async def set_programa(db: Conexion, caso_id: int, programa: str) -> None:
    await db.execute(
        "UPDATE casos SET programa = ?, actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (programa, caso_id),
    )
    await db.commit()


async def set_sentido(
    db: Conexion, caso_id: int, sentido: Sentido, *, commit: bool = True
) -> None:
    # `recomendado` guarda cuándo se registró la recomendación (indicadores).
    # Solo un cambio real de sentido la mueve: volver a marcar el mismo sentido
    # no la cambia (ni se la inventa a un caso viejo sin fecha) y volver a
    # «pendiente» la borra. Con decisión del Consejo ya registrada no se mueve:
    # los días de la recomendación al acta se miden con la fecha original.
    await db.execute(
        """
        UPDATE casos SET
            recomendado = CASE
                WHEN EXISTS (
                    SELECT 1 FROM decisiones_consejo d WHERE d.caso_id = casos.id
                ) THEN recomendado
                WHEN :sentido = :pendiente THEN NULL
                WHEN sentido = :sentido THEN recomendado
                ELSE CURRENT_TIMESTAMP END,
            sentido = :sentido,
            actualizado = CURRENT_TIMESTAMP
        WHERE id = :id
        """,
        {"sentido": sentido.value, "pendiente": Sentido.PENDIENTE.value, "id": caso_id},
    )
    if commit:
        await db.commit()


async def set_nota(db: Conexion, caso_id: int, nota: str | None) -> None:
    await db.execute(
        "UPDATE casos SET nota_comite = ?, actualizado = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (nota, caso_id),
    )
    await db.commit()


# La prerrevisión del programa saca del borrador del comité los casos
# incompletos y los improcedentes que no van al comité (app/services/flujo.py).
_FUERA_DEL_COMITE = "AND COALESCE(etapa, '') NOT IN ('incompleta', 'improcedente')"


async def casos_listos(db: Conexion, *, direccion: str) -> list[Caso]:
    """Casos procesados que todavía no se han cerrado: forman el borrador en curso."""
    cur = await db.execute(
        "SELECT * FROM casos WHERE direccion = ? AND estado = ? "
        + _FUERA_DEL_COMITE
        + " ORDER BY id",
        (direccion, EstadoCaso.LISTO.value),
    )
    return [await _row_to_caso(db, row) for row in await cur.fetchall()]


async def cerrar_casos(
    db: Conexion, caso_ids: list[int], *, commit: bool = True
) -> None:
    if not caso_ids:
        return
    marcas = ",".join("?" for _ in caso_ids)
    await db.execute(
        f"UPDATE casos SET estado = ?, actualizado = CURRENT_TIMESTAMP "
        f"WHERE id IN ({marcas}) AND estado = ?",
        (EstadoCaso.CERRADO.value, *caso_ids, EstadoCaso.LISTO.value),
    )
    if commit:
        await db.commit()


async def reabrir_en_borrador(db: Conexion, caso_id: int) -> None:
    """El caso vuelve del Consejo al comité: entra otra vez al borrador."""
    await db.execute(
        "UPDATE casos SET estado = ?, actualizado = CURRENT_TIMESTAMP "
        "WHERE id = ? AND estado = ?",
        (EstadoCaso.LISTO.value, caso_id, EstadoCaso.CERRADO.value),
    )


async def set_prerrevision(db: Conexion, caso_id: int, resultado: str) -> None:
    """Sin commit: la registra flujo.prerrevisar junto con la transición."""
    await db.execute(
        "UPDATE casos SET prerrevision = ?, actualizado = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (resultado, caso_id),
    )


@dataclass(frozen=True)
class FirmaBorrador:
    caso_ids: tuple[int, ...]
    ultima_modificacion: str


async def firma_actual(
    db: Conexion, *, direccion: str, programas: tuple[str, ...]
) -> FirmaBorrador:
    """Qué casos y hasta cuándo modificados componen hoy el borrador del comité
    (los de sus programas: uno en pregrado, varios en un comité único)."""
    marcas = ",".join("?" for _ in programas)
    cur = await db.execute(
        f"SELECT id, actualizado FROM casos WHERE direccion = ? "
        f"AND programa IN ({marcas}) AND estado = ? "
        + _FUERA_DEL_COMITE
        + " ORDER BY id",
        (direccion, *programas, EstadoCaso.LISTO.value),
    )
    filas = await cur.fetchall()
    ids = tuple(int(r["id"]) for r in filas)
    ultima = max((str(r["actualizado"]) for r in filas), default="")
    return FirmaBorrador(ids, ultima)


async def ultimo_borrador(db: Conexion, programa: str) -> FirmaBorrador | None:
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
    db: Conexion,
    *,
    direccion: str,
    limite: int = 15,
    archivados: bool | None = None,
) -> list[Caso]:
    """`archivados`: None, todos; False, solo los de la bandeja; True, solo los
    que la administrativa sacó de la bandeja."""
    filtro = ""
    if archivados is not None:
        filtro = (
            " AND archivado IS NOT NULL" if archivados else " AND archivado IS NULL"
        )
    cur = await db.execute(
        "SELECT * FROM casos WHERE direccion = ? AND estado != ?"
        + filtro
        + " ORDER BY id DESC LIMIT ?",
        (direccion, EstadoCaso.DESCARTADO.value, limite),
    )
    return [await _row_to_caso(db, row) for row in await cur.fetchall()]


async def registrar_borrador(
    db: Conexion,
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
    db: Conexion,
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


async def uso_del_mes(db: Conexion, mes: str) -> UsoMes:
    """`mes` en formato AAAA-MM (UTC)."""
    cur = await db.execute(
        "SELECT COUNT(*), COUNT(DISTINCT caso_id), COALESCE(SUM(input_tokens), 0), "
        "COALESCE(SUM(output_tokens), 0) FROM uso_modelo "
        "WHERE substr(creado, 1, 7) = ?",
        (mes,),
    )
    row = await cur.fetchone()
    if row is None:
        return UsoMes(0, 0, 0, 0)
    return UsoMes(int(row[0]), int(row[1]), int(row[2]), int(row[3]))
