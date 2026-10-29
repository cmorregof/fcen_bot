"""Servicio de calidad: seguimiento del plan de mejoramiento y acreditación."""

from __future__ import annotations

import hmac
import json
from html import escape

import aiosqlite

from app.db import repo
from app.integrations import telegram
from app.schemas.telegram import Message, Update
from app.servicios.calidad import alertas, directorio, plan, reloj, reporte, textos
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.db import init_calidad

MENSAJE_BIENVENIDA = textos.ALCANCE
BOTONES_IMPORTACION = [
    [
        {"text": "Guardar", "callback_data": "cal:imp:ok"},
        {"text": "Cancelar", "callback_data": "cal:imp:no"},
    ]
]


# ---------------------------------------------------------------------------
# Acceso y estado de la conversación
# ---------------------------------------------------------------------------


async def _es_usuario(db: aiosqlite.Connection, telegram_id: int) -> bool:
    cur = await db.execute(
        "SELECT 1 FROM cal_usuarios WHERE telegram_id = ?", (telegram_id,)
    )
    return await cur.fetchone() is not None


async def _registrar(db: aiosqlite.Connection, msg: Message, codigo: str) -> str:
    uid = msg.from_.id if msg.from_ else msg.chat.id
    if await _es_usuario(db, uid):
        return f"{textos.ALCANCE}\n\n{textos.AYUDA}"
    esperado = calidad_settings.invite_code
    if not esperado or not hmac.compare_digest(codigo.strip(), esperado):
        return "Necesito el código de invitación: /start &lt;código&gt;."
    cur = await db.execute("SELECT COUNT(*) FROM cal_usuarios")
    fila = await cur.fetchone()
    if fila and int(fila[0]) >= calidad_settings.max_users:
        return "Se alcanzó el máximo de usuarios de este servicio."
    await db.execute(
        "INSERT INTO cal_usuarios (telegram_id, nombre) VALUES (?, ?)",
        (uid, msg.from_.nombre if msg.from_ else None),
    )
    await db.commit()
    return f"Listo, quedaste registrado.\n\n{textos.ALCANCE}\n\n{textos.AYUDA}"


async def _esperar(
    db: aiosqlite.Connection, chat_id: int, esperando: str, dato: str = ""
) -> None:
    await db.execute(
        "INSERT INTO cal_estado_chat (chat_id, esperando, dato) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET esperando=excluded.esperando, "
        "dato=excluded.dato",
        (chat_id, esperando, dato),
    )
    await db.commit()


async def _estado(db: aiosqlite.Connection, chat_id: int) -> tuple[str, str] | None:
    cur = await db.execute(
        "SELECT esperando, dato FROM cal_estado_chat WHERE chat_id = ?", (chat_id,)
    )
    fila = await cur.fetchone()
    return (str(fila["esperando"]), str(fila["dato"])) if fila else None


async def _limpiar(db: aiosqlite.Connection, chat_id: int) -> None:
    await db.execute("DELETE FROM cal_estado_chat WHERE chat_id = ?", (chat_id,))
    await db.commit()


def _comando(texto: str) -> tuple[str, str]:
    if not texto.startswith("/"):
        return "", texto
    primero, _, resto = texto.partition(" ")
    return primero.split("@")[0].lower(), resto.strip()


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


async def _importar(db: aiosqlite.Connection, msg: Message, uid: int) -> None:
    doc = msg.document
    if doc is None:
        await _esperar(db, msg.chat.id, "plan")
        await telegram.send_message(
            msg.chat.id,
            "Envíame el .xlsx del plan con las columnas: programa, código, tarea, "
            "responsable_cargo, responsable_dependencia, fecha_limite, "
            "evidencia_esperada (y, opcionales, factor_cna y eje_plan_accion).",
        )
        return
    nombre = doc.file_name or "plan.xlsx"
    if not nombre.lower().endswith(".xlsx"):
        await telegram.send_message(msg.chat.id, "El archivo debe ser un .xlsx.")
        return
    try:
        contenido = await telegram.descargar_archivo(doc.file_id)
    except Exception:
        await telegram.send_message(msg.chat.id, "No pude descargar el archivo.")
        return
    lectura = plan.leer_plan(contenido)
    if lectura.errores:
        lista = "\n".join(f"• {escape(e)}" for e in lectura.errores[:15])
        extra = len(lectura.errores) - 15
        if extra > 0:
            lista += f"\n… y {extra} más"
        await telegram.send_message(
            msg.chat.id, f"No guardé nada. Corrige el archivo:\n{lista}"
        )
        return
    resumen = await plan.resumir(db, lectura.filas)
    await _esperar(
        db,
        msg.chat.id,
        "confirmar_plan",
        json.dumps({"archivo": nombre, "filas": plan.filas_a_json(lectura.filas)}),
    )
    await telegram.send_message(
        msg.chat.id,
        textos.texto_resumen_importacion(resumen, nombre),
        botones=BOTONES_IMPORTACION,
    )


