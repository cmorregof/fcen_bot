"""Línea única de estados de una solicitud estudiantil (servicio de actas).

Una solicitud tiene una sola ficha (`casos`) y una sola línea de estados
(`casos.etapa` más su historia en `caso_eventos`), entre por Telegram o por
la web. La máquina de estados es explícita y determinista: cada acción dice
desde qué etapas se puede hacer, a cuál lleva y qué roles la pueden hacer.
Cada transición guarda la fecha, quién la hizo, con qué rol y por qué canal.

Reglas que no se negocian (AGENTS.md):

- El comité asesor NUNCA aprueba: recomienda APROBAR o NO APROBAR. Ninguna
  transición la hace el rol «comite» y ninguna lleva a «decidida» sin el acta
  del Consejo confirmada por una persona.
- El modelo no hace transiciones: las hace una persona (botón o comando) o el
  sistema cuando termina la lectura.

`casos.estado` sigue existiendo: es el estado de la lectura y del borrador del
comité (abierto, procesando, listo, cerrado…). La línea que ven las personas
y de la que salen los tiempos es `casos.etapa`. Ver docs/flujo-solicitudes.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.core import solicitudes
from app.core.conexion import Conexion, Fila
from app.core.config import settings
from app.db import repo
from app.schemas.caso import EstadoCaso, Sentido, TipoSolicitud
from app.schemas.consejo import SentidoConsejo


class Etapa(StrEnum):
    LLEGADA = "llegada"
    INCOMPLETA = "incompleta"
    IMPROCEDENTE = "improcedente"
    EN_COMITE = "en_comite"
    RECOMENDADA = "recomendada"
    EN_CONSEJO = "en_consejo"
    DECIDIDA = "decidida"
    EXPEDIDA = "expedida"
    NOTIFICADA = "notificada"
    ARCHIVADA = "archivada"
    DESCARTADA = "descartada"


NOMBRE_ETAPA: dict[Etapa, str] = {
    Etapa.LLEGADA: "Llegada",
    Etapa.INCOMPLETA: "Incompleta (prerrevisión)",
    Etapa.IMPROCEDENTE: "Improcedente (prerrevisión)",
    Etapa.EN_COMITE: "En comité",
    Etapa.RECOMENDADA: "Recomendada por el comité",
    Etapa.EN_CONSEJO: "En el Consejo",
    Etapa.DECIDIDA: "Decidida por el Consejo",
    Etapa.EXPEDIDA: "Acto expedido",
    Etapa.NOTIFICADA: "Notificada al estudiante",
    Etapa.ARCHIVADA: "Archivada",
    Etapa.DESCARTADA: "Descartada",
}


def nombre_etapa(valor: str | None) -> str | None:
    """Nombre legible de una etapa guardada (None si no tiene)."""
    if valor in Etapa._value2member_map_:
        return NOMBRE_ETAPA[Etapa(str(valor))]
    return None


# Sin salida: la solicitud ya terminó su recorrido.
FINALES = frozenset({Etapa.ARCHIVADA, Etapa.DESCARTADA})


class Prerrevision(StrEnum):
    PROCEDENTE = "procedente"
    IMPROCEDENTE = "improcedente"
    INCOMPLETO = "incompleto"


class Accion(StrEnum):
    REGISTRAR = "registrar"
    LECTURA_LISTA = "lectura_lista"
    PRERREVISAR_PROCEDENTE = "prerrevisar_procedente"
    PRERREVISAR_IMPROCEDENTE = "prerrevisar_improcedente"
    PRERREVISAR_INCOMPLETO = "prerrevisar_incompleto"
    COMPLETAR = "completar"
    RECOMENDAR = "recomendar"
    QUITAR_RECOMENDACION = "quitar_recomendacion"
    ENVIAR_CONSEJO = "enviar_consejo"
    VOLVER_AL_COMITE = "volver_al_comite"
    APLAZAR = "aplazar"
    DECIDIR = "decidir"
    EXPEDIR = "expedir"
    NOTIFICAR = "notificar"
    ANULAR_NOTIFICACION = "anular_notificacion"
    ANULAR_EXPEDICION = "anular_expedicion"
    ARCHIVAR_DOCUMENTO = "archivar_documento"
    ARCHIVAR = "archivar"
    DESCARTAR = "descartar"


NOMBRE_ACCION: dict[Accion, str] = {
    Accion.REGISTRAR: "Llegó la solicitud",
    Accion.LECTURA_LISTA: "Lectura lista; pasa al comité",
    Accion.PRERREVISAR_PROCEDENTE: "Prerrevisión del programa: procedente",
    Accion.PRERREVISAR_IMPROCEDENTE: "Prerrevisión del programa: improcedente",
    Accion.PRERREVISAR_INCOMPLETO: "Prerrevisión del programa: incompleta",
    Accion.COMPLETAR: "Se completó la documentación",
    Accion.RECOMENDAR: "Recomendación del comité",
    Accion.QUITAR_RECOMENDACION: "Recomendación retirada (vuelve a pendiente)",
    Accion.ENVIAR_CONSEJO: "Oficio del comité al Consejo",
    Accion.VOLVER_AL_COMITE: "Vuelve al comité",
    Accion.APLAZAR: "El Consejo aplazó",
    Accion.DECIDIR: "Decisión del Consejo",
    Accion.EXPEDIR: "Expedición del acto (Secretaría)",
    Accion.NOTIFICAR: "Notificación al estudiante",
    Accion.ANULAR_NOTIFICACION: "Se corrigió: sin fecha de notificación",
    Accion.ANULAR_EXPEDICION: "Se corrigió: sin expedición",
    Accion.ARCHIVAR_DOCUMENTO: "Documento firmado archivado en Drive",
    Accion.ARCHIVAR: "Archivada",
    Accion.DESCARTAR: "Descartada",
}

# Roles de la web (app/api/web/auth.py) más «sistema». En Telegram, quien usa
# el bot de actas es la administrativa de su área.
ADMINISTRATIVA = "administrativa"
SECRETARIA = "secretaria"
ADMIN = "admin"
SISTEMA = "sistema"

NOMBRE_ROL: dict[str, str] = {
    ADMINISTRATIVA: "Administrativa del programa",
    SECRETARIA: "Secretaría de Facultad",
    ADMIN: "Administración de MemorIA",
    SISTEMA: "MemorIA (automático)",
    "comite": "Comité asesor",
}

_PRE_DECISION = frozenset(
    {
        Etapa.LLEGADA,
        Etapa.INCOMPLETA,
        Etapa.IMPROCEDENTE,
        Etapa.EN_COMITE,
        Etapa.RECOMENDADA,
        Etapa.EN_CONSEJO,
    }
)


@dataclass(frozen=True)
class Transicion:
    desde: frozenset[Etapa | None]
    hacia: Etapa | None  # None: se queda en la misma etapa (solo deja registro)
    roles: frozenset[str]


def transiciones(flujo: solicitudes.Flujo | None = None) -> dict[Accion, Transicion]:
    """La tabla completa. Depende solo de la sección `flujo` de
    config/solicitudes.yaml (decisiones de negocio configurables)."""
    flujo = flujo or solicitudes.actual().flujo
    adm = frozenset({ADMINISTRATIVA})
    acta = frozenset({ADMINISTRATIVA, ADMIN})
    sec = frozenset({SECRETARIA, ADMIN})
    al_comite: set[Etapa | None] = {Etapa.EN_COMITE, Etapa.RECOMENDADA}
    if not flujo.prerrevision_obligatoria:
        # Sin prerrevisión obligatoria el caso leído ya está ante el comité,
        # aunque la línea no haya registrado el paso (casos sin leer).
        al_comite.add(Etapa.LLEGADA)
    tabla = {
        Accion.REGISTRAR: Transicion(
            frozenset({None}), Etapa.LLEGADA, frozenset({ADMINISTRATIVA, SISTEMA})
        ),
        Accion.PRERREVISAR_PROCEDENTE: Transicion(
            frozenset({Etapa.LLEGADA, Etapa.INCOMPLETA, Etapa.EN_COMITE}),
            Etapa.EN_COMITE,
            adm,
        ),
        Accion.PRERREVISAR_IMPROCEDENTE: Transicion(
            frozenset({Etapa.LLEGADA, Etapa.INCOMPLETA, Etapa.EN_COMITE}),
            Etapa.EN_COMITE if flujo.improcedente_va_a_comite else Etapa.IMPROCEDENTE,
            adm,
        ),
        Accion.PRERREVISAR_INCOMPLETO: Transicion(
            frozenset({Etapa.LLEGADA, Etapa.EN_COMITE}), Etapa.INCOMPLETA, adm
        ),
        Accion.COMPLETAR: Transicion(frozenset({Etapa.INCOMPLETA}), Etapa.LLEGADA, adm),
        Accion.RECOMENDAR: Transicion(frozenset(al_comite), Etapa.RECOMENDADA, adm),
        Accion.QUITAR_RECOMENDACION: Transicion(
            frozenset({Etapa.RECOMENDADA}), Etapa.EN_COMITE, adm
        ),
        Accion.ENVIAR_CONSEJO: Transicion(
            frozenset({Etapa.RECOMENDADA}), Etapa.EN_CONSEJO, adm
        ),
        Accion.VOLVER_AL_COMITE: Transicion(
            frozenset({Etapa.EN_CONSEJO}), Etapa.RECOMENDADA, adm
        ),
        # La decisión sale del acta del Consejo, que manda sobre la línea: se
        # registra aunque falten pasos previos en MemorIA (quedan a la vista).
        Accion.APLAZAR: Transicion(frozenset(_PRE_DECISION), Etapa.EN_CONSEJO, acta),
        Accion.DECIDIR: Transicion(
            frozenset(_PRE_DECISION | {Etapa.DECIDIDA}), Etapa.DECIDIDA, acta
        ),
        Accion.EXPEDIR: Transicion(frozenset({Etapa.DECIDIDA}), Etapa.EXPEDIDA, sec),
        Accion.NOTIFICAR: Transicion(
            frozenset({Etapa.EXPEDIDA}), Etapa.NOTIFICADA, sec
        ),
        Accion.ANULAR_NOTIFICACION: Transicion(
            frozenset({Etapa.NOTIFICADA}), Etapa.EXPEDIDA, sec
        ),
        Accion.ANULAR_EXPEDICION: Transicion(
            frozenset({Etapa.EXPEDIDA}), Etapa.DECIDIDA, sec
        ),
        Accion.ARCHIVAR_DOCUMENTO: Transicion(frozenset({Etapa.EXPEDIDA}), None, sec),
        Accion.ARCHIVAR: Transicion(
            frozenset({Etapa.NOTIFICADA}), Etapa.ARCHIVADA, sec
        ),
        Accion.DESCARTAR: Transicion(
            frozenset(
                {
                    Etapa.LLEGADA,
                    Etapa.INCOMPLETA,
                    Etapa.IMPROCEDENTE,
                    Etapa.EN_COMITE,
                    Etapa.RECOMENDADA,
                }
            ),
            Etapa.DESCARTADA,
            adm,
        ),
    }
    if not flujo.prerrevision_obligatoria:
        tabla[Accion.LECTURA_LISTA] = Transicion(
            frozenset({Etapa.LLEGADA}), Etapa.EN_COMITE, frozenset({SISTEMA})
        )
    return tabla


class TransicionNoPermitida(Exception):
    """La acción no se puede hacer desde la etapa actual o con ese rol."""


@dataclass(frozen=True)
class Evento:
    accion: Accion
    desde: Etapa | None
    hacia: Etapa
    fecha: str | None  # None: la fecha no quedó registrada (casos anteriores)
    rol: str
    persona: str | None
    canal: str
    detalle: str | None = None
    registrado: str | None = None


# Valor por defecto de `fecha` en transicionar: el momento del registro.
AHORA = "__ahora__"


def ahora() -> str:
    """Mismo formato que CURRENT_TIMESTAMP de SQLite (UTC)."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Etapa derivada de los datos (casos anteriores a la línea única)
