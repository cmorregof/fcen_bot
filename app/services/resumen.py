"""Resumen para la decanatura (Decana y vicedecanos): /resumen y envío semanal.

Solo lectura y solo cifras: casos por programa y por estado, los más antiguos
sin movimiento y alertas. Nunca nombres ni documentos de estudiantes.

El comité asesor solo recomienda; decide el Consejo de Facultad (o el de Sede
o el Superior), y lo que decide sale de su acta. Un caso recomendado sigue
«pendiente de acta del Consejo» hasta que una persona confirma en MemorIA la
decisión que consta en el acta (aprobó, no aprobó u otra). Un aplazamiento no
es una decisión: el caso sigue pendiente y se cuenta aparte.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite
import httpx

from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.integrations import telegram
from app.schemas.caso import EstadoCaso, Sentido
from app.schemas.consejo import NOMBRE_INSTANCIA, Instancia, SentidoConsejo

logger = logging.getLogger(__name__)

AYUDA = (
    "Este bot le envía a la decanatura un resumen de los casos estudiantiles de "
    "los comités asesores: cifras por programa y por estado, sin nombres.\n\n"
    "/resumen — el resumen ahora\n"
    "/indicadores [periodo] — tiempos de respuesta y decisiones del Consejo, "
    "con Excel (periodo: 2026-10, 2026 o vacío para el periodo en curso)\n"
    "Cada lunes en la mañana llega solo."
)

_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
# Casos que siguen en manos de las áreas (sin cerrar el acta del comité).
_ACTIVOS = (
    EstadoCaso.ABIERTO,
    EstadoCaso.PROCESANDO,
    EstadoCaso.ERROR,
    EstadoCaso.LISTO,
)
_SIN_PROGRAMA = "Sin programa asignado"
_MAS_ANTIGUOS = 3


def es_decanatura(telegram_id: int) -> bool:
    return telegram_id in settings.ids_decanatura


def es_admin(telegram_id: int) -> bool:
    return telegram_id in settings.ids_admin


def puede_ver_indicadores(telegram_id: int) -> bool:
    """/indicadores: decanatura y administradores (ADMIN_TELEGRAM_IDS)."""
    return es_decanatura(telegram_id) or es_admin(telegram_id)


@dataclass
class Conteo:
    recibidos: int = 0
    en_preparacion: int = 0
    recomendar_aprobar: int = 0
    recomendar_no_aprobar: int = 0
    # Según el acta del Consejo, confirmado por una persona.
    consejo_aprobo: int = 0
    consejo_no_aprobo: int = 0
    consejo_aplazo: int = 0
    consejo_otro: int = 0
    # Recomendados con decisión del Consejo (sin contar los aplazados).
    recomendados_decididos: int = 0

    @property
    def recomendados(self) -> int:
        return self.recomendar_aprobar + self.recomendar_no_aprobar

    @property
    def decididos_consejo(self) -> int:
        return self.consejo_aprobo + self.consejo_no_aprobo + self.consejo_otro

    @property
    def pendientes_acta_consejo(self) -> int:
        # Sin decisión confirmada desde el acta, la recomendación sigue pendiente.
        return self.recomendados - self.recomendados_decididos


@dataclass(frozen=True)
class SinMovimiento:
    caso_id: int
    programa: str
    etapa: str
    dias: int


@dataclass
class ActaSemana:
    """Decisiones confirmadas en la semana desde una misma acta del Consejo."""

    instancia: str
    numero: str | None
    fecha: str | None
    conteo: dict[SentidoConsejo, int] = field(default_factory=dict)


@dataclass
class CifrasActas:
    total: Conteo = field(default_factory=Conteo)
    por_programa: dict[str, Conteo] = field(default_factory=dict)
    mas_antiguos: list[SinMovimiento] = field(default_factory=list)
    sin_movimiento: int = 0
    con_error: int = 0
    sin_programa: int = 0
    actas_semana: list[ActaSemana] = field(default_factory=list)


def _etapa(estado: EstadoCaso, sentido: Sentido) -> str:
    if estado == EstadoCaso.ERROR:
        return "no se pudo leer"
    if estado in (EstadoCaso.ABIERTO, EstadoCaso.PROCESANDO):
        return "recibido, sin ficha"
    if sentido == Sentido.PENDIENTE:
        return "esperando al comité"
    return "recomendado, sin cerrar el acta del comité"


def _fecha(valor: object) -> datetime:
    # SQLite guarda CURRENT_TIMESTAMP en UTC, como «AAAA-MM-DD HH:MM:SS».
    return datetime.fromisoformat(str(valor)).replace(tzinfo=UTC)


async def cifras_actas(db: aiosqlite.Connection, ahora: datetime) -> CifrasActas:
    """Conteos de los casos del periodo y de los que siguen en curso."""
    inicio = settings.periodo_inicio.isoformat() if settings.periodo_inicio else ""
    cur = await db.execute(
        "SELECT c.id, c.programa, c.estado, c.sentido, c.actualizado, d.sentido"
        " FROM casos c LEFT JOIN decisiones_consejo d ON d.caso_id = c.id"
        " WHERE c.estado != ? AND (c.creado >= ? OR c.estado IN (?, ?, ?, ?))",
        (EstadoCaso.DESCARTADO.value, inicio, *(e.value for e in _ACTIVOS)),
    )
    cifras = CifrasActas()
    activos: list[SinMovimiento] = []
    for fila in await cur.fetchall():
        caso_id, programa, estado_txt, sentido_txt, actualizado, consejo_txt = fila
        estado, sentido = EstadoCaso(estado_txt), Sentido(sentido_txt)
        consejo = SentidoConsejo(consejo_txt) if consejo_txt else None
        nombre = PROGRAMAS[programa].nombre if programa in PROGRAMAS else _SIN_PROGRAMA
        for c in (cifras.total, cifras.por_programa.setdefault(nombre, Conteo())):
            c.recibidos += 1
            if sentido == Sentido.APROBAR:
                c.recomendar_aprobar += 1
            elif sentido == Sentido.NO_APROBAR:
                c.recomendar_no_aprobar += 1
            elif estado in _ACTIVOS:
                c.en_preparacion += 1
            if consejo == SentidoConsejo.APROBO:
                c.consejo_aprobo += 1
            elif consejo == SentidoConsejo.NO_APROBO:
                c.consejo_no_aprobo += 1
            elif consejo == SentidoConsejo.APLAZO:
                c.consejo_aplazo += 1
            elif consejo == SentidoConsejo.OTRO:
                c.consejo_otro += 1
            if (
                consejo not in (None, SentidoConsejo.APLAZO)
                and sentido != Sentido.PENDIENTE
            ):
                c.recomendados_decididos += 1
        if estado not in _ACTIVOS:
            continue
        dias = max(0, (ahora - _fecha(actualizado)).days)
        activos.append(SinMovimiento(caso_id, nombre, _etapa(estado, sentido), dias))
        if dias > settings.resumen_dias_sin_movimiento:
            cifras.sin_movimiento += 1
        if estado == EstadoCaso.ERROR:
            cifras.con_error += 1
        if programa not in PROGRAMAS:
            cifras.sin_programa += 1
    activos.sort(key=lambda s: (-s.dias, s.caso_id))
    cifras.mas_antiguos = [s for s in activos if s.dias > 0][:_MAS_ANTIGUOS]
    cifras.actas_semana = await actas_de_la_semana(db, ahora)
    return cifras


async def actas_de_la_semana(
    db: aiosqlite.Connection, ahora: datetime
) -> list[ActaSemana]:
    """Decisiones del Consejo confirmadas en MemorIA en los últimos 7 días,
    por acta (instancia, número y fecha). Solo conteos."""
    desde = (ahora - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    cur = await db.execute(
        "SELECT instancia, acta_numero, acta_fecha, sentido, COUNT(*)"
        " FROM decisiones_consejo WHERE confirmado >= ?"
        " GROUP BY instancia, acta_numero, acta_fecha, sentido"
        " ORDER BY acta_fecha, acta_numero",
        (desde,),
    )
    actas: dict[tuple[str, str | None, str | None], ActaSemana] = {}
    for instancia, numero, fecha, sentido, n in await cur.fetchall():
        try:
            nombre = NOMBRE_INSTANCIA[Instancia(instancia)]
        except ValueError:
            nombre = str(instancia)
        acta = actas.setdefault(
            (nombre, numero, fecha), ActaSemana(nombre, numero, fecha)
        )
        acta.conteo[SentidoConsejo(sentido)] = int(n)
    return list(actas.values())


# ---------------------------------------------------------------------------
# Otros servicios: solo sus conteos agregados, por /internal/cifras
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Externo:
    linea: str
    alertas: tuple[str, ...] = ()


def _n(valor: object) -> int:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else 0


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def linea_calidad(datos: dict[str, Any]) -> Externo:
    total = datos.get("total")
    t = total if isinstance(total, dict) else {}
    acciones = sum(_n(v) for v in t.values())
    vencidas, no_funciono = _n(t.get("vencida")), _n(t.get("no funcionó"))
    linea = (
        f"Calidad, plan de mejoramiento: {_plural(acciones, 'acción', 'acciones')} · "
        f"{_n(t.get('cumplida'))} cumplidas · {_n(t.get('en curso'))} en curso · "
        f"{vencidas} vencidas · {_n(datos.get('reprogramadas'))} reprogramadas"
    )
    alertas = []
    if vencidas:
        alertas.append(
            f"Calidad: {_plural(vencidas, 'acción vencida', 'acciones vencidas')} "
            "en el plan de mejoramiento."
        )
    if no_funciono:
        alertas.append(
            f"Calidad: {_plural(no_funciono, 'acción marcada', 'acciones marcadas')} "
            "«no funcionó»."
        )
    return Externo(linea, tuple(alertas))


def linea_admision(datos: dict[str, Any]) -> Externo:
    total = datos.get("total")
    t = total if isinstance(total, dict) else {}
    sin_respuesta = _n(t.get("preguntas_sin_respuesta"))
    linea = (
        f"Admisión: {_n(t.get('documentos_revisados'))} documentos revisados · "
        f"{_n(t.get('documentos_con_errores'))} con errores · "
        f"{sin_respuesta} preguntas sin respuesta"
    )
    alertas: tuple[str, ...] = ()
    if sin_respuesta:
        alertas = (
            f"Admisión: {_plural(sin_respuesta, 'pregunta', 'preguntas')} de "
            "admitidos sin respuesta.",
        )
    return Externo(linea, alertas)


async def _pedir(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            url.rstrip("/") + "/internal/cifras",
            headers={"X-Resumen-Secret": settings.resumen_secret},
        )
    resp.raise_for_status()
    datos = resp.json()
    if not isinstance(datos, dict):
        raise ValueError("respuesta inesperada")
    return datos


async def externos() -> list[Externo]:
    """Una línea por servicio configurado. Si no responde, se dice así."""
    if not settings.resumen_secret:
        return []
    salida: list[Externo] = []
    for url, nombre, armar in (
        (settings.resumen_calidad_url, "Calidad", linea_calidad),
        (settings.resumen_admision_url, "Admisión", linea_admision),
    ):
        if not url:
            continue
        try:
            salida.append(armar(await _pedir(url)))
        except Exception:
            logger.exception("No pude pedir las cifras de %s", nombre)
            salida.append(Externo(f"{nombre}: sin datos (el servicio no respondió)."))
    return salida


# ---------------------------------------------------------------------------
# Mensaje
# ---------------------------------------------------------------------------


def _fecha_larga(d: date) -> str:
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


def _detalle(c: Conteo) -> str:
    texto = (
        f"{c.recibidos} recibidos · {c.en_preparacion} en preparación · "
        f"{c.recomendados} recomendados por el comité · "
        f"{c.pendientes_acta_consejo} pendientes de acta del Consejo"
    )
    if c.decididos_consejo:
        texto += f" · {c.decididos_consejo} decididos por el Consejo"
    return texto


def _consejo(c: Conteo) -> str:
    return (
        f"Según el acta del Consejo: aprobó {c.consejo_aprobo}, no aprobó "
        f"{c.consejo_no_aprobo}, aplazó {c.consejo_aplazo}"
        + (f", otra decisión {c.consejo_otro}" if c.consejo_otro else "")
        + "."
    )


def _linea_acta(a: ActaSemana) -> str:
    acta = f"acta {a.numero}" if a.numero else "acta sin número"
    fecha = f" del {a.fecha}" if a.fecha else ""
    c = a.conteo
    texto = (
        f"• {escape(a.instancia)}, {escape(acta)}{escape(fecha)}: aprobó "
        f"{c.get(SentidoConsejo.APROBO, 0)}, no aprobó "
        f"{c.get(SentidoConsejo.NO_APROBO, 0)}, aplazó "
        f"{c.get(SentidoConsejo.APLAZO, 0)}"
    )
    if c.get(SentidoConsejo.OTRO):
        texto += f", otra decisión {c[SentidoConsejo.OTRO]}"
    return texto + "."


def formatear(
    cifras: CifrasActas, hoy: date, otros: list[Externo] | None = None
) -> str:
    otros = otros or []
    t = cifras.total
    lineas = [
        "<b>Resumen de casos estudiantiles</b>",
        f"Comités asesores · {_fecha_larga(hoy)} · periodo "
        f"{escape(settings.periodo_actual)}",
        "",
    ]
    if not t.recibidos:
        lineas.append("No hay casos registrados en el periodo.")
    else:
        lineas += [
            f"<b>Total</b>: {_detalle(t)}",
            f"De los recomendados: {t.recomendar_aprobar} recomendar aprobar, "
            f"{t.recomendar_no_aprobar} recomendar no aprobar.",
        ]
        if t.decididos_consejo or t.consejo_aplazo:
            lineas.append(_consejo(t))
        lineas += [
            "",
            "<b>Por programa</b>",
        ]
        orden = sorted(
            cifras.por_programa.items(), key=lambda kv: (kv[0] == _SIN_PROGRAMA, kv[0])
        )
        lineas += [f"• {escape(n)}: {_detalle(c)}" for n, c in orden]
    if cifras.actas_semana:
        lineas += ["", "<b>Actas del Consejo registradas esta semana</b>"]
        lineas += [_linea_acta(a) for a in cifras.actas_semana]
    if cifras.mas_antiguos:
        lineas += ["", "<b>Más antiguos sin movimiento</b>"]
        lineas += [
            f"• {escape(s.programa)}, caso #{s.caso_id}: "
            f"{_plural(s.dias, 'día', 'días')} ({s.etapa})"
            for s in cifras.mas_antiguos
        ]

    alertas: list[str] = []
    if cifras.sin_movimiento:
        alertas.append(
            f"{_plural(cifras.sin_movimiento, 'caso lleva', 'casos llevan')} más de "
            f"{settings.resumen_dias_sin_movimiento} días sin movimiento."
        )
    if cifras.con_error:
        alertas.append(
            f"{_plural(cifras.con_error, 'caso no se pudo', 'casos no se pudieron')} "
            "leer y espera a que el área lo revise."
        )
    if cifras.sin_programa:
        alertas.append(
            f"{_plural(cifras.sin_programa, 'caso', 'casos')} sin programa asignado."
        )
    for o in otros:
        alertas += o.alertas
    lineas += ["", "<b>Atención</b>"]
    lineas += [f"• {escape(a)}" for a in alertas] if alertas else ["Sin alertas."]

    if otros:
        lineas += ["", "<b>Otros servicios</b>"]
        lineas += [f"• {escape(o.linea)}" for o in otros]

    lineas += [
        "",
        "<i>El comité asesor solo recomienda; decide el Consejo de Facultad. "
        "Mientras su decisión no conste en el acta del Consejo, el caso figura "
        "como pendiente de acta del Consejo y no como aprobado.</i>",
    ]
    return "\n".join(lineas)


def _ahora() -> datetime:
    return datetime.now(UTC)


async def armar(db: aiosqlite.Connection) -> str:
    ahora = _ahora()
    hoy = ahora.astimezone(ZoneInfo(settings.timezone)).date()
    return formatear(await cifras_actas(db, ahora), hoy, await externos())


async def enviar_a(ids: Iterable[int], texto: str) -> int:
    """Envía el mismo texto a cada id. Un envío fallido no detiene a los demás.
    Devuelve cuántos salieron. Lo usan el resumen semanal y el reporte mensual."""
    enviados = 0
    for chat_id in sorted(set(ids)):
        try:
            await telegram.send_message(chat_id, texto)
            enviados += 1
        except Exception:
            logger.exception("No pude enviar el mensaje a %s", chat_id)
    return enviados


async def enviar_semanal(db: aiosqlite.Connection) -> dict[str, object]:
    """Para el cron del lunes."""
    if not settings.resumen_semanal_activo:
        return {"activo": False, "enviados": 0}
    ids = sorted(settings.ids_decanatura)
    if not ids:
        return {"activo": True, "enviados": 0}
    enviados = await enviar_a(ids, await armar(db))
    return {"activo": True, "enviados": enviados, "destinatarios": len(ids)}
