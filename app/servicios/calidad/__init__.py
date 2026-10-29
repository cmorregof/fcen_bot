"""Servicio de calidad: seguimiento del plan de mejoramiento y acreditación."""

from __future__ import annotations

import hmac
import json
import re
from html import escape

import aiosqlite

from app.db import repo
from app.integrations import telegram
from app.schemas.telegram import Message, Update
from app.servicios.calidad import (
    alertas,
    directorio,
    plan,
    plantilla,
    reloj,
    reporte,
    textos,
)
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
            "Envíame el .xlsx del plan de mejoramiento con la plantilla institucional "
            "(hojas «1. Formulación», «2. Plan de Mejora», «3. Cronograma 20XX» y "
            "«4. Evaluación»).",
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
    lectura = plantilla.leer_plantilla(contenido)
    if lectura.errores or lectura.plan is None:
        lista = "\n".join(f"• {escape(e)}" for e in lectura.errores[:15])
        await telegram.send_message(
            msg.chat.id, f"No guardé nada. No pude leer el plan:\n{lista}"
        )
        return
    resumen = await plan.resumir(db, lectura.plan)
    await _esperar(
        db,
        msg.chat.id,
        "confirmar_plan",
        json.dumps({"archivo": nombre, "plan": lectura.plan.model_dump_json()}),
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
    leido = plantilla.Plan.model_validate_json(datos["plan"])
    resumen = await plan.aplicar_importacion(
        db,
        leido,
        archivo=datos["archivo"],
        usuario_id=uid,
        creado=reloj.ahora().isoformat(),
    )
    return (
        f"Plan de {escape(resumen.programa)} guardado: {len(resumen.nuevas)} acciones "
        f"nuevas, {len(resumen.actualizadas)} actualizadas, {resumen.sin_cambios} sin "
        f"cambios; {resumen.cortes_nuevos} cortes nuevos. El historial conserva lo "
        "que cambió. Míralo con /plan."
    )


async def _programa_o_lista(
    db: aiosqlite.Connection, chat_id: int, arg: str, uso: str
) -> str | None:
    programas = await plan.listar_programas(db)
    if not programas:
        await telegram.send_message(
            chat_id, "Aún no hay plan cargado. Usa /importar_plan."
        )
        return None
    if not arg and len(programas) == 1:
        return programas[0]
    programa = await plan.buscar_programa(db, arg) if arg else None
    if programa is None:
        lista = "\n".join(f"• {escape(p)}" for p in programas)
        inicio = f"No encontré el programa «{escape(arg)}». " if arg else ""
        await telegram.send_message(chat_id, f"{inicio}Uso: {uso}\n{lista}")
    return programa


async def _cmd_plan(db: aiosqlite.Connection, chat_id: int, arg: str) -> None:
    programa = await _programa_o_lista(db, chat_id, arg, "/plan &lt;programa&gt;")
    if programa is None:
        return
    guardado = await plan.cargar_plan(db, programa)
    if guardado is not None:
        await telegram.send_message(chat_id, textos.texto_plan(guardado, reloj.hoy()))


_RE_CODIGO = re.compile(r"^\d+(?:\.\d+)*\.?$")


async def _cmd_evidencia(
    db: aiosqlite.Connection, msg: Message, uid: int, arg: str
) -> None:
    uso = "/evidencia &lt;programa&gt; &lt;código de acción&gt; [enlace]"
    palabras = arg.split()
    i = next((n for n, p in enumerate(palabras) if _RE_CODIGO.match(p)), None)
    if i is None:
        await telegram.send_message(msg.chat.id, f"Uso: {uso}")
        return
    programa = await _programa_o_lista(db, msg.chat.id, " ".join(palabras[:i]), uso)
    if programa is None:
        return
    codigo = palabras[i].rstrip(".")
    guardado = await plan.cargar_plan(db, programa)
    accion = guardado.accion(codigo) if guardado else None
    if guardado is None or accion is None:
        await telegram.send_message(
            msg.chat.id,
            f"No hay una acción {escape(codigo)} en el plan de {escape(programa)}.",
        )
        return
    enlace = " ".join(palabras[i + 1 :]).strip()
    if msg.document is not None or enlace:
        await _guardar_evidencia(db, msg, uid, guardado, accion, enlace)
        return
    await _esperar(
        db,
        msg.chat.id,
        "evidencia",
        json.dumps({"programa": programa, "codigo": codigo}),
    )
    await telegram.send_message(
        msg.chat.id,
        f"Envíame el archivo o el enlace del soporte de la acción {escape(codigo)}. "
        f"Indicador: {escape(textos.corto(accion.indicador, 200) or 'sin indicador en el plan')}",
    )


async def _guardar_evidencia(
    db: aiosqlite.Connection,
    msg: Message,
    uid: int,
    guardado: plan.PlanGuardado,
    accion: plantilla.Accion,
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
    await plan.registrar_soporte(
        db,
        guardado.ids[accion.codigo],
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
        f"Soporte de la acción {escape(accion.codigo)} ({escape(guardado.programa)}) "
        f"registrado por ti el {reloj.ahora().date().isoformat()}. Queda por revisar: "
        "el % de avance solo cambia cuando se actualiza el plan.",
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
    programa = await _programa_o_lista(db, chat_id, arg, "/reporte &lt;programa&gt;")
    guardado = await plan.cargar_plan(db, programa) if programa else None
    if guardado is None:
        return
    hoy = reloj.hoy()
    await telegram.send_document(
        chat_id,
        nombre=f"reporte-plan-{hoy.isoformat()}.xlsx",
        contenido=reporte.generar_reporte(guardado, hoy),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        caption=f"Estado del plan de {escape(guardado.programa)}. La pestaña «fuentes» lista las acciones de cada cifra y su fila en el plan.",
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
    elif estado[0] == "evidencia":
        datos = json.loads(estado[1])
        guardado = await plan.cargar_plan(db, datos["programa"])
        accion = guardado.accion(datos["codigo"]) if guardado else None
        if guardado is not None and accion is not None:
            await _guardar_evidencia(
                db, msg, uid, guardado, accion, (msg.text or "").strip()
            )


__all__ = ["MENSAJE_BIENVENIDA", "manejar_update"]