async def _confirmar_importacion(
    db: aiosqlite.Connection, chat_id: int, uid: int, aceptar: bool
) -> str:
    estado = await _estado(db, chat_id)
    if estado is None or estado[0] != "confirmar_plan":
        return "No hay una importación pendiente."
    await _limpiar(db, chat_id)
    if not aceptar:
        return "Importación cancelada. No se guardó nada."
    datos = json.loads(estado[1])
    filas = plan.filas_de_json(datos["filas"])
    resumen = await plan.resumir(db, filas)
    await plan.aplicar_importacion(
        db,
        filas,
        archivo=datos["archivo"],
        usuario_id=uid,
        creado=reloj.ahora().isoformat(),
    )
    return (
        f"Plan guardado: {len(resumen.nuevas)} nuevas, "
        f"{len(resumen.actualizadas)} actualizadas, {resumen.sin_cambios} sin cambios. "
        "El historial conserva lo que cambió."
    )


async def _cmd_plan(db: aiosqlite.Connection, chat_id: int, arg: str) -> None:
    hoy = reloj.hoy()
    if not arg:
        programas = await plan.listar_programas(db)
        if not programas:
            await telegram.send_message(
                chat_id, "Aún no hay plan cargado. Usa /importar_plan."
            )
            return
        lista = "\n".join(f"• {escape(p)}" for p in programas)
        await telegram.send_message(
            chat_id, f"Indica el programa: /plan &lt;programa&gt;\n{lista}"
        )
        return
    programa = await plan.buscar_programa(db, arg)
    if programa is None:
        await telegram.send_message(
            chat_id,
            f"No encontré el programa «{escape(arg)}». Usa /plan para ver la lista.",
        )
        return
    tareas = await plan.listar_tareas(db, programa)
    await telegram.send_message(chat_id, textos.texto_plan(programa, tareas, hoy))


async def _cmd_evidencia(
    db: aiosqlite.Connection, msg: Message, uid: int, arg: str
) -> None:
    codigo, _, resto = arg.partition(" ")
    if not codigo:
        await telegram.send_message(
            msg.chat.id, "Uso: /evidencia &lt;código&gt; [enlace]"
        )
        return
    tareas = await plan.buscar_tareas_por_codigo(db, codigo)
    if not tareas:
        await telegram.send_message(
            msg.chat.id, f"No hay una tarea con el código {escape(codigo)}."
        )
        return
    if len(tareas) > 1:
        lista = ", ".join(escape(t.programa) for t in tareas)
        await telegram.send_message(
            msg.chat.id,
            f"El código está en varios programas ({lista}); revisa el plan.",
        )
        return
    tarea = tareas[0]
    enlace = resto.strip()
    if msg.document is not None or enlace:
        await _guardar_evidencia(db, msg, uid, tarea, enlace)
        return
    await _esperar(db, msg.chat.id, f"evidencia:{tarea.id}")
    await telegram.send_message(
        msg.chat.id,
        f"Envíame el archivo o el enlace de la evidencia de {escape(tarea.codigo)}. "
        f"Se espera: {escape(tarea.evidencia_esperada)}",
    )


async def _guardar_evidencia(
    db: aiosqlite.Connection,
    msg: Message,
    uid: int,
    tarea: plan.Tarea,
    enlace: str,
) -> None:
    if msg.document is not None:
        tipo, valor = "archivo", msg.document.file_name or "archivo sin nombre"
        referencia: str | None = msg.document.file_id
    elif enlace.lower().startswith(("http://", "https://")):
        tipo, valor, referencia = "enlace", enlace, None
    else:
        await telegram.send_message(
            msg.chat.id,
            "Envía un archivo o un enlace que empiece por http:// o https://.",
        )
        return
    await plan.registrar_evidencia(
        db,
        tarea.id,
        tipo=tipo,
        valor=valor,
        referencia=referencia,
        usuario_id=uid,
        usuario_nombre=msg.from_.nombre if msg.from_ else None,
        creado=reloj.ahora().isoformat(),
    )
    await _limpiar(db, msg.chat.id)
    await telegram.send_message(
        msg.chat.id,
        f"Tarea {escape(tarea.codigo)} marcada como cumplida. "
        f"Evidencia registrada por ti el {reloj.ahora().date().isoformat()}.\n"
        f"Responsable: {textos.responsable(tarea)}",
    )


