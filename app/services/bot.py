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

from app.core.conexion import Conexion
from app.core.config import settings
from app.core.programas import (
    DIRECCIONES,
    PROGRAMAS,
    Programa,
    comite_de,
    integrantes_con_nombre,
    normalizar,
    programas_de,
)
from app.db import repo
from app.integrations import telegram
from app.schemas.caso import Caso, EstadoCaso, Sentido
from app.schemas.consejo import ETIQUETA_SENTIDO_CONSEJO, Cruce
from app.schemas.telegram import CallbackQuery, Document, Message, Update
from app.services import (
    actas_comite,
    adjuntos,
    borrador,
    casos,
    consejo,
    ficha,
    firma,
    flujo,
    formatos,
    indicadores,
    resumen,
    suit,
)
from app.services.documento import fecha_larga

logger = logging.getLogger(__name__)

_RE_CASO = re.compile(r"Caso #(\d+)")
_RE_NOTA = re.compile(r"Nota del comité · caso #(\d+)")
_RE_CONCEPTO = re.compile(r"Concepto de (.+?) · caso #(\d+)")
_RE_FIRMA = re.compile(r"Datos para firmar · .+? \((\w+)\)")
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
_ESPERA_ACTA = "acta_consejo"

AYUDA = """<b>Cómo funciona</b>
1. Pega el correo del estudiante (texto) y envía los pantallazos del SIA y de la solicitud. También recibo PDF y Word (.docx): el formato de solicitud lo leo; los demás quedan como anexos.
2. Toca <b>Procesar</b> (o escribe /listo). Te respondo con la ficha del caso y las alertas.
3. Si un dato está mal, <b>responde a la ficha</b> con la corrección.
4. Con <b>Concepto</b> registras lo que opinó cada profesor del comité; va al acta, no al oficio.
5. Después del comité, marca cada caso: Recomendar aprobar, Recomendar no aprobar o Pendiente.
6. Cada día hábil a las 4:50 p. m. te llegan, por programa, el oficio y el acta (.docx y PDF). También con /acta.
7. Después de la sesión, <b>/firmar programa</b>: revisas el resumen, confirmas el radicado y los datos de la sesión, y recibes el oficio y el acta finales con la firma. Los casos firmados pasan al Consejo.

<b>Comandos</b>
/nuevo — empieza otro caso
/listo — procesa el caso abierto
/cancelar — descarta el caso abierto
/casos — últimos casos
/caso N — vuelve a mostrar la ficha del caso N
/adjuntos N — lista los adjuntos del caso N y permite quitar uno equivocado
/acta — oficio y acta ahora
/firmar programa — firma el oficio y el acta del programa
/cerrar_acta — cierra el acta del comité sin firmar en MemorIA (número propuesto, fecha de hoy) y empieza la siguiente
/acta_consejo — sube el acta del Consejo para registrar sus decisiones
/costo — consumo del modelo este mes"""


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


async def manejar_update(db: Conexion, update: Update) -> None:
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


async def _mensaje(db: Conexion, msg: Message) -> None:
    assert msg.from_ is not None
    chat_id = msg.chat.id
    texto = (msg.text or "").strip()
    usuario = await repo.get_usuario(db, msg.from_.id)

    # Decanatura y admin: indicadores de lectura. Para los demás no existe.
    comando, _, argumento = texto.partition(" ")
    if comando.split("@")[0].lower() == "/indicadores" and (
        resumen.puede_ver_indicadores(msg.from_.id)
    ):
        await _indicadores(db, chat_id, argumento)
        return
    if comando.split("@")[0].lower() == "/suit" and (
        resumen.puede_ver_indicadores(msg.from_.id)
    ):
        await _suit(db, chat_id, argumento)
        return

    # Decanatura: solo el resumen, de lectura. Para los demás /resumen no existe.
    if resumen.es_decanatura(msg.from_.id):
        if texto.split("@")[0].split(" ")[0].lower() == "/resumen":
            await telegram.send_message(chat_id, await resumen.armar(db))
            return
        if usuario is None:
            await telegram.send_message(chat_id, resumen.AYUDA)
            return

    if usuario is None:
        await _registro(db, msg, texto)
        return
    if usuario.direccion is None:
        await _pedir_direccion(chat_id)
        return

    if msg.document is not None:
        leyenda = (msg.caption or "").strip().split("@")[0].lower()
        estado = await repo.get_estado(db, chat_id)
        if leyenda.startswith("/acta_consejo") or estado.esperando == _ESPERA_ACTA:
            await _acta_consejo(db, msg, usuario)
            return
    elif not texto.startswith("/acta_consejo"):
        # Cualquier otro mensaje cancela la espera del acta.
        estado = await repo.get_estado(db, chat_id)
        if estado.esperando == _ESPERA_ACTA:
            await repo.set_estado(db, chat_id, caso_abierto_id=estado.caso_abierto_id)
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
        # Respuesta al pedido de los datos para firmar.
        m = _RE_FIRMA.search(respondido)
        if m:
            await _datos_firma(db, chat_id, usuario, m.group(1), texto)
            return
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
    db: Conexion,
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
        tratamiento = casos.tratamiento_de(caso, miembro)
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


