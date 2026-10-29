"""Flujo de Telegram: registro, caso abierto, procesar, ficha y recomendaciones.

Orden de precedencia para un mensaje: comando con "/", respuesta al pedido
de una nota o de un concepto del comité, respuesta a una ficha (corrección) y,
por último, contenido del caso abierto (texto o pantallazos). El modelo solo se llama al procesar o corregir.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import aiosqlite

from app.core.config import settings
from app.core.programas import DIRECCIONES, PROGRAMAS, normalizar, programas_de
from app.db import repo
from app.integrations import telegram
from app.schemas.caso import Caso, EstadoCaso, Sentido
from app.schemas.telegram import CallbackQuery, Document, Message, Update
from app.services import borrador, extraccion, ficha, formatos, reglas

logger = logging.getLogger(__name__)

_RE_CASO = re.compile(r"Caso #(\d+)")
_RE_NOTA = re.compile(r"Nota del comité · caso #(\d+)")
_RE_CONCEPTO = re.compile(r"Concepto de (.+?) · caso #(\d+)")
_OTRO_MIEMBRO = "otro miembro"
_RE_TRATAMIENTO = re.compile(r"^(el profesor|la profesora)\s+", re.IGNORECASE)
# Palabras sueltas que equivalen a /listo cuando hay un caso abierto.
_PALABRAS_PROCESAR = {
    "procesar",
    "procesa",
    "listo",
    "lista",
    "ya",
    "eso es todo",
    "fin",
}
_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

AYUDA = """<b>Cómo funciona</b>
1. Pega el correo del estudiante (texto) y envía los pantallazos del SIA y de la solicitud.
2. Toca <b>Procesar</b> (o escribe /listo). Te respondo con la ficha del caso y las alertas.
3. Si un dato está mal, <b>responde a la ficha</b> con la corrección.
4. Con <b>Concepto</b> registras lo que opinó cada profesor del comité; va al acta, no al oficio.
5. Después del comité, marca cada caso: Recomendar aprobar, Recomendar no aprobar o Pendiente.
6. Cada día hábil a las 4:50 p. m. te llegan, por programa, el oficio y el acta (.docx y PDF). También con /acta.