async def _cmd_alerta(db: aiosqlite.Connection, chat_id: int) -> None:
    mapa = await alertas.construir_alertas(db, reloj.hoy())
    if not mapa:
        await telegram.send_message(
            chat_id, "Aún no hay plan cargado. Usa /importar_plan."
        )
        return
    estado = "ACTIVO" if calidad_settings.alertas_activas else "DESACTIVADO"
    await telegram.send_message(
        chat_id,
        f"<b>Vista previa</b> (el envío real está {estado}; esto no se envió a nadie).",
    )
    for texto in mapa.values():
        await telegram.send_message(chat_id, texto)


async def _cmd_reporte(db: aiosqlite.Connection, chat_id: int, arg: str) -> None:
    programa = await plan.buscar_programa(db, arg) if arg else None
    if programa is None:
        await telegram.send_message(
            chat_id, "Uso: /reporte &lt;programa&gt; (mira /plan para la lista)."
        )
        return
    hoy = reloj.hoy()
    contenido = reporte.generar_reporte(
        programa, await plan.listar_tareas(db, programa), hoy
    )
    await telegram.send_document(
        chat_id,
        nombre=f"reporte-plan-{hoy.isoformat()}.xlsx",
        contenido=contenido,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        caption=f"Estado del plan de {escape(programa)}. La pestaña «fuentes» lista los registros de cada cifra.",
    )


async def _cmd_a_quien(chat_id: int, arg: str) -> None:
    tramites = directorio.cargar()
    if not arg:
        await telegram.send_message(
            chat_id, textos.texto_directorio("", [], [t.tema for t in tramites])
        )
        return
    await telegram.send_message(
        chat_id,
        textos.texto_directorio(
            arg, directorio.buscar(arg, tramites), [t.tema for t in tramites]
        ),
    )


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


async def _callback(db: aiosqlite.Connection, update: Update) -> None:
    cb = update.callback_query
    if cb is None or cb.message is None or not cb.data:
        return
    if not await _es_usuario(db, cb.from_.id):
        await telegram.responder_callback(cb.id, "Sin acceso.")
        return
    if cb.data in ("cal:imp:ok", "cal:imp:no"):
        texto = await _confirmar_importacion(
            db, cb.message.chat.id, cb.from_.id, cb.data.endswith(":ok")
        )
        await telegram.responder_callback(cb.id)
        await telegram.editar_botones(cb.message.chat.id, cb.message.message_id, None)
        await telegram.send_message(cb.message.chat.id, texto)


async def manejar_update(db: aiosqlite.Connection, update: Update) -> None:
    await init_calidad(db)
    if not await repo.marcar_update(db, update.update_id):
        return
    if update.callback_query is not None:
        await _callback(db, update)
        return
    msg = update.message
    if msg is None:
        return
    uid = msg.from_.id if msg.from_ else msg.chat.id
    cmd, arg = _comando((msg.text or msg.caption or "").strip())

    if cmd == "/start":
        await telegram.send_message(msg.chat.id, await _registrar(db, msg, arg))
        return
    if not await _es_usuario(db, uid):
        if cmd:
            await telegram.send_message(
                msg.chat.id,
                "Este servicio es solo por invitación. Envía /start &lt;código&gt;.",
            )
        return

    if cmd == "/ayuda":
        await telegram.send_message(msg.chat.id, f"{textos.ALCANCE}\n\n{textos.AYUDA}")
    elif cmd == "/importar_plan":
        await _importar(db, msg, uid)
    elif cmd == "/plan":
        await _cmd_plan(db, msg.chat.id, arg)
    elif cmd == "/evidencia":
        await _cmd_evidencia(db, msg, uid, arg)
    elif cmd == "/alerta_vista_previa":
        await _cmd_alerta(db, msg.chat.id)
    elif cmd == "/reporte":
        await _cmd_reporte(db, msg.chat.id, arg)
    elif cmd == "/a_quien":
        await _cmd_a_quien(msg.chat.id, arg)
    elif not cmd:
        await _continuar(db, msg, uid)


async def _continuar(db: aiosqlite.Connection, msg: Message, uid: int) -> None:
    """Mensaje sin comando: completa lo que el chat dejó pendiente."""
    estado = await _estado(db, msg.chat.id)
    if estado is None:
        return
    if estado[0] == "plan" and msg.document is not None:
        await _limpiar(db, msg.chat.id)
        await _importar(db, msg, uid)
    elif estado[0].startswith("evidencia:"):
        tareas = [
            t
            for t in await plan.listar_tareas(db)
            if t.id == int(estado[0].split(":")[1])
        ]
        if tareas:
            await _guardar_evidencia(db, msg, uid, tareas[0], (msg.text or "").strip())


__all__ = ["MENSAJE_BIENVENIDA", "manejar_update"]