async def _registro(db: Conexion, msg: Message, texto: str) -> None:
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
    db: Conexion, msg: Message, usuario: repo.Usuario, texto: str
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
            try:
                await flujo.descartar(
                    db,
                    estado.caso_abierto_id,
                    rol=flujo.ADMINISTRATIVA,
                    persona=_persona(usuario),
                    canal=_CANAL,
                )
            except flujo.TransicionNoPermitida as exc:
                await telegram.send_message(chat_id, escape(str(exc)))
                return
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
    elif nombre == "/adjuntos":
        valor = arg.strip().lstrip("#")
        caso_n = int(valor) if valor.isdigit() else estado.caso_abierto_id
        caso = await _caso_propio(db, caso_n, usuario) if caso_n else None
        if caso is None:
            await telegram.send_message(chat_id, "Uso: /adjuntos 12")
        else:
            await _listar_adjuntos(db, chat_id, caso)
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
    elif nombre == "/firmar":
        if not arg.strip():
            await _ofrecer_firma(db, chat_id, usuario.direccion)
            return
        programa = firma.programa_de_la_direccion(arg, usuario.direccion)
        if programa is None:
            await telegram.send_message(
                chat_id,
                "No conozco ese programa en tu dirección. Escribe /firmar para "
                "ver los botones.",
            )
            return
        await _resumen_firma(db, chat_id, usuario, programa.clave)
    elif nombre == "/cerrar_acta":
        await _ofrecer_cierre(db, chat_id, usuario.direccion)
    elif nombre == "/acta_consejo":
        await repo.set_estado(
            db,
            chat_id,
            caso_abierto_id=estado.caso_abierto_id,
            esperando=_ESPERA_ACTA,
        )
        await telegram.send_message(
            chat_id,
            "Envíe el acta del Consejo (PDF con texto o Word). La leo y le muestro "
            "qué decisiones cruzan con sus casos; nada se registra hasta que "
            "usted lo confirme.",
        )
    elif nombre == "/costo":
        await _costo(db, chat_id)
    else:
        await telegram.send_message(chat_id, "No conozco ese comando. Escribe /ayuda.")


async def _indicadores(db: Conexion, chat_id: int, argumento: str) -> None:
    """/indicadores [periodo]: toda la Facultad, solo cifras, y el Excel."""
    hoy = indicadores.hoy_local()
    try:
        periodo = indicadores.periodo_de(argumento, hoy)
    except indicadores.PeriodoInvalido as exc:
        await telegram.send_message(chat_id, escape(str(exc)))
        return
    reporte = await indicadores.reporte(db, periodo, hoy)
    # El Excel se arma antes de enviar: si config/indicadores.yaml falla, se
    # avisa en vez de cortar después del texto.
    archivo: bytes | None = None
    try:
        archivo = indicadores.xlsx(reporte)
    except indicadores.ConfigIndicadoresError:
        logger.exception("No pude armar el Excel de indicadores")
    await telegram.send_message(chat_id, indicadores.formatear(reporte))
    if archivo is None:
        await telegram.send_message(
            chat_id,
            "No pude armar el Excel: config/indicadores.yaml tiene un error. "
            "Las cifras de arriba no cambian.",
        )
        return
    await telegram.send_document(
        chat_id,
        nombre=indicadores.nombre_xlsx(reporte),
        contenido=archivo,
        mime=indicadores.MIME_XLSX,
        caption="Los mismos indicadores en Excel, con la pestaña «fuentes».",
    )


async def _suit(db: Conexion, chat_id: int, argumento: str) -> None:
    """/suit [año]: datos de operación de la Secretaría, solo cifras, y el Excel."""
    hoy = indicadores.hoy_local()
    try:
        ano = suit.ano_de(argumento, hoy)
    except suit.AnoInvalido as exc:
        await telegram.send_message(chat_id, escape(str(exc)))
        return
    r = await suit.reporte(db, ano, hoy)
    await telegram.send_message(chat_id, suit.formatear(r))
    await telegram.send_document(
        chat_id,
        nombre=suit.nombre_xlsx(r),
        contenido=suit.xlsx(r),
        mime=suit.MIME_XLSX,
        caption="Fila lista para copiar al Excel de «Datos de Operación».",
    )