# ---------------------------------------------------------------------------


def _expedido(numero: object, fecha_expedicion: object) -> bool:
    return bool(numero) and bool(fecha_expedicion)


def derivar(
    *,
    estado: str,
    sentido: str,
    creado: str | None,
    recomendado: str | None,
    decision_sentido: str | None,
    acta_fecha: str | None,
    numero: str | None,
    fecha_expedicion: str | None,
    fecha_notificacion: str | None,
) -> list[Evento]:
    """Historia mínima que se deduce de lo guardado antes de la línea única.
    Lo que no tiene fecha guardada queda sin fecha: no se inventa."""

    def ev(
        accion: Accion, desde: Etapa | None, hacia: Etapa, fecha: str | None
    ) -> Evento:
        return Evento(accion, desde, hacia, fecha, SISTEMA, None, "migracion")

    eventos = [ev(Accion.REGISTRAR, None, Etapa.LLEGADA, creado)]
    if estado == EstadoCaso.DESCARTADO.value:
        eventos.append(ev(Accion.DESCARTAR, Etapa.LLEGADA, Etapa.DESCARTADA, None))
        return eventos
    etapa = Etapa.LLEGADA
    leidos = {
        EstadoCaso.LISTO.value,
        EstadoCaso.CERRADO.value,
        EstadoCaso.DECIDIDO_CONSEJO.value,
    }
    if estado in leidos:
        eventos.append(ev(Accion.LECTURA_LISTA, etapa, Etapa.EN_COMITE, None))
        etapa = Etapa.EN_COMITE
    if sentido != Sentido.PENDIENTE.value:
        eventos.append(ev(Accion.RECOMENDAR, etapa, Etapa.RECOMENDADA, recomendado))
        etapa = Etapa.RECOMENDADA
    if estado == EstadoCaso.CERRADO.value and etapa == Etapa.RECOMENDADA:
        eventos.append(ev(Accion.ENVIAR_CONSEJO, etapa, Etapa.EN_CONSEJO, None))
        etapa = Etapa.EN_CONSEJO
    if decision_sentido == SentidoConsejo.APLAZO.value:
        if etapa != Etapa.EN_CONSEJO:
            eventos.append(ev(Accion.APLAZAR, etapa, Etapa.EN_CONSEJO, acta_fecha))
        etapa = Etapa.EN_CONSEJO
    elif decision_sentido:
        eventos.append(ev(Accion.DECIDIR, etapa, Etapa.DECIDIDA, acta_fecha))
        etapa = Etapa.DECIDIDA
        if _expedido(numero, fecha_expedicion):
            eventos.append(ev(Accion.EXPEDIR, etapa, Etapa.EXPEDIDA, fecha_expedicion))
            etapa = Etapa.EXPEDIDA
            if fecha_notificacion:
                eventos.append(
                    ev(Accion.NOTIFICAR, etapa, Etapa.NOTIFICADA, fecha_notificacion)
                )
    return eventos