<b>Comandos</b>
/nuevo — empieza otro caso
/listo — procesa el caso abierto
/cancelar — descarta el caso abierto
/casos — últimos casos
/caso N — vuelve a mostrar la ficha del caso N
/acta — oficio y acta ahora
/cerrar_acta — saca del borrador los casos ya tratados por el comité
/costo — consumo del modelo este mes"""


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


async def manejar_update(db: aiosqlite.Connection, update: Update) -> None:
    if not await repo.marcar_update(db, update.update_id):
        return
    if update.callback_query is not None:
        await _callback(db, update.callback_query)
        return
    msg = update.message
    if msg is None or msg.from_ is None or msg.chat.type != "private":
        return
    async with _locks[msg.chat.id]:
        await _mensaje(db, msg)


async def _mensaje(db: aiosqlite.Connection, msg: Message) -> None:
    assert msg.from_ is not None
    chat_id = msg.chat.id
    texto = (msg.text or "").strip()
    usuario = await repo.get_usuario(db, msg.from_.id)

    if usuario is None:
        await _registro(db, msg, texto)
        return
    if usuario.direccion is None:
        await _pedir_direccion(chat_id)
        return

    if texto.startswith("/"):
        await _comando(db, msg, usuario, texto)
        return
    if _normalizar(texto) in _PALABRAS_PROCESAR and not msg.reply_to_message:
        estado = await repo.get_estado(db, chat_id)
        if estado.caso_abierto_id is not None:
            await _procesar(db, chat_id, usuario, estado.caso_abierto_id)
            return

    if msg.reply_to_message and msg.reply_to_message.text and texto:
        respondido = msg.reply_to_message.text
        # Respuesta al mensaje que pide la nota del comité.
        m = _RE_NOTA.search(respondido)
        if m:
            caso = await _caso_propio(db, int(m.group(1)), usuario)
            if caso:
                await repo.set_nota(db, caso.id, texto[:1500])
                await telegram.send_message(
                    chat_id, f"Nota guardada en el caso #{caso.id}."
                )
            return
        # Respuesta al mensaje que pide el concepto de un miembro del comité.
        m = _RE_CONCEPTO.search(respondido)
        if m:
            await _guardar_concepto(
                db, chat_id, usuario, m.group(1), int(m.group(2)), texto
            )
            return
        # Respuesta a una ficha: corrección del caso.
        m = _RE_CASO.search(respondido)
        if m:
            await _corregir(db, chat_id, usuario, int(m.group(1)), texto)
            return

    await _agregar_al_caso(db, msg, usuario)


async def _guardar_concepto(
    db: aiosqlite.Connection,
    chat_id: int,
    usuario: repo.Usuario,
    miembro: str,
    caso_id: int,
    texto: str,
) -> None:
    caso = await _caso_propio(db, caso_id, usuario)
    if caso is None:
        return
    tratamiento: str | None = None
    if miembro == _OTRO_MIEMBRO:
        # Primera línea: el nombre; el resto, el concepto.
        nombre, _, resto = texto.partition("\n")
        nombre = nombre.strip().rstrip(":").strip()
        m = _RE_TRATAMIENTO.match(nombre)
        if m:
            tratamiento = m.group(1).capitalize()
            nombre = nombre[m.end() :].strip()
        texto = resto.strip()
        if not nombre or not texto:
            await telegram.send_message(
                chat_id,
                "Escribe el nombre en la primera línea y el concepto debajo. "
                "Vuelve a tocar «Concepto» para intentarlo otra vez.",
            )
            return
        miembro = nombre
    else:
        programa = PROGRAMAS.get(caso.programa or "")
        for m_ in programa.miembros if programa else ():
            if m_.nombre == miembro:
                tratamiento = m_.tratamiento
    if _normalizar(texto) == "borrar":
        borrado = await repo.borrar_concepto(db, caso.id, miembro)
        await telegram.send_message(
            chat_id,
            f"Borré el concepto de {escape(miembro)} en el caso #{caso.id}."
            if borrado
            else f"El caso #{caso.id} no tenía concepto de {escape(miembro)}.",
        )
        return
    await repo.guardar_concepto(
        db, caso.id, miembro=miembro, tratamiento=tratamiento, texto=texto[:4000]
    )
    await telegram.send_message(
        chat_id,
        f"Concepto de {escape(miembro)} guardado en el caso #{caso.id}. "
        "Va al acta, no al oficio.",
    )


def _normalizar(texto: str) -> str:
    return normalizar(texto).strip(" .!¡?¿")


async def _registro(db: aiosqlite.Connection, msg: Message, texto: str) -> None:
    assert msg.from_ is not None
    partes = texto.split(maxsplit=1)
    codigo = partes[1].strip() if len(partes) == 2 and partes[0] == "/start" else ""
    if (
        settings.invite_code
        and codigo == settings.invite_code
        and await repo.contar_usuarios(db) < settings.max_users
    ):
        await repo.registrar_usuario(db, msg.from_.id, msg.from_.nombre)
        await telegram.send_message(msg.chat.id, "Bienvenida. Quedaste registrada.")
        await _pedir_direccion(msg.chat.id)
        return
    await telegram.send_message(
        msg.chat.id,
        "Este bot es de uso interno de la Facultad de Ciencias Exactas y Naturales.",
    )


async def _pedir_direccion(chat_id: int) -> None:
    botones = [
        [{"text": d.nombre, "callback_data": f"dir:{d.clave}"}]
        for d in DIRECCIONES.values()
    ]
    await telegram.send_message(
        chat_id, "¿De qué dirección de área curricular eres?", botones=botones
    )


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


async def _comando(
    db: aiosqlite.Connection, msg: Message, usuario: repo.Usuario, texto: str
) -> None:
    chat_id = msg.chat.id
    nombre, _, arg = texto.partition(" ")
    nombre = nombre.split("@")[0].lower()
    estado = await repo.get_estado(db, chat_id)
    assert usuario.direccion is not None

    if nombre in ("/start", "/ayuda", "/help"):
        await telegram.send_message(chat_id, AYUDA)
    elif nombre == "/nuevo":
        await repo.set_estado(db, chat_id, caso_abierto_id=None)
        await telegram.send_message(
            chat_id, "Listo. Pega el correo del siguiente caso."
        )
    elif nombre == "/listo":
        if estado.caso_abierto_id is None:
            await telegram.send_message(
                chat_id, "No hay un caso abierto. Pega un correo para empezar."
            )
        else:
            await _procesar(db, chat_id, usuario, estado.caso_abierto_id)
    elif nombre == "/cancelar":
        if estado.caso_abierto_id is not None:
            await repo.set_estado_caso(
                db, estado.caso_abierto_id, EstadoCaso.DESCARTADO
            )
            await repo.set_estado(db, chat_id, caso_abierto_id=None)
            await telegram.send_message(
                chat_id, f"Descarté el caso #{estado.caso_abierto_id}."
            )
        else:
            await telegram.send_message(chat_id, "No hay un caso abierto.")
    elif nombre == "/casos":
        await _listar(db, chat_id, usuario.direccion)
    elif nombre == "/caso":
        if not arg.strip().lstrip("#").isdigit():
            await telegram.send_message(chat_id, "Uso: /caso 12")
            return
        caso = await _caso_propio(db, int(arg.strip().lstrip("#")), usuario)
        if caso is None:
            await telegram.send_message(chat_id, "No encontré ese caso.")
        else:
            await _enviar_ficha(chat_id, caso)
    elif nombre == "/acta":
        await telegram.send_message(chat_id, "Armando los borradores…")
        borradores, sin_programa = await borrador.armar_borradores(
            db,
            direccion=usuario.direccion,
            elaboro=usuario.nombre,
            solo_con_cambios=False,
        )
        if not borradores:
            await telegram.send_message(chat_id, "No hay casos procesados en curso.")
        await borrador.enviar_borradores(chat_id, borradores)
        if sin_programa:
            await telegram.send_message(
                chat_id,
                "Sin programa asignado (no entraron): "
                + ", ".join(f"#{i}" for i in sin_programa),
            )
    elif nombre == "/cerrar_acta":
        await _ofrecer_cierre(db, chat_id, usuario.direccion)
    elif nombre == "/costo":
        await _costo(db, chat_id)
    else:
        await telegram.send_message(chat_id, "No conozco ese comando. Escribe /ayuda.")


async def _listar(db: aiosqlite.Connection, chat_id: int, direccion: str) -> None:
    casos = await repo.casos_recientes(db, direccion=direccion)
    if not casos:
        await telegram.send_message(chat_id, "Todavía no hay casos.")
        return
    lineas = ["<b>Últimos casos</b>"]
    for c in casos:
        nombre = c.extraccion.nombre_estudiante if c.extraccion else None
        programa = PROGRAMAS[c.programa].nombre if c.programa in PROGRAMAS else "—"
        lineas.append(
            f"#{c.id} · {escape(nombre or 'sin procesar')} · {escape(programa)} · "
            f"{c.estado.value} · {c.sentido.value}"
        )
    await telegram.send_message(chat_id, "\n".join(lineas))


async def _costo(db: aiosqlite.Connection, chat_id: int) -> None:
    mes = datetime.now(UTC).strftime("%Y-%m")
    uso = await repo.uso_del_mes(db, mes)
    usd = (
        uso.input_tokens * settings.precio_input_mtok
        + uso.output_tokens * settings.precio_output_mtok
    ) / 1_000_000
    por_caso = usd / uso.casos if uso.casos else 0.0

    def miles(n: int) -> str:
        return f"{n:,}".replace(",", ".")

    await telegram.send_message(
        chat_id,
        f"<b>Consumo de {mes}</b>\n"
        f"{uso.casos} casos, {uso.llamadas} llamadas al modelo\n"
        f"{miles(uso.input_tokens)} tokens de entrada, "
        f"{miles(uso.output_tokens)} de salida\n"
        f"≈ {usd:.2f} USD ({por_caso:.3f} USD por caso)",
    )


async def _ofrecer_cierre(
    db: aiosqlite.Connection, chat_id: int, direccion: str
) -> None:
    casos = await repo.casos_listos(db, direccion=direccion)
    con_sentido = [c for c in casos if c.sentido != Sentido.PENDIENTE and c.programa]
    if not con_sentido:
        await telegram.send_message(
            chat_id, "No hay casos con recomendación del comité para cerrar."
        )
        return
    programas = sorted({c.programa for c in con_sentido if c.programa})
    botones = [
        [{"text": f"Cerrar {PROGRAMAS[p].nombre}", "callback_data": f"cerrar:{p}"}]
        for p in programas
    ]
    await telegram.send_message(
        chat_id,
        "Cerrar saca del borrador los casos que ya tienen recomendación del comité "
        "(recomendar aprobar o no aprobar). Los pendientes siguen en curso.",
        botones=botones,
    )


# ---------------------------------------------------------------------------
# Caso abierto
# ---------------------------------------------------------------------------


async def _agregar_al_caso(
    db: aiosqlite.Connection, msg: Message, usuario: repo.Usuario
) -> None:
    chat_id = msg.chat.id
    assert usuario.direccion is not None
    estado = await repo.get_estado(db, chat_id)
    caso_id = estado.caso_abierto_id
    nuevo = False
    if caso_id is not None:
        caso = await repo.get_caso(db, caso_id)
        if caso is None or caso.estado != EstadoCaso.ABIERTO:
            caso_id = None
    if caso_id is None:
        caso_id = await repo.crear_caso(
            db,
            chat_id=chat_id,
            user_id=usuario.telegram_id,
            direccion=usuario.direccion,
        )
        await repo.set_estado(db, chat_id, caso_abierto_id=caso_id)
        nuevo = True

    texto = (msg.text or msg.caption or "").strip()
    if texto:
        await repo.agregar_texto(db, caso_id, texto)

    if msg.photo:
        foto = max(msg.photo, key=lambda p: p.width * p.height)
        await _guardar_imagen(db, caso_id, foto.file_id, foto.file_unique_id, ".jpg")
    elif msg.document:
        doc = msg.document
        mime = doc.mime_type or ""
        if mime.startswith("image/"):
            ext = "." + mime.split("/")[-1].replace("jpeg", "jpg")
            await _guardar_imagen(db, caso_id, doc.file_id, doc.file_unique_id, ext)
        else:
            await _documento(db, chat_id, caso_id, doc)

    if nuevo:
        await telegram.send_message(
            chat_id,
            f"Abrí el caso #{caso_id}. Sigue pegando el correo y los pantallazos; "
            "cuando termines, toca Procesar.",
            botones=[
                [
                    {
                        "text": f"▶️ Procesar caso #{caso_id}",
                        "callback_data": f"proc:{caso_id}",
                    }
                ]
            ],
        )


async def _documento(
    db: aiosqlite.Connection, chat_id: int, caso_id: int, doc: Document
) -> None:
    """Un formato de solicitud se lee; los demás soportes solo se registran por
    nombre: no se guardan ni se envían al modelo."""
    nombre = doc.file_name or "archivo"
    extension = Path(nombre).suffix.lower()
    unico = doc.file_unique_id
    if extension in formatos.EXTENSIONES and (doc.file_size or 0) <= formatos.MAX_BYTES:
        datos = await telegram.descargar_archivo(doc.file_id)
        texto = await formatos.texto_de_archivo(datos, extension)
        if formatos.es_formato(texto):
            if await repo.agregar_archivo(
                db,
                caso_id,
                tipo="formato",
                ruta=None,
                nombre=nombre,
                file_unique_id=unico,
            ):
                await repo.agregar_texto(
                    db, caso_id, f"--- Formato adjunto: {nombre} ---\n{texto}"
                )
                await telegram.send_message(
                    chat_id, f"Leí «{escape(nombre)}» como formato de solicitud."
                )
            return
        if extension == ".pdf" and not texto.strip():
            # Escaneado: no se puede saber si es el formato o un soporte.
            carpeta = settings.media_dir / str(caso_id)
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta = carpeta / f"_pendiente_{unico}.pdf"
            ruta.write_bytes(datos)
            if await repo.agregar_archivo(
                db,
                caso_id,
                tipo="pendiente",
                ruta=str(ruta),
                nombre=nombre,
                file_unique_id=unico,
            ):
                await telegram.send_message(
                    chat_id,
                    f"«{escape(nombre)}» es un PDF escaneado. ¿Es el formato de "
                    "solicitud del estudiante?",
                    botones=[
                        [
                            {
                                "text": "Sí, léelo",
                                "callback_data": f"f:{caso_id}:{unico}:si",
                            },
                            {
                                "text": "No, es un soporte",
                                "callback_data": f"f:{caso_id}:{unico}:no",
                            },
                        ]
                    ],
                )
            return
    await repo.agregar_archivo(
        db, caso_id, tipo="anexo", ruta=None, nombre=nombre, file_unique_id=unico
    )


async def _guardar_imagen(
    db: aiosqlite.Connection, caso_id: int, file_id: str, unique: str, ext: str
) -> None:
    carpeta = settings.media_dir / str(caso_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{unique}{ext}"
    if not ruta.exists():
        ruta.write_bytes(await telegram.descargar_archivo(file_id))
    await repo.agregar_archivo(
        db, caso_id, tipo="imagen", ruta=str(ruta), nombre=None, file_unique_id=unique
    )


async def _procesar(
    db: aiosqlite.Connection, chat_id: int, usuario: repo.Usuario, caso_id: int
) -> None:
    caso = await _caso_propio(db, caso_id, usuario)
    if caso is None:
        await telegram.send_message(chat_id, "No encontré ese caso.")
        return
    # PROCESANDO se acepta: si el proceso anterior se cayó a mitad de camino,
    # el caso no puede quedar bloqueado. El lock por chat evita dobles llamadas.
    if caso.estado not in (EstadoCaso.ABIERTO, EstadoCaso.ERROR, EstadoCaso.PROCESANDO):
        await _enviar_ficha(chat_id, caso)
        return
    if not caso.texto.strip() and not caso.imagenes:
        await telegram.send_message(chat_id, f"El caso #{caso.id} está vacío.")
        return
    await repo.set_estado_caso(db, caso.id, EstadoCaso.PROCESANDO)
    await telegram.send_message(chat_id, f"Leyendo el caso #{caso.id}…")
    try:
        salida = await extraccion.extraer_caso(db, caso)
    except Exception as exc:
        logger.exception("Falló la extracción del caso %s", caso.id)
        salida = extraccion.SalidaExtraccion(None, None, f"error inesperado ({exc})")
    if salida.extraccion is None:
        await repo.set_estado_caso(db, caso.id, EstadoCaso.ABIERTO, error=salida.error)
        await telegram.send_message(
            chat_id,
            f"No pude procesar el caso #{caso.id}: {escape(salida.error or '')}\n"
            "El caso sigue abierto; puedes agregar algo y volver a intentar con /listo.",
        )
        return
    await repo.guardar_extraccion(
        db,
        caso.id,
        salida.extraccion,
        salida.programa.clave if salida.programa else None,
    )
    estado = await repo.get_estado(db, chat_id)
    if estado.caso_abierto_id == caso.id:
        await repo.set_estado(db, chat_id, caso_abierto_id=None)
    actualizado = await repo.get_caso(db, caso.id)
    assert actualizado is not None
    await _enviar_ficha(chat_id, actualizado)


async def _corregir(
    db: aiosqlite.Connection,
    chat_id: int,
    usuario: repo.Usuario,
    caso_id: int,
    texto: str,
) -> None:
    caso = await _caso_propio(db, caso_id, usuario)
    if caso is None or caso.extraccion is None:
        await telegram.send_message(chat_id, "No encontré ese caso procesado.")
        return
    if caso.estado != EstadoCaso.LISTO:
        await telegram.send_message(
            chat_id, f"El caso #{caso.id} ya está {caso.estado.value}; no lo modifico."
        )
        return
    await telegram.send_message(chat_id, f"Corrigiendo el caso #{caso.id}…")
    salida = await extraccion.corregir_caso(db, caso, texto)
    if salida.extraccion is None:
        await telegram.send_message(
            chat_id, f"No pude aplicar la corrección: {escape(salida.error or '')}"
        )
        return
    programa = salida.programa.clave if salida.programa else caso.programa
    await repo.actualizar_extraccion(db, caso.id, salida.extraccion, programa)
    actualizado = await repo.get_caso(db, caso.id)
    assert actualizado is not None
    await _enviar_ficha(chat_id, actualizado)


async def _enviar_ficha(chat_id: int, caso: Caso) -> None:
    if caso.extraccion is None:
        await telegram.send_message(
            chat_id, f"Caso #{caso.id}: {caso.estado.value}, todavía sin procesar."
        )
        return
    programa = PROGRAMAS.get(caso.programa or "")
    analisis = reglas.analizar(
        caso.extraccion,
        programa,
        periodo_inicio=settings.periodo_inicio,
        hay_imagenes=bool(caso.imagenes),
    )
    await telegram.send_message(
        chat_id, ficha.ficha(caso, analisis), botones=ficha.botones_ficha(caso.id)
    )
    if programa is None:
        botones = [
            [{"text": p.nombre, "callback_data": f"p:{caso.id}:{p.clave}"}]
            for p in programas_de(caso.direccion)
        ]
        await telegram.send_message(
            chat_id,
            f"No reconocí el programa del caso #{caso.id}. ¿A cuál pertenece?",
            botones=botones,
        )


async def _caso_propio(
    db: aiosqlite.Connection, caso_id: int, usuario: repo.Usuario
) -> Caso | None:
    caso = await repo.get_caso(db, caso_id)
    if caso is None or caso.direccion != usuario.direccion:
        return None
    return caso


# ---------------------------------------------------------------------------
# Botones
# ---------------------------------------------------------------------------


async def _callback(db: aiosqlite.Connection, cq: CallbackQuery) -> None:
    usuario = await repo.get_usuario(db, cq.from_.id)
    data = cq.data or ""
    chat_id = cq.message.chat.id if cq.message else cq.from_.id
    if usuario is None:
        await telegram.responder_callback(cq.id, "No estás registrada.")
        return

    if data.startswith("dir:"):
        clave = data.split(":", 1)[1]
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        if usuario.direccion is not None:
            await telegram.responder_callback(cq.id, "Tu dirección ya está asignada.")
            return
        if clave in DIRECCIONES:
            await repo.asignar_direccion(db, usuario.telegram_id, clave)
            await telegram.responder_callback(cq.id, "Guardado")
            await telegram.send_message(
                chat_id, f"Quedaste en {DIRECCIONES[clave].nombre}.\n\n{AYUDA}"
            )
        return
    if usuario.direccion is None:
        await telegram.responder_callback(cq.id)
        await _pedir_direccion(chat_id)
        return

    partes = data.split(":")
    try:
        caso_id = int(partes[1]) if len(partes) > 1 and partes[0] != "cerrar" else None
    except ValueError:
        caso_id = None

    if partes[0] == "proc" and caso_id:
        await telegram.responder_callback(cq.id)
        async with _locks[chat_id]:
            await _procesar(db, chat_id, usuario, caso_id)
        return

    if partes[0] == "cerrar" and len(partes) == 2:
        clave = partes[1]
        casos = await repo.casos_listos(db, direccion=usuario.direccion)
        ids = [
            c.id
            for c in casos
            if c.programa == clave and c.sentido != Sentido.PENDIENTE
        ]
        await repo.cerrar_casos(db, ids)
        await telegram.responder_callback(cq.id, f"{len(ids)} casos cerrados")
        await telegram.send_message(
            chat_id,
            f"Cerré {len(ids)} caso(s) de {PROGRAMAS[clave].nombre}: "
            + ", ".join(f"#{i}" for i in ids),
        )
        return

    if caso_id is None:
        await telegram.responder_callback(cq.id)
        return
    caso = await _caso_propio(db, caso_id, usuario)
    if caso is None:
        await telegram.responder_callback(cq.id, "No encontré ese caso.")
        return

    if (
        partes[0] == "s"
        and len(partes) == 3
        and partes[2] in Sentido._value2member_map_
    ):
        sentido = Sentido(partes[2])
        await repo.set_sentido(db, caso.id, sentido)
        etiqueta = {
            "aprobar": "se recomienda APROBAR",
            "no_aprobar": "se recomienda NO APROBAR",
            "pendiente": "pendiente",
        }
        await telegram.responder_callback(
            cq.id, f"Caso #{caso.id}: {etiqueta[sentido.value]}"
        )
    elif partes[0] == "n":
        await telegram.responder_callback(cq.id)
        await telegram.send_message(
            chat_id,
            f"Nota del comité · caso #{caso.id}\nResponde a este mensaje con la nota.",
            forzar_respuesta=True,
        )
    elif partes[0] == "c":
        await telegram.responder_callback(cq.id)
        programa = PROGRAMAS.get(caso.programa or "")
        filas = [
            [{"text": m.nombre, "callback_data": f"k:{caso.id}:{i}"}]
            for i, m in enumerate(programa.miembros if programa else ())
        ]
        filas.append([{"text": "Otro miembro", "callback_data": f"k:{caso.id}:x"}])
        await telegram.send_message(
            chat_id, f"¿De quién es el concepto del caso #{caso.id}?", botones=filas
        )
    elif partes[0] == "k" and len(partes) == 3:
        await telegram.responder_callback(cq.id)
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        programa = PROGRAMAS.get(caso.programa or "")
        miembros = programa.miembros if programa else ()
        if partes[2].isdigit() and int(partes[2]) < len(miembros):
            nombre = miembros[int(partes[2])].nombre
            await telegram.send_message(
                chat_id,
                f"Concepto de {nombre} · caso #{caso.id}\nResponde a este mensaje "
                "con el concepto, tal como lo envió (o «borrar» para quitarlo).",
                forzar_respuesta=True,
            )
        else:
            await telegram.send_message(
                chat_id,
                f"Concepto de {_OTRO_MIEMBRO} · caso #{caso.id}\nResponde a este "
                "mensaje con el nombre en la primera línea (p. ej. «La profesora "
                "Ana Pérez») y el concepto debajo.",
                forzar_respuesta=True,
            )
    elif partes[0] == "f" and len(partes) == 4:
        await telegram.responder_callback(cq.id)
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        unico = partes[2]
        archivo = await repo.get_archivo(db, caso.id, unico)
        if archivo is None or archivo[0] != "pendiente" or not archivo[1]:
            return
        pdf = Path(archivo[1])
        if partes[3] == "si" and pdf.exists():
            paginas = await formatos.paginas_pdf(pdf, pdf.parent, f"formato_{unico}_")
            for i, pagina in enumerate(paginas, 1):
                await repo.agregar_archivo(
                    db,
                    caso.id,
                    tipo="imagen",
                    ruta=str(pagina),
                    nombre=None,
                    file_unique_id=f"{unico}_p{i}",
                )
            await repo.set_tipo_archivo(db, caso.id, unico, tipo="formato", ruta=None)
            mensaje = (
                f"Agregué {len(paginas)} página(s) del formato al caso #{caso.id}."
                if paginas
                else "No pude convertir el PDF; envía fotos o pantallazos del formato."
            )
        else:
            await repo.set_tipo_archivo(db, caso.id, unico, tipo="anexo", ruta=None)
            mensaje = f"Queda como soporte del caso #{caso.id}; no se envía al modelo."
        pdf.unlink(missing_ok=True)
        await telegram.send_message(chat_id, mensaje)
    elif partes[0] == "d":
        await repo.set_estado_caso(db, caso.id, EstadoCaso.DESCARTADO)
        await telegram.responder_callback(cq.id, f"Caso #{caso.id} descartado")
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
    elif partes[0] == "p" and len(partes) == 3 and partes[2] in PROGRAMAS:
        if PROGRAMAS[partes[2]].direccion != usuario.direccion:
            await telegram.responder_callback(
                cq.id, "Ese programa no es de tu dirección."
            )
            return
        await repo.set_programa(db, caso.id, partes[2])
        await telegram.responder_callback(cq.id, PROGRAMAS[partes[2]].nombre)
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
    else:
        await telegram.responder_callback(cq.id)