async def _listar(db: Conexion, chat_id: int, direccion: str) -> None:
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
            f"{_etapa_corta(c)} · {c.sentido.value}"
        )
    await telegram.send_message(chat_id, "\n".join(lineas))


def _etapa_corta(caso: Caso) -> str:
    nombre = flujo.nombre_etapa(caso.etapa)
    return nombre.lower() if nombre else caso.estado.value


async def _costo(db: Conexion, chat_id: int) -> None:
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


def _comites_con_recomendacion(casos: list[Caso]) -> dict[str, Programa]:
    """Los comités con casos recomendados: uno por programa en pregrado, o el
    comité único de la dirección (un solo botón para todos sus programas)."""
    comites: dict[str, Programa] = {}
    for c in casos:
        if c.programa not in PROGRAMAS or c.sentido == Sentido.PENDIENTE:
            continue
        comite = comite_de(c.programa)
        if comite is not None:
            comites[comite.clave] = comite
    return dict(sorted(comites.items()))


def _rotulo(comite: Programa) -> str:
    """Botones: el programa, o «Comité de posgrados» para el comité único."""
    return "Comité de posgrados" if comite.es_comite_unico else comite.nombre


async def _ofrecer_cierre(db: Conexion, chat_id: int, direccion: str) -> None:
    casos = await repo.casos_listos(db, direccion=direccion)
    con_sentido = [c for c in casos if c.sentido != Sentido.PENDIENTE and c.programa]
    if not con_sentido:
        await telegram.send_message(
            chat_id, "No hay casos con recomendación del comité para cerrar."
        )
        return
    comites = _comites_con_recomendacion(con_sentido)
    anio = firma.hoy_local().year
    botones = []
    for p, comite in comites.items():
        numero = await actas_comite.proponer_numero(db, p, anio)
        botones.append(
            [
                {
                    "text": f"Cerrar {_rotulo(comite)} · acta "
                    f"{actas_comite.formato_numero(numero)}",
                    "callback_data": f"cerrar:{p}:{numero}",
                }
            ]
        )
    await telegram.send_message(
        chat_id,
        "Cerrar guarda el acta del comité con el número propuesto (el siguiente "
        "del programa) y la fecha de hoy, y saca del borrador los casos que ya "
        "tienen recomendación del comité. Los pendientes y los nuevos pasan a la "
        "siguiente acta. Para otro número u otra fecha, use /firmar o la web "
        "(«Cerrar sin firmar»).",
        botones=botones,
    )


async def _cerrar_acta(
    db: Conexion,
    chat_id: int,
    usuario: repo.Usuario,
    cq: CallbackQuery,
    partes: list[str],
) -> None:
    """Botón «Cerrar … · acta N»: el número es el que la persona vio."""
    assert usuario.direccion is not None
    clave = partes[1]
    hoy = firma.hoy_local()
    try:
        acta = await actas_comite.abierta(
            db, direccion=usuario.direccion, clave=clave, hoy=hoy
        )
        numero = int(partes[2]) if len(partes) == 3 else acta.numero_propuesto
        cerrada = await actas_comite.cerrar_sin_firma(
            db,
            direccion=usuario.direccion,
            clave=clave,
            numero=numero,
            fecha_sesion=hoy,
            caso_ids=acta.caso_ids,
            persona=_persona(usuario),
            rol=flujo.ADMINISTRATIVA,
            canal=_CANAL,
            hoy=hoy,
        )
    except (
        ValueError,
        actas_comite.ActaNoPermitida,
        flujo.TransicionNoPermitida,
    ) as exc:
        await telegram.responder_callback(cq.id, str(exc)[:190])
        return
    if cq.message:
        await telegram.editar_botones(chat_id, cq.message.message_id, None)
    siguiente = await actas_comite.proponer_numero(db, clave, hoy.year)
    await telegram.responder_callback(cq.id, f"Acta {cerrada.numero_texto} cerrada")
    await telegram.send_message(
        chat_id,
        f"Cerré el acta {cerrada.numero_texto} de {hoy.year} de "
        f"{escape(acta.programa.nombre)} con {len(cerrada.caso_ids)} caso(s): "
        + ", ".join(f"#{i}" for i in cerrada.caso_ids)
        + f". La siguiente acta es la {actas_comite.formato_numero(siguiente)}.",
    )


# ---------------------------------------------------------------------------
# Firma del oficio y del acta (app/services/firma.py)
# ---------------------------------------------------------------------------

_CAMPOS_FIRMA = {
    "radicado": "radicado",
    "acta": "numero_acta",
    "numero de acta": "numero_acta",
    "numero del acta": "numero_acta",
    "no. acta": "numero_acta",
    "acta no.": "numero_acta",
    "fecha": "fecha_sesion",
    "fecha de la sesion": "fecha_sesion",
    "hora": "hora",
    "lugar": "lugar",
}