_SQL_DATOS = (
    "SELECT c.id, c.estado, c.sentido, c.creado, c.recomendado, c.etapa,"
    " d.sentido AS d_sentido, d.acta_fecha, n.numero, n.fecha_expedicion,"
    " n.fecha_notificacion"
    " FROM casos c LEFT JOIN decisiones_consejo d ON d.caso_id = c.id"
    " LEFT JOIN notificaciones n ON n.caso_id = c.id"
)


def _derivar_fila(r: Fila) -> list[Evento]:
    return derivar(
        estado=str(r["estado"]),
        sentido=str(r["sentido"]),
        creado=str(r["creado"]) if r["creado"] else None,
        recomendado=str(r["recomendado"]) if r["recomendado"] else None,
        decision_sentido=r["d_sentido"],
        acta_fecha=r["acta_fecha"],
        numero=r["numero"],
        fecha_expedicion=r["fecha_expedicion"],
        fecha_notificacion=r["fecha_notificacion"],
    )


async def _insertar(db: Conexion, caso_id: int, e: Evento) -> None:
    await db.execute(
        "INSERT INTO caso_eventos (caso_id, accion, desde, hacia, fecha, rol,"
        " persona, canal, detalle) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            caso_id,
            e.accion.value,
            e.desde.value if e.desde else None,
            e.hacia.value,
            e.fecha,
            e.rol,
            e.persona,
            e.canal,
            e.detalle,
        ),
    )


