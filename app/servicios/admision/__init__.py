"""Servicio de admisión: asistente de documentación para admitidos.

Los documentos se procesan en memoria y se descartan; solo se guardan métricas
agregadas. Nunca se pide ni se acepta el correo ni la contraseña.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata

import aiosqlite

from app.db import repo
from app.integrations import telegram
from app.schemas.telegram import CallbackQuery, Message, Update
from app.servicios.admision import almacen, chequeo, filtro, flujo
from app.servicios.admision.config import config
from app.servicios.admision.modelo import ClaudeModelo, Modelo

logger = logging.getLogger(__name__)

PROPOSITO = (
    "Te ayudo a revisar tus documentos antes de subirlos. "
    "No reemplazo la revisión oficial ni subo nada por ti."
)
_PIE = f"\n\n<i>{html.escape(PROPOSITO)}</i>"

_MODELO: Modelo | None = None
# Solo el file_id de Telegram (nunca el contenido) mientras el estudiante elige
# el tipo de documento. Se pierde al reiniciar: se le pide reenviar.
_PENDIENTES: dict[int, tuple[str, int | None]] = {}
_MAX_PENDIENTES = 500


def usar_modelo(modelo: Modelo | None) -> None:
    global _MODELO
    _MODELO = modelo


def modelo() -> Modelo:
    """El modelo en uso; lo comparten Telegram y la web."""
    global _MODELO
    if _MODELO is None:
        _MODELO = ClaudeModelo()
    return _MODELO


async def _decir(
    chat_id: int,
    texto: str,
    botones: list[list[dict[str, str]]] | None = None,
    *,
    pie: bool = True,
) -> None:
    await telegram.send_message(chat_id, texto + (_PIE if pie else ""), botones=botones)


def _btn(texto: str, data: str) -> dict[str, str]:
    return {"text": texto, "callback_data": data}


def _normal(texto: str) -> str:
    sin = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sin if unicodedata.category(c) != "Mn")


def aviso_html() -> str:
    crudo = config.aviso_path.read_text(encoding="utf-8").strip()
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(crudo))


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


async def manejar_update(db: aiosqlite.Connection, update: Update) -> None:
    if not await repo.marcar_update(db, update.update_id):
        return
    await almacen.asegurar_tablas(db)
    if update.callback_query is not None:
        await _callback(db, update.callback_query)
        return
    msg = update.message
    if msg is None:
        return
    texto = (msg.text or "").strip()
    if texto.startswith("/start"):
        await _start(db, msg.chat.id)
    elif texto.startswith("/metricas"):
        await _metricas(db, msg)
    elif msg.document is not None or msg.photo:
        await _archivo(db, msg)
    elif texto:
        await _pregunta(db, msg.chat.id, texto)


async def _start(db: aiosqlite.Connection, chat_id: int) -> None:
    await almacen.reiniciar(db, chat_id)
    _PENDIENTES.pop(chat_id, None)
    await _decir(
        chat_id,
        aviso_html(),
        [[_btn("Acepto", "adm:acepto"), _btn("No acepto", "adm:noacepto")]],
    )


async def _callback(db: aiosqlite.Connection, cb: CallbackQuery) -> None:
    if cb.message is None or not cb.data or not cb.data.startswith("adm:"):
        return
    chat_id = cb.message.chat.id
    await telegram.responder_callback(cb.id)
    accion = cb.data.split(":")
    match accion[1:]:
        case ["acepto"]:
            await almacen.fijar(db, chat_id, "acepto", 1)
            await almacen.contar(db, "consentimientos")
            await _decir(
                chat_id,
                "Gracias. ¿Tienes menos de 18 años?",
                [[_btn("Sí, soy menor", "adm:menor:1"), _btn("No", "adm:menor:0")]],
            )
        case ["noacepto"]:
            await almacen.contar(db, "rechazos")
            await _decir(
                chat_id,
                "Entendido: no reviso documentos ni guardo nada. "
                "Si cambias de opinión, escribe /start.",
            )
        case ["menor", valor] if valor in ("0", "1"):
            if not (await almacen.estado(db, chat_id))["acepto"]:
                await _sin_aviso(chat_id)
                return
            await almacen.fijar(db, chat_id, "menor", int(valor))
            if valor == "1":
                await almacen.contar(db, "menores")
                await _decir(
                    chat_id,
                    "Antes de revisar documentos necesito la aceptación de tu "
                    "acudiente (quien tenga tu patria potestad). ¿Leyó el aviso "
                    "y acepta?",
                    [[_btn("Sí, acepta", "adm:acud:1"), _btn("No", "adm:acud:0")]],
                )
            else:
                await _listo(chat_id)
        case ["acud", valor] if valor in ("0", "1"):
            est = await almacen.estado(db, chat_id)
            if not est["acepto"] or est["menor"] != 1:
                await _sin_aviso(chat_id)
                return
            await almacen.fijar(db, chat_id, "acudiente", int(valor))
            if valor == "1":
                await _listo(chat_id)
            else:
                await _decir(
                    chat_id,
                    "Sin la aceptación de tu acudiente no puedo revisar "
                    "documentos. Puedes hacerme preguntas sobre el listado.",
                )
        case ["doc", clave]:
            await _revisar_pendiente(db, chat_id, clave)


async def _sin_aviso(chat_id: int) -> None:
    await _decir(chat_id, "Primero lee el aviso de datos: escribe /start.")


async def _listo(chat_id: int) -> None:
    await _decir(
        chat_id,
        "Listo. Pregúntame por el listado de documentos o envíame un PDF o una "
        "foto de un documento para revisarlo.",
    )


async def _puede_preguntar(db: aiosqlite.Connection, chat_id: int) -> bool:
    est = await almacen.estado(db, chat_id)
    if not est["acepto"] or est["menor"] is None:
        await _sin_aviso(chat_id)
        return False
    return True


async def _puede_revisar(db: aiosqlite.Connection, chat_id: int) -> bool:
    if not await _puede_preguntar(db, chat_id):
        return False
    est = await almacen.estado(db, chat_id)
    if est["menor"] == 1 and not est["acudiente"]:
        await _decir(
            chat_id,
            "Para revisar documentos necesito la aceptación de tu acudiente. "
            "Escribe /start para completarla.",
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Preguntas
# ---------------------------------------------------------------------------


async def _avisar_credenciales(chat_id: int) -> None:
    await _decir(
        chat_id,
        "⚠️ Escribiste un correo o una contraseña. <b>No los compartas</b>: no "
        "los pido, no los uso y no los guardo. Borra ese mensaje del chat.",
    )


async def _pregunta(db: aiosqlite.Connection, chat_id: int, texto: str) -> None:
    if filtro.filtrar(texto).credenciales:
        await _avisar_credenciales(chat_id)
        if not filtro.tiene_contenido(filtro.filtrar(texto).texto):
            await almacen.contar(db, "credenciales_bloqueadas")
            return
    if not await _puede_preguntar(db, chat_id):
        return
    resp = await flujo.responder(db, modelo(), texto)
    if resp.estado == "sin_fuentes":
        await _decir(chat_id, "No puedo consultar el listado ahora. Intenta más tarde.")
    elif resp.estado == "error":
        await _decir(chat_id, "No pude responder ahora. Intenta de nuevo en un rato.")
    elif resp.estado == "sin_respuesta":
        await _decir(
            chat_id,
            "Eso no aparece en el listado ni en la guía, así que no te lo puedo "
            f"confirmar. Consúltalo con {html.escape(config.contacto)}.",
        )
    elif resp.estado == "ok":
        citas = "; ".join(html.escape(c) for c in resp.citas)
        await _decir(chat_id, f"{html.escape(resp.texto)}\n\n<b>Fuente:</b> {citas}")


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------


def _tipo_por_texto(texto: str) -> str | None:
    norm = _normal(texto)
    if not norm.strip():
        return None
    # Gana el nombre más largo: «constancia del colegio (peama o paet)» no
    # debe quedar como «constancia del colegio».
    candidatos = [
        doc
        for doc in chequeo.cargar().documentos
        if _normal(doc.nombre) in norm or doc.clave.replace("_", " ") in norm
    ]
    if not candidatos:
        return None
    return max(candidatos, key=lambda d: len(d.nombre)).clave


async def _archivo(db: aiosqlite.Connection, msg: Message) -> None:
    chat_id = msg.chat.id
    leyenda = filtro.filtrar(msg.caption or "")
    if leyenda.credenciales:
        await almacen.contar(db, "credenciales_bloqueadas")
        await _avisar_credenciales(chat_id)
    if not await _puede_revisar(db, chat_id):
        return
    if msg.document is not None:
        file_id, tamano = msg.document.file_id, msg.document.file_size
    else:
        assert msg.photo
        mayor = msg.photo[-1]
        file_id, tamano = mayor.file_id, mayor.file_size
    if tamano is not None and tamano > config.max_bytes:
        await almacen.contar(db, "error_peso")
        await _decir(
            chat_id,
            f"El archivo pesa demasiado; el máximo es "
            f"{config.max_bytes / 1_000_000:.0f} MB.",
        )
        return
    clave = _tipo_por_texto(leyenda.texto)
    if clave is not None:
        await _revisar(db, chat_id, file_id, clave)
        return
    if len(_PENDIENTES) >= _MAX_PENDIENTES:
        _PENDIENTES.pop(next(iter(_PENDIENTES)))
    _PENDIENTES[chat_id] = (file_id, tamano)
    botones = [
        [_btn(d.nombre, f"adm:doc:{d.clave}")] for d in chequeo.cargar().documentos
    ]
    await _decir(chat_id, "¿Qué documento es?", botones)


async def _revisar_pendiente(
    db: aiosqlite.Connection, chat_id: int, clave: str
) -> None:
    pendiente = _PENDIENTES.pop(chat_id, None)
    if pendiente is None:
        await _decir(chat_id, "Ya no tengo el archivo. Envíalo de nuevo, por favor.")
        return
    if not await _puede_revisar(db, chat_id):
        return
    await _revisar(db, chat_id, pendiente[0], clave)


async def _revisar(
    db: aiosqlite.Connection, chat_id: int, file_id: str, clave: str
) -> None:
    if chequeo.cargar().buscar(clave) is None:
        await _decir(chat_id, "No conozco ese tipo de documento.")
        return
    try:
        datos = await telegram.descargar_archivo(file_id, max_bytes=config.max_bytes)
    except Exception:
        logger.warning("No se pudo descargar el archivo")
        await _decir(chat_id, "No pude descargar el archivo. Envíalo de nuevo.")
        return
    resultado = await flujo.revisar(db, modelo(), datos, clave)
    del datos  # los bytes viven solo en memoria durante esta revisión
    if resultado.estado == "problemas":
        lineas = "\n".join(f"• {html.escape(p)}" for p in resultado.problemas)
        await _decir(
            chat_id, f"No pude revisar el archivo:\n{lineas}\nCorrígelo y reenvíalo."
        )
    elif resultado.estado == "sin_fuentes":
        await _decir(chat_id, "No puedo revisar documentos ahora. Intenta más tarde.")
    elif resultado.estado == "error":
        await _decir(chat_id, "No pude revisar el documento ahora. Intenta de nuevo.")
    elif resultado.estado == "ok":
        await _decir(chat_id, _informe(resultado))


def _informe(resultado: flujo.Revision) -> str:
    partes = [f"<b>{html.escape(resultado.nombre)}</b>"]
    if resultado.bien:
        partes.append(
            "✅ Bien:\n"
            + "\n".join(f"• {html.escape(i.punto)}" for i in resultado.bien)
        )
    if resultado.corregir:
        partes.append(
            "✏️ Por corregir:\n"
            + "\n".join(
                f"• {html.escape(i.punto)}: {html.escape(i.detalle)}"
                for i in resultado.corregir
            )
        )
    else:
        partes.append("No veo nada por corregir en estos puntos.")
    partes.append(flujo.AVISO_REVISION)
    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


async def _metricas(db: aiosqlite.Connection, msg: Message) -> None:
    usuario = msg.from_.id if msg.from_ else None
    if usuario is None or usuario not in config.admins:
        await _decir(msg.chat.id, "No tienes permiso para ver las métricas.")
        return
    datos = await almacen.totales(db)
    if not datos:
        await _decir(msg.chat.id, "Aún no hay métricas.")
        return
    lineas = "\n".join(f"{html.escape(k)}: {v}" for k, v in datos.items())
    await _decir(msg.chat.id, f"<b>Métricas (acumuladas)</b>\n{lineas}")


__all__ = ["PROPOSITO", "manejar_update", "modelo", "usar_modelo"]