async def _ofrecer_firma(db: Conexion, chat_id: int, direccion: str) -> None:
    casos_listos = await repo.casos_listos(db, direccion=direccion)
    comites = _comites_con_recomendacion(casos_listos)
    if not comites:
        await telegram.send_message(
            chat_id, "No hay casos con recomendación del comité para firmar."
        )
        return
    botones = [
        [{"text": f"Firmar {_rotulo(comite)}", "callback_data": f"fir:{p}"}]
        for p, comite in comites.items()
    ]
    await telegram.send_message(
        chat_id,
        "¿Qué programa vas a firmar? Primero te muestro el resumen.",
        botones=botones,
    )


def _linea_caso_firma(caso: Caso) -> str:
    e = caso.extraccion
    nombre = escape((e.nombre_estudiante or "sin nombre").title()) if e else "?"
    sentido = (
        "recomienda APROBAR"
        if caso.sentido == Sentido.APROBAR
        else "recomienda NO APROBAR"
    )
    comite = comite_de(caso.programa)
    if comite is not None and comite.es_comite_unico and caso.programa in PROGRAMAS:
        # Varios programas en la misma acta: se dice de cuál es el caso.
        nombre += f" ({escape(PROGRAMAS[caso.programa].nombre)})"
    return f"• #{caso.id} · {nombre} · {sentido}"


def _texto_resumen(prep: firma.Preparacion, persona: str) -> str:
    p = prep.programa
    lineas = [f"<b>Firma · {escape(p.comite if p.es_comite_unico else p.nombre)}</b>"]
    if p.es_comite_unico:
        lineas.append(
            "Una sola acta para "
            + ", ".join(escape(PROGRAMAS[c].nombre) for c in p.programas)
            + "."
        )
    if prep.firmante:
        lineas.append(
            f"Firma: {escape(prep.firmante.nombre)}, "
            f"{escape(prep.firmante.cargo_bajo_firma)}. "
            f"Firmas en su nombre: {escape(persona)}."
        )
    lineas.append(f"\nEntran {len(prep.casos)} caso(s) al oficio y al acta:")
    lineas += [_linea_caso_firma(c) for c in prep.casos]
    for aviso in prep.avisos:
        lineas.append(f"\n⚠️ {escape(aviso)}")
    return "\n".join(lineas)


async def _resumen_firma(
    db: Conexion, chat_id: int, usuario: repo.Usuario, clave: str
) -> None:
    assert usuario.direccion is not None
    try:
        prep = await firma.preparar(db, direccion=usuario.direccion, clave=clave)
    except firma.FirmaNoPermitida as exc:
        await telegram.send_message(chat_id, escape(str(exc)))
        return
    if prep.bloqueos:
        await telegram.send_message(
            chat_id,
            f"No se puede firmar {escape(prep.programa.nombre)}:\n"
            + "\n".join(f"• {escape(b)}" for b in prep.bloqueos),
        )
        return
    await telegram.send_message(chat_id, _texto_resumen(prep, _persona(usuario)))
    radicado = prep.radicado_propuesto or f"Mz.FCEN.1.0__-___-{firma.hoy_local():%y}"
    await telegram.send_message(
        chat_id,
        f"Datos para firmar · {escape(prep.programa.nombre)} ({prep.programa.clave})\n"
        "Responde a este mensaje con los datos. El radicado es una propuesta "
        "(siguiente de la dirección) y el acta también (siguiente del programa): "
        "corrígelos si la dirección ya usó esos números por fuera de MemorIA.\n\n"
        f"<pre>Radicado: {escape(radicado)}\n"
        f"Acta: {escape(prep.numero_acta_propuesto)}\n"
        "Fecha: DD/MM/AAAA\n"
        "Hora: \n"
        "Lugar: </pre>\n"
        "Lugar puede ser «sesión ad referéndum». Nada se firma hasta que confirmes.",
        forzar_respuesta=True,
    )


def _leer_datos_firma(texto: str) -> dict[str, str]:
    datos: dict[str, str] = {}
    for linea in texto.splitlines():
        clave, separador, valor = linea.partition(":")
        if not separador:
            continue
        campo = _CAMPOS_FIRMA.get(normalizar(clave).strip(" .-•"))
        if campo:
            datos[campo] = valor.strip()
    return datos