async def _materializar_fila(db: Conexion, r: Fila) -> Etapa:
    eventos = _derivar_fila(r)
    etapa = eventos[-1].hacia
    cur = await db.execute(
        "UPDATE casos SET etapa = ? WHERE id = ? AND etapa IS NULL",
        (etapa.value, int(r["id"])),
    )
    if cur.rowcount == 1:
        for e in eventos:
            await _insertar(db, int(r["id"]), e)
    return etapa


async def migrar(db: Conexion) -> int:
    """Idempotente: da etapa e historia a los casos que no la tienen. Corre al
    abrir la base (app/db/session.py). No hace commit."""
    cur = await db.execute(_SQL_DATOS + " WHERE c.etapa IS NULL ORDER BY c.id")
    n = 0
    for r in await cur.fetchall():
        await _materializar_fila(db, r)
        n += 1
    return n


async def etapa_de(db: Conexion, caso_id: int) -> Etapa:
    """La etapa actual. Si el caso aún no la tiene (se escribió por fuera de la
    línea), se deriva y se guarda en ese momento (sin commit)."""
    cur = await db.execute(_SQL_DATOS + " WHERE c.id = ?", (caso_id,))
    r = await cur.fetchone()
    if r is None:
        raise TransicionNoPermitida(f"No existe el caso #{caso_id}.")
    if r["etapa"]:
        return Etapa(r["etapa"])
    return await _materializar_fila(db, r)


# ---------------------------------------------------------------------------
# Transición
# ---------------------------------------------------------------------------


def puede(accion: Accion, etapa: Etapa | None, rol: str) -> bool:
    t = transiciones().get(accion)
    return t is not None and etapa in t.desde and rol in t.roles


def _motivo(accion: Accion, etapa: Etapa | None, rol: str) -> str:
    t = transiciones().get(accion)
    if t is None:
        return f"«{NOMBRE_ACCION[accion]}» no aplica con la configuración actual."
    if rol not in t.roles:
        quienes = ", ".join(NOMBRE_ROL.get(r, r) for r in sorted(t.roles))
        return f"«{NOMBRE_ACCION[accion]}» solo la puede hacer: {quienes}."
    actual = NOMBRE_ETAPA[etapa].lower() if etapa else "sin registrar"
    return f"No se puede «{NOMBRE_ACCION[accion].lower()}» con el caso en «{actual}»."