async def _datos_firma(
    db: Conexion, chat_id: int, usuario: repo.Usuario, clave: str, texto: str
) -> None:
    assert usuario.direccion is not None
    datos = _leer_datos_firma(texto)
    try:
        prep = await firma.preparar(db, direccion=usuario.direccion, clave=clave)
        if prep.bloqueos:
            raise firma.FirmaNoPermitida(prep.bloqueos[0])
        radicado = firma.normalizar_radicado(datos.get("radicado", ""))
        if await firma.radicado_usado(db, radicado):
            raise ValueError(f"El radicado {radicado} ya se usó en otra firma.")
        sesion = firma.validar_sesion(
            numero_acta=datos.get("numero_acta", ""),
            fecha_sesion=datos.get("fecha_sesion", ""),
            hora=datos.get("hora", ""),
            lugar=datos.get("lugar", ""),
        )
    except (ValueError, firma.FirmaNoPermitida) as exc:
        await telegram.send_message(
            chat_id,
            f"{escape(str(exc))}\nVuelve a responder al mensaje «Datos para "
            "firmar» con los datos corregidos.",
        )
        return
    await firma.guardar_pendiente(
        db,
        chat_id,
        firma.Pendiente(clave, radicado, sesion, prep.caso_ids),
    )
    p = prep.programa
    texto_confirmar = (
        _texto_resumen(prep, _persona(usuario))
        + f"\n\nRadicado: <b>{escape(radicado)}</b>"
        + f"\nActa {escape(sesion.numero_acta)} · "
        + f"{fecha_larga(sesion.fecha_sesion)} · {escape(sesion.hora)} · "
        + f"{escape(sesion.lugar)}"
        + "\n\nAl confirmar genero el oficio y el acta finales con la firma, "
        "registro quién firmó y los casos pasan al Consejo de Facultad. "
        "¿Confirmas la firma?"
    )
    await telegram.send_message(
        chat_id,
        texto_confirmar,
        botones=[
            [{"text": f"✍️ Firmar {p.nombre}", "callback_data": "fok"}],
            [{"text": "Cancelar", "callback_data": "fno"}],
        ],
    )


async def _confirmar_firma(
    db: Conexion, chat_id: int, usuario: repo.Usuario, callback_id: str
) -> None:
    assert usuario.direccion is not None
    pendiente = await firma.leer_pendiente(db, chat_id)
    if pendiente is None:
        await telegram.responder_callback(callback_id, "No hay una firma pendiente.")
        return
    await firma.borrar_pendiente(db, chat_id)
    await telegram.responder_callback(callback_id, "Firmando…")
    try:
        hecha = await firma.firmar(
            db,
            direccion=usuario.direccion,
            clave=pendiente.programa,
            radicado=pendiente.radicado,
            sesion=pendiente.sesion,
            caso_ids=pendiente.caso_ids,
            persona=_persona(usuario),
            rol=flujo.ADMINISTRATIVA,
            canal=_CANAL,
        )
    except (firma.FirmaNoPermitida, flujo.TransicionNoPermitida) as exc:
        await telegram.send_message(
            chat_id, f"No firmé: {escape(str(exc))}\nVuelve a empezar con /firmar."
        )
        return
    programa = comite_de(hecha.programa)
    assert programa is not None
    siguiente = actas_comite.formato_numero(
        await actas_comite.proponer_numero(db, hecha.programa, firma.hoy_local().year)
    )
    for archivo in hecha.archivos:
        rotulo = "Oficio al Consejo" if archivo.documento == "oficio" else "Acta"
        await telegram.send_document(
            chat_id,
            nombre=archivo.ruta.name,
            contenido=firma.leer_verificado(archivo),
            mime=borrador.DOCX_MIME if archivo.formato == "docx" else "application/pdf",
            caption=f"<b>{escape(programa.nombre)}</b> · {rotulo} firmado · "
            f"{escape(hecha.radicado)}",
        )
    hashes = "\n".join(
        f"{escape(a.ruta.name)}: <code>{a.sha256}</code>" for a in hecha.archivos
    )
    await telegram.send_message(
        chat_id,
        f"Firmado. Radicado <b>{escape(hecha.radicado)}</b>, acta "
        f"{escape(hecha.numero_acta)}. Los casos "
        + ", ".join(f"#{i}" for i in hecha.caso_ids)
        + " pasan al Consejo de Facultad.\n\nEl acta "
        + f"{escape(hecha.numero_acta)} queda cerrada. La siguiente acta de "
        + f"{escape(programa.nombre)} es la {siguiente}.\n\nSHA-256 de cada documento:\n"
        + hashes,
    )


# ---------------------------------------------------------------------------
# Caso abierto
# ---------------------------------------------------------------------------


async def _agregar_al_caso(db: Conexion, msg: Message, usuario: repo.Usuario) -> None:
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
            canal=_CANAL,
            persona=_persona(usuario),
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
        await _documento(db, chat_id, caso_id, msg.document)

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


async def _documento(db: Conexion, chat_id: int, caso_id: int, doc: Document) -> None:
    """PDF, Word o imagen enviados como archivo (app/services/adjuntos.py). El
    formato de solicitud se lee; los demás quedan guardados como anexos."""
    nombre = doc.file_name or "archivo"
    es_imagen = (doc.mime_type or "").startswith("image/")
    if doc.file_name and not es_imagen and not adjuntos.permitido_por_nombre(nombre):
        await telegram.send_message(
            chat_id,
            f"No adjunté «{escape(nombre)}»: solo recibo {adjuntos.TEXTO_PERMITIDOS}.",
        )
        return
    if (doc.file_size or 0) > adjuntos.MAX_DOCUMENTO:
        await telegram.send_message(
            chat_id, f"No adjunté «{escape(nombre)}»: pesa más de 20 MB."
        )
        return
    datos = await telegram.descargar_archivo(doc.file_id)
    try:
        agregado = await adjuntos.agregar(
            db, caso_id, datos, nombre, unico=doc.file_unique_id
        )
    except adjuntos.AdjuntoInvalido as exc:
        await telegram.send_message(chat_id, f"No lo adjunté. {escape(str(exc))}")
        return
    if not agregado.nuevo:
        return
    unico = agregado.unico
    if agregado.tipo == "formato":
        await telegram.send_message(
            chat_id, f"Leí «{escape(nombre)}» como formato de solicitud."
        )
    elif agregado.tipo == "pendiente":
        await telegram.send_message(
            chat_id,
            f"«{escape(nombre)}» es un PDF escaneado. ¿Es el formato de "
            "solicitud del estudiante?",
            botones=[
                [
                    {"text": "Sí, léelo", "callback_data": f"f:{caso_id}:{unico}:si"},
                    {
                        "text": "No, es un anexo",
                        "callback_data": f"f:{caso_id}:{unico}:no",
                    },
                ]
            ],
        )
    elif agregado.tipo == "anexo":
        await telegram.send_message(
            chat_id,
            f"Guardé «{escape(nombre)}» como anexo del caso #{caso_id}. Si no "
            f"era, quítalo con /adjuntos {caso_id}.",
        )


async def _listar_adjuntos(db: Conexion, chat_id: int, caso: Caso) -> None:
    lista = await adjuntos.listar(db, caso.id)
    if not lista:
        await telegram.send_message(chat_id, f"El caso #{caso.id} no tiene adjuntos.")
        return
    lineas = [f"<b>Adjuntos del caso #{caso.id}</b>"]
    botones: list[list[dict[str, str]]] = []
    for i, a in enumerate(lista, 1):
        leido = " · ya leído" if a["leido"] else ""
        lineas.append(f"{i}. {escape(str(a['nombre']))} ({a['tipo_texto']}{leido})")
        botones.append(
            [{"text": f"🗑 Quitar {i}", "callback_data": f"aq:{caso.id}:{a['id']}"}]
        )
    await telegram.send_message(chat_id, "\n".join(lineas), botones=botones)


async def _acta_consejo(db: Conexion, msg: Message, usuario: repo.Usuario) -> None:
    """Lee el acta del Consejo y propone el cruce con los casos del área."""
    assert msg.document is not None and usuario.direccion is not None
    chat_id = msg.chat.id
    estado = await repo.get_estado(db, chat_id)
    await repo.set_estado(db, chat_id, caso_abierto_id=estado.caso_abierto_id)
    doc = msg.document
    if (doc.file_size or 0) > formatos.MAX_BYTES:
        await telegram.send_message(chat_id, "El acta pesa más de 20 MB.")
        return
    await telegram.send_message(chat_id, "Leyendo el acta del Consejo…")
    try:
        registrada = await consejo.leer_y_registrar(
            db,
            datos=await telegram.descargar_archivo(doc.file_id),
            nombre_archivo=doc.file_name or "acta.pdf",
            direccion=usuario.direccion,
            instancia=None,
            subido_por=usuario.nombre or str(usuario.telegram_id),
        )
    except consejo.ErrorActa as exc:
        await telegram.send_message(chat_id, escape(str(exc)))
        return
    texto, botones = await _resumen_acta(db, registrada, usuario.direccion)
    await telegram.send_message(chat_id, texto, botones=botones)