async def transicionar(
    db: Conexion,
    caso_id: int,
    accion: Accion,
    *,
    rol: str,
    persona: str | None,
    canal: str,
    fecha: str | None = AHORA,
    detalle: str | None = None,
    commit: bool = True,
) -> Etapa:
    """Valida y registra una transición. `fecha` es cuándo ocurrió (por
    defecto, ahora; None si no se sabe); se guarda aparte de cuándo se
    registró."""
    if rol == "comite":
        # Ninguna transición es del comité: recomienda en su sesión y la
        # administrativa registra esa recomendación. Nunca aprueba.
        raise TransicionNoPermitida(_motivo(accion, None, rol))
    if accion == Accion.REGISTRAR:
        cur = await db.execute("SELECT etapa FROM casos WHERE id = ?", (caso_id,))
        fila = await cur.fetchone()
        if fila is None or fila["etapa"] is not None:
            raise TransicionNoPermitida(
                f"El caso #{caso_id} ya está registrado en la línea."
            )
        etapa: Etapa | None = None
    else:
        etapa = await etapa_de(db, caso_id)
    if not puede(accion, etapa, rol):
        raise TransicionNoPermitida(_motivo(accion, etapa, rol))
    hacia = transiciones()[accion].hacia or etapa
    assert hacia is not None
    if etapa is not None:
        cur = await db.execute(
            "UPDATE casos SET etapa = ? WHERE id = ? AND etapa = ?",
            (hacia.value, caso_id, etapa.value),
        )
        if cur.rowcount != 1:
            raise TransicionNoPermitida(
                "El caso cambió mientras tanto. Recargue e intente de nuevo."
            )
    else:
        await db.execute(
            "UPDATE casos SET etapa = ? WHERE id = ?", (hacia.value, caso_id)
        )
    await _insertar(
        db,
        caso_id,
        Evento(
            accion,
            etapa,
            hacia,
            ahora() if fecha == AHORA else fecha,
            rol,
            persona,
            canal,
            detalle,
        ),
    )
    if commit:
        await db.commit()
    return hacia


# ---------------------------------------------------------------------------
# Operaciones que comparten Telegram y la web
# ---------------------------------------------------------------------------

_DETALLE_SENTIDO = {
    Sentido.APROBAR: "El comité recomienda APROBAR",
    Sentido.NO_APROBAR: "El comité recomienda NO APROBAR",
}


async def recomendar(
    db: Conexion,
    caso_id: int,
    sentido: Sentido,
    *,
    rol: str,
    persona: str | None,
    canal: str,
) -> None:
    """Registra lo que recomendó el comité (o lo vuelve a pendiente). La
    recomendación la decide el comité en su sesión; aquí solo se registra."""
    etapa = await etapa_de(db, caso_id)
    cur = await db.execute("SELECT sentido FROM casos WHERE id = ?", (caso_id,))
    fila = await cur.fetchone()
    previo = Sentido(fila["sentido"]) if fila else Sentido.PENDIENTE
    if sentido == Sentido.PENDIENTE:
        if etapa != Etapa.RECOMENDADA and previo == Sentido.PENDIENTE:
            if rol != ADMINISTRATIVA:
                raise TransicionNoPermitida(
                    _motivo(Accion.QUITAR_RECOMENDACION, etapa, rol)
                )
            return  # ya estaba pendiente: nada que registrar
        accion = Accion.QUITAR_RECOMENDACION
    else:
        accion = Accion.RECOMENDAR
        if etapa == Etapa.RECOMENDADA and previo == sentido and rol == ADMINISTRATIVA:
            return  # el mismo botón otra vez: no cambia nada
    if not puede(accion, etapa, rol):
        raise TransicionNoPermitida(_motivo(accion, etapa, rol))
    await repo.set_sentido(db, caso_id, sentido, commit=False)
    cur = await db.execute("SELECT recomendado FROM casos WHERE id = ?", (caso_id,))
    fila = await cur.fetchone()
    await transicionar(
        db,
        caso_id,
        accion,
        rol=rol,
        persona=persona,
        canal=canal,
        fecha=str(fila["recomendado"]) if fila and fila["recomendado"] else AHORA,
        detalle=_DETALLE_SENTIDO.get(sentido),
        commit=False,
    )
    await db.commit()


_ACCION_PRERREVISION = {
    Prerrevision.PROCEDENTE: Accion.PRERREVISAR_PROCEDENTE,
    Prerrevision.IMPROCEDENTE: Accion.PRERREVISAR_IMPROCEDENTE,
    Prerrevision.INCOMPLETO: Accion.PRERREVISAR_INCOMPLETO,
}


async def prerrevisar(
    db: Conexion,
    caso_id: int,
    resultado: Prerrevision,
    *,
    rol: str,
    persona: str | None,
    canal: str,
    nota: str | None = None,
) -> Etapa:
    """Prerrevisión del programa. No es una decisión sobre la solicitud: dice
    si el trámite procede, no procede o le falta documentación."""
    accion = _ACCION_PRERREVISION[resultado]
    etapa = await etapa_de(db, caso_id)
    if not puede(accion, etapa, rol):
        raise TransicionNoPermitida(_motivo(accion, etapa, rol))
    await repo.set_prerrevision(db, caso_id, resultado.value)
    hacia = await transicionar(
        db,
        caso_id,
        accion,
        rol=rol,
        persona=persona,
        canal=canal,
        detalle=(nota or "").strip()[:1500] or None,
        commit=False,
    )
    await db.commit()
    return hacia


async def completar(
    db: Conexion, caso_id: int, *, rol: str, persona: str | None, canal: str
) -> Etapa:
    return await transicionar(
        db, caso_id, Accion.COMPLETAR, rol=rol, persona=persona, canal=canal
    )


async def lectura_lista(db: Conexion, caso_id: int) -> None:
    """Al terminar la lectura, el caso pasa al comité si la prerrevisión no es
    obligatoria. Si ya avanzó por otra vía, no hace nada."""
    if await etapa_de(db, caso_id) != Etapa.LLEGADA:
        await db.commit()
        return
    if Accion.LECTURA_LISTA not in transiciones():
        await db.commit()
        return
    await transicionar(
        db,
        caso_id,
        Accion.LECTURA_LISTA,
        rol=SISTEMA,
        persona=None,
        canal=SISTEMA,
    )


async def enviar_consejo(
    db: Conexion,
    caso_ids: list[int],
    *,
    rol: str,
    persona: str | None,
    canal: str,
) -> list[int]:
    """El oficio del comité va al Consejo: los casos recomendados salen del
    borrador en curso. Devuelve los que pasaron a «en el Consejo»."""
    enviados: list[int] = []
    for caso_id in caso_ids:
        etapa = await etapa_de(db, caso_id)
        if etapa == Etapa.EN_CONSEJO:
            continue  # ya estaba (p. ej., aplazado): solo sale del borrador
        if not puede(Accion.ENVIAR_CONSEJO, etapa, rol):
            raise TransicionNoPermitida(_motivo(Accion.ENVIAR_CONSEJO, etapa, rol))
        await transicionar(
            db,
            caso_id,
            Accion.ENVIAR_CONSEJO,
            rol=rol,
            persona=persona,
            canal=canal,
            commit=False,
        )
        enviados.append(caso_id)
    await repo.cerrar_casos(db, caso_ids, commit=False)
    await db.commit()
    return enviados


async def volver_al_comite(
    db: Conexion, caso_id: int, *, rol: str, persona: str | None, canal: str
) -> None:
    await transicionar(
        db,
        caso_id,
        Accion.VOLVER_AL_COMITE,
        rol=rol,
        persona=persona,
        canal=canal,
        commit=False,
    )
    await repo.reabrir_en_borrador(db, caso_id)
    await db.commit()


async def descartar(
    db: Conexion, caso_id: int, *, rol: str, persona: str | None, canal: str
) -> None:
    """Descartar es para un caso registrado por error (no cuenta en las
    métricas). Una solicitud que no procede se marca improcedente."""
    await transicionar(
        db,
        caso_id,
        Accion.DESCARTAR,
        rol=rol,
        persona=persona,
        canal=canal,
        commit=False,
    )
    await repo.set_estado_caso(db, caso_id, EstadoCaso.DESCARTADO)


def accion_consejo(sentido: SentidoConsejo) -> Accion:
    return Accion.APLAZAR if sentido == SentidoConsejo.APLAZO else Accion.DECIDIR


async def validar_consejo(
    db: Conexion, caso_id: int, sentido: SentidoConsejo, rol: str
) -> None:
    accion = accion_consejo(sentido)
    etapa = await etapa_de(db, caso_id)
    if not puede(accion, etapa, rol):
        if etapa in (Etapa.EXPEDIDA, Etapa.NOTIFICADA, Etapa.ARCHIVADA):
            raise TransicionNoPermitida(
                f"El caso #{caso_id} ya tiene el acto expedido por la Secretaría: "
                "la decisión no se cambia en MemorIA."
            )
        raise TransicionNoPermitida(_motivo(accion, etapa, rol))


_SECUENCIA_SECRETARIA = (Accion.EXPEDIR, Accion.NOTIFICAR)
_ANULAR = {
    Accion.EXPEDIR: Accion.ANULAR_EXPEDICION,
    Accion.NOTIFICAR: Accion.ANULAR_NOTIFICACION,
}