async def _resumen_acta(
    db: Conexion, registrada: consejo.ActaRegistrada, direccion: str
) -> tuple[str, list[list[dict[str, str]]] | None]:
    exactos = [p for p in registrada.propuestas if p.cruce == Cruce.EXACTO]
    duda = [
        p
        for p in registrada.propuestas
        if p.cruce in (Cruce.DUDOSO, Cruce.NO_VERIFICADO)
    ]
    sin_caso = [p for p in registrada.propuestas if p.cruce == Cruce.SIN_CASO]
    faltan = await consejo.no_aparecieron(db, registrada.acta_id, direccion)
    lineas = [
        f"<b>Acta del Consejo leída</b> ({len(registrada.propuestas)} decisiones)",
        f"Cruzaron: {len(exactos)} · En duda: {len(duda)} · Sin caso: "
        f"{len(sin_caso)} · Recomendados que no aparecen: {len(faltan)}",
    ]
    for p in exactos:
        lineas.append(
            f"• #{p.caso_id}: {escape(p.leida.nombre_estudiante or '')} — "
            f"{ETIQUETA_SENTIDO_CONSEJO[p.sentido].lower()} "
            f"«{escape(p.leida.texto_decision)}»"
        )
    if duda or sin_caso:
        lineas.append(
            "Lo que quedó en duda se resuelve a mano en la web, pantalla "
            "«Acta del Consejo»."
        )
    lineas.append("Nada se ha registrado todavía.")
    botones = (
        [
            [
                {
                    "text": f"Confirmar {len(exactos)} cruce(s)",
                    "callback_data": f"ac:{registrada.acta_id}",
                }
            ]
        ]
        if exactos
        else None
    )
    return "\n".join(lineas), botones