def _cadena_secretaria(
    evs: list[Evento],
) -> tuple[list[tuple[Accion, str | None]], bool]:
    """Lo vigente después de la última decisión: expedición y notificación con
    sus fechas, y si ya se archivó el documento firmado."""
    cadena: list[tuple[Accion, str | None]] = []
    archivado = False
    for e in evs:
        if e.accion == Accion.DECIDIR:
            cadena, archivado = [], False
        elif e.accion in _SECUENCIA_SECRETARIA:
            cadena.append((e.accion, e.fecha))
        elif e.accion in (Accion.ANULAR_EXPEDICION, Accion.ANULAR_NOTIFICACION):
            if cadena:
                cadena.pop()
        elif e.accion in (Accion.ARCHIVAR_DOCUMENTO, Accion.ARCHIVAR):
            archivado = True
    return cadena, archivado


async def sincronizar_secretaria(
    db: Conexion,
    caso_id: int,
    *,
    numero: str | None,
    fecha_expedicion: str | None,
    fecha_notificacion: str | None,
    rol: str,
    persona: str | None,
) -> Etapa:
    """Lleva la línea a lo que la Secretaría registró: expedido (número y
    fecha de expedición) y notificado (fecha de notificación). Si corrige una
    fecha, la línea lo deja anotado (anula y vuelve a registrar). Sin commit."""
    deseada: list[tuple[Accion, str | None]] = []
    if _expedido(numero, fecha_expedicion):
        deseada.append((Accion.EXPEDIR, fecha_expedicion))
        if fecha_notificacion:
            deseada.append((Accion.NOTIFICAR, fecha_notificacion))
    etapa = await etapa_de(db, caso_id)
    actual, archivado = _cadena_secretaria(await eventos(db, caso_id))
    comun = 0
    while comun < min(len(actual), len(deseada)) and actual[comun] == deseada[comun]:
        comun += 1
    if etapa == Etapa.ARCHIVADA and (comun < len(actual) or comun < len(deseada)):
        raise TransicionNoPermitida(
            "El caso ya está archivado: sus fechas de expedición y notificación "
            "no se cambian."
        )
    for accion, _ in reversed(actual[comun:]):
        etapa = await transicionar(
            db,
            caso_id,
            _ANULAR[accion],
            rol=rol,
            persona=persona,
            canal="web",
            commit=False,
        )
    for accion, fecha in deseada[comun:]:
        etapa = await transicionar(
            db,
            caso_id,
            accion,
            rol=rol,
            persona=persona,
            canal="web",
            fecha=fecha,
            commit=False,
        )
    if etapa == Etapa.NOTIFICADA and archivado:
        etapa = await transicionar(
            db,
            caso_id,
            Accion.ARCHIVAR,
            rol=rol,
            persona=persona,
            canal="web",
            commit=False,
        )
    return etapa


async def archivar(
    db: Conexion, caso_id: int, *, rol: str, persona: str | None, detalle: str
) -> Etapa:
    """El oficio o la resolución firmados quedaron en Drive. Si el caso ya se
    notificó, queda archivado; si no, se anota y se archiva al notificar."""
    etapa = await etapa_de(db, caso_id)
    accion = Accion.ARCHIVAR if etapa == Etapa.NOTIFICADA else Accion.ARCHIVAR_DOCUMENTO
    return await transicionar(
        db, caso_id, accion, rol=rol, persona=persona, canal="web", detalle=detalle
    )


# ---------------------------------------------------------------------------
# Lectura: línea de tiempo, siguiente paso y tramos
# ---------------------------------------------------------------------------


async def eventos(db: Conexion, caso_id: int) -> list[Evento]:
    await etapa_de(db, caso_id)
    cur = await db.execute(
        "SELECT accion, desde, hacia, fecha, rol, persona, canal, detalle,"
        " registrado FROM caso_eventos WHERE caso_id = ? ORDER BY id",
        (caso_id,),
    )
    return [
        Evento(
            Accion(r["accion"]),
            Etapa(r["desde"]) if r["desde"] else None,
            Etapa(r["hacia"]),
            str(r["fecha"]) if r["fecha"] else None,
            str(r["rol"]),
            r["persona"],
            str(r["canal"]),
            r["detalle"],
            str(r["registrado"]) if r["registrado"] else None,
        )
        for r in await cur.fetchall()
    ]


@dataclass(frozen=True)
class Siguiente:
    paso: str
    responsable: str


def siguiente(
    etapa: Etapa,
    *,
    leido: bool,
    tipos: list[TipoSolicitud],
    instancia_decision: str | None = None,
) -> Siguiente | None:
    """El siguiente paso y quién lo hace. Solo describe: no decide nada."""
    config = solicitudes.actual()
    adm = "Administrativa del programa"
    if etapa == Etapa.LLEGADA:
        if not leido:
            return Siguiente("Leer el caso (correo y pantallazos del SIA)", adm)
        if config.flujo.prerrevision_obligatoria:
            return Siguiente(
                "Prerrevisión del programa: procedente, improcedente o incompleta",
                adm,
            )
        return Siguiente("Llevar el caso al comité asesor", adm)
    if etapa == Etapa.INCOMPLETA:
        return Siguiente("Completar la documentación y volver a prerrevisar", adm)
    if etapa == Etapa.EN_COMITE:
        return Siguiente(
            "Recomendación del comité: recomendar APROBAR o NO APROBAR",
            "Comité asesor (la registra la administrativa)",
        )
    if etapa == Etapa.RECOMENDADA:
        return Siguiente("Enviar el oficio del comité al Consejo", adm)
    if etapa == Etapa.EN_CONSEJO:
        decide = solicitudes.texto_decide(tipos)
        return Siguiente(
            f"Decisión del {decide}"
            if decide != "por confirmar"
            else "Decisión del Consejo (instancia por confirmar)",
            "El Consejo decide; la administrativa registra el acta en MemorIA",
        )
    if etapa == Etapa.DECIDIDA:
        if instancia_decision not in (None, "facultad"):
            return Siguiente(
                "Expedir y notificar el acto (por definir cuando decide el "
                "Consejo de Sede o el Superior)",
                "Por definir",
            )
        return Siguiente(
            "Expedir el oficio o la resolución (número y fecha)",
            "Secretaría de Facultad",
        )
    if etapa == Etapa.EXPEDIDA:
        return Siguiente("Notificar al estudiante (fecha)", "Secretaría de Facultad")
    if etapa == Etapa.NOTIFICADA:
        return Siguiente(
            "Archivar en Drive el oficio o la resolución firmados",
            "Secretaría de Facultad",
        )
    return None


def _zona() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def dia(valor: str | None) -> date | None:
    """Fecha local de un evento. Las fechas de día (acta, expedición) se
    toman tal cual; las marcas de tiempo vienen en UTC."""
    if not valor:
        return None
    if len(valor) == 10:
        try:
            return date.fromisoformat(valor)
        except ValueError:
            return None
    try:
        momento = datetime.fromisoformat(valor)
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return momento.astimezone(_zona()).date()


def _ultimo(evs: list[Evento], accion: Accion) -> Evento | None:
    return next((e for e in reversed(evs) if e.accion == accion), None)


def _fecha_solicitud(extraccion_json: str | None, llegada: date | None) -> date | None:
    """Misma regla de los indicadores: la fecha del correo si se leyó y no es
    posterior al registro; si no, la del registro."""
    leida: date | None = None
    if extraccion_json:
        try:
            datos = json.loads(extraccion_json)
            leida = date.fromisoformat(str(datos.get("fecha_solicitud") or "")[:10])
        except (ValueError, AttributeError):
            leida = None
    if leida is not None and llegada is not None and leida <= llegada:
        return leida
    return llegada


@dataclass(frozen=True)
class Tramo:
    nombre: str
    dias: int | None


def tramos(evs: list[Evento], extraccion_json: str | None = None) -> list[Tramo]:
    """Días por tramo, con las mismas convenciones de los indicadores. El
    principal es de la llegada a la decisión."""
    registro = _ultimo(evs, Accion.REGISTRAR)
    llegada = _fecha_solicitud(
        extraccion_json, dia(registro.fecha) if registro else None
    )
    # La recomendación vigente: la última, salvo que después se haya retirado.
    rec: date | None = None
    for e in evs:
        if e.accion == Accion.RECOMENDAR:
            rec = dia(e.fecha)
        elif e.accion == Accion.QUITAR_RECOMENDACION:
            rec = None
    dec_ev = _ultimo(evs, Accion.DECIDIR)
    decision = dia(dec_ev.fecha) if dec_ev else None
    notif_ev = _ultimo(evs, Accion.NOTIFICAR)
    notificacion = dia(notif_ev.fecha) if notif_ev else None

    def entre(a: date | None, b: date | None) -> int | None:
        return (b - a).days if a and b and b >= a else None

    return [
        Tramo("De la llegada a la decisión del Consejo", entre(llegada, decision)),
        Tramo("De la llegada a la recomendación del comité", entre(llegada, rec)),
        Tramo("De la recomendación a la decisión del Consejo", entre(rec, decision)),
        Tramo("De la decisión a la notificación", entre(decision, notificacion)),
    ]