async def _guardar_imagen(
    db: Conexion, caso_id: int, file_id: str, unique: str, ext: str
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
    db: Conexion, chat_id: int, usuario: repo.Usuario, caso_id: int
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
    await telegram.send_message(chat_id, f"Leyendo el caso #{caso.id}…")
    resultado = await casos.procesar(db, caso)
    if resultado.error is not None:
        await telegram.send_message(
            chat_id,
            f"No pude procesar el caso #{caso.id}: {escape(resultado.error)}\n"
            "El caso sigue abierto; puedes agregar algo y volver a intentar con /listo.",
        )
        return
    estado = await repo.get_estado(db, chat_id)
    if estado.caso_abierto_id == caso.id:
        await repo.set_estado(db, chat_id, caso_abierto_id=None)
    await _enviar_ficha(chat_id, resultado.caso)


async def _corregir(
    db: Conexion,
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
    resultado = await casos.corregir(db, caso, texto)
    if resultado.error is not None:
        await telegram.send_message(
            chat_id, f"No pude aplicar la corrección: {escape(resultado.error)}"
        )
        return
    await _enviar_ficha(chat_id, resultado.caso)


async def _enviar_ficha(chat_id: int, caso: Caso) -> None:
    if caso.extraccion is None:
        await telegram.send_message(
            chat_id, f"Caso #{caso.id}: {caso.estado.value}, todavía sin procesar."
        )
        return
    programa = PROGRAMAS.get(caso.programa or "")
    analisis = casos.analizar(caso)
    assert analisis is not None
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


# Quien usa el bot de actas es la administrativa de su área.
_CANAL = "telegram"


def _persona(usuario: repo.Usuario) -> str:
    return usuario.nombre or str(usuario.telegram_id)


async def _quitar_adjunto(
    db: Conexion,
    cq: CallbackQuery,
    chat_id: int,
    usuario: repo.Usuario,
    caso: Caso,
    archivo_id: int,
    paso: str,
) -> None:
    """«aq»: pide confirmación. «aqs»: borra de verdad."""
    if cq.message:
        await telegram.editar_botones(chat_id, cq.message.message_id, None)
    archivo = await repo.get_archivo_por_id(db, caso.id, archivo_id)
    if archivo is None:
        await telegram.responder_callback(cq.id, "Ese adjunto ya no está.")
        return
    await telegram.responder_callback(cq.id)
    if paso == "aq":
        nombre = archivo.nombre or "el pantallazo"
        aviso = (
            "\nYa se usó al leer el caso: después revisa los datos o vuelve a leerlo."
            if archivo.leido and caso.extraccion is not None
            else ""
        )
        await telegram.send_message(
            chat_id,
            f"¿Quitar «{escape(nombre)}» del caso #{caso.id}? Se borra del todo y "
            f"no se puede recuperar.{aviso}",
            botones=[
                [
                    {
                        "text": "Sí, borrar",
                        "callback_data": f"aqs:{caso.id}:{archivo_id}",
                    },
                    {"text": "No", "callback_data": f"aqn:{caso.id}"},
                ]
            ],
        )
        return
    borrado = await adjuntos.borrar(
        db,
        caso,
        archivo_id,
        rol=flujo.ADMINISTRATIVA,
        persona=_persona(usuario),
        canal=_CANAL,
    )
    texto = f"Quité el adjunto del caso #{caso.id}."
    if borrado.aviso:
        texto += " " + escape(borrado.aviso)
    await telegram.send_message(chat_id, texto)


async def _caso_propio(
    db: Conexion, caso_id: int, usuario: repo.Usuario
) -> Caso | None:
    caso = await repo.get_caso(db, caso_id)
    if caso is None or caso.direccion != usuario.direccion:
        return None
    return caso


# ---------------------------------------------------------------------------
# Botones
# ---------------------------------------------------------------------------


async def _callback(db: Conexion, cq: CallbackQuery) -> None:
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
    if partes[0] == "ac" and len(partes) == 2 and partes[1].isdigit():
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        aplicadas = await consejo.aplicar_exactos(
            db,
            int(partes[1]),
            persona=usuario.nombre or str(usuario.telegram_id),
            canal=_CANAL,
            direccion=usuario.direccion,
        )
        await telegram.responder_callback(cq.id, f"{len(aplicadas)} registradas")
        await telegram.send_message(
            chat_id,
            f"Registré {len(aplicadas)} decisión(es) del Consejo: "
            + (", ".join(f"#{d.caso_id}" for d in aplicadas) or "ninguna"),
        )
        return
    try:
        caso_id = int(partes[1]) if len(partes) > 1 and partes[0] != "cerrar" else None
    except ValueError:
        caso_id = None

    if partes[0] == "proc" and caso_id:
        await telegram.responder_callback(cq.id)
        async with _locks[chat_id]:
            await _procesar(db, chat_id, usuario, caso_id)
        return

    if partes[0] == "cerrar" and len(partes) in (2, 3):
        await _cerrar_acta(db, chat_id, usuario, cq, partes)
        return

    if partes[0] == "fir" and len(partes) == 2:
        await telegram.responder_callback(cq.id)
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        await _resumen_firma(db, chat_id, usuario, partes[1])
        return
    if data == "fok":
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        async with _locks[chat_id]:
            await _confirmar_firma(db, chat_id, usuario, cq.id)
        return
    if data == "fno":
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        await firma.borrar_pendiente(db, chat_id)
        await telegram.responder_callback(cq.id, "Cancelado")
        await telegram.send_message(chat_id, "Cancelado. No se firmó nada.")
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
        try:
            await flujo.recomendar(
                db,
                caso.id,
                sentido,
                rol=flujo.ADMINISTRATIVA,
                persona=_persona(usuario),
                canal=_CANAL,
            )
        except flujo.TransicionNoPermitida as exc:
            await telegram.responder_callback(cq.id, str(exc)[:190])
            return
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
        filas = [
            [{"text": m.nombre, "callback_data": f"k:{caso.id}:{i}"}]
            for i, m in enumerate(integrantes_con_nombre(comite_de(caso.programa)))
        ]
        filas.append([{"text": "Otro miembro", "callback_data": f"k:{caso.id}:x"}])
        await telegram.send_message(
            chat_id, f"¿De quién es el concepto del caso #{caso.id}?", botones=filas
        )
    elif partes[0] == "k" and len(partes) == 3:
        await telegram.responder_callback(cq.id)
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
        miembros = integrantes_con_nombre(comite_de(caso.programa))
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
        mensaje = await adjuntos.resolver_pendiente(
            db, caso.id, partes[2], es_formato=partes[3] == "si"
        )
        if mensaje:
            await telegram.send_message(chat_id, mensaje)
    elif partes[0] in ("aq", "aqs") and len(partes) == 3 and partes[2].isdigit():
        await _quitar_adjunto(db, cq, chat_id, usuario, caso, int(partes[2]), partes[0])
    elif partes[0] == "aqn":
        await telegram.responder_callback(cq.id, "No se borró nada")
        if cq.message:
            await telegram.editar_botones(chat_id, cq.message.message_id, None)
    elif (
        partes[0] == "pr"
        and len(partes) == 3
        and partes[2] in flujo.Prerrevision._value2member_map_
    ):
        resultado = flujo.Prerrevision(partes[2])
        try:
            etapa = await flujo.prerrevisar(
                db,
                caso.id,
                resultado,
                rol=flujo.ADMINISTRATIVA,
                persona=_persona(usuario),
                canal=_CANAL,
            )
        except flujo.TransicionNoPermitida as exc:
            await telegram.responder_callback(cq.id, str(exc)[:190])
            return
        await telegram.responder_callback(
            cq.id,
            f"Caso #{caso.id}: {resultado.value} · {flujo.NOMBRE_ETAPA[etapa].lower()}",
        )
    elif partes[0] == "d":
        try:
            await flujo.descartar(
                db,
                caso.id,
                rol=flujo.ADMINISTRATIVA,
                persona=_persona(usuario),
                canal=_CANAL,
            )
        except flujo.TransicionNoPermitida as exc:
            await telegram.responder_callback(cq.id, str(exc)[:190])
            return
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
