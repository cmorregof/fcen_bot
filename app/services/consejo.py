"""Acta del Consejo: lectura, cruce con los casos de MemorIA y confirmación.

1. El modelo copia del acta cada decisión con su texto literal y los
   identificadores que aparezcan (`ActaLeida`). Cada fragmento se comprueba
   contra el texto del acta: si no está literal, la decisión no se puede
   aplicar.
2. El sentido (aprobó, no aprobó, aplazó, otro) sale del texto literal con
   una regla fija, no del modelo.
3. El cruce es determinista: número de caso, documento y nombre. Lo que no
   cruza con certeza queda en la cola de revisión con sus candidatos; no se
   adivina.
4. Nada se registra en un caso hasta que una persona lo confirma. Sin acta, el
   caso sigue «pendiente de acta del Consejo».
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from html import escape

import aiosqlite

from app.core.config import settings
from app.core.programas import PROGRAMAS, normalizar
from app.db import repo
from app.integrations import telegram
from app.integrations.claude import validar
from app.prompts.consejo import SISTEMA_ACTA_CONSEJO, mensaje_acta
from app.schemas.caso import Caso, EstadoCaso, Sentido
from app.schemas.consejo import (
    ETIQUETA_SENTIDO_CONSEJO,
    NOMBRE_INSTANCIA,
    ActaLeida,
    Cruce,
    DecisionConsejo,
    DecisionLeida,
    EstadoDecision,
    Instancia,
    SentidoConsejo,
)
from app.services import formatos
from app.services.extraccion import get_estructurador

logger = logging.getLogger(__name__)

HERRAMIENTA = "registrar_acta"

# Casos que pueden aparecer en un acta del Consejo: ya tienen ficha.
_CANDIDATOS = (EstadoCaso.LISTO, EstadoCaso.CERRADO, EstadoCaso.DECIDIDO_CONSEJO)


class ErrorActa(Exception):
    """El acta no se pudo leer; el mensaje se muestra tal cual."""


# ---------------------------------------------------------------------------
# Reglas fijas
# ---------------------------------------------------------------------------


def _espacios(texto: str) -> str:
    return " ".join(texto.split())


def es_literal(fragmento: str, texto_acta: str) -> bool:
    """El fragmento es una subcadena exacta del acta. Solo se toleran
    diferencias de espacios y saltos de línea (el PDF los reparte para alinear
    columnas); letras, tildes, mayúsculas y signos deben ser idénticos."""
    buscado = _espacios(fragmento)
    return bool(buscado) and buscado in _espacios(texto_acta)


_NO_APROBO = re.compile(
    r"\bno\s+(se\s+)?(aprob|aprueb|autoriz|conced|avala)|\b(niega|negad|deneg|"
    r"rechaz)"
)
_APLAZO = re.compile(r"\b(aplaz|pospon|pospus)")
_APROBO = re.compile(r"\b(aprob|aprueb|autoriz|conced|avala)")


def sentido_de(texto_decision: str) -> SentidoConsejo:
    """Del texto literal al sentido, con palabras clave. Lo que no encaja es
    «otro» y se muestra con su texto."""
    t = normalizar(texto_decision)
    if _APLAZO.search(t):
        return SentidoConsejo.APLAZO
    if _NO_APROBO.search(t):
        return SentidoConsejo.NO_APROBO
    if _APROBO.search(t):
        return SentidoConsejo.APROBO
    return SentidoConsejo.OTRO


def instancia_de(texto: str | None) -> Instancia | None:
    """«Consejo de Facultad … Sede Manizales» es Facultad: se busca el nombre
    completo del cuerpo, no la palabra «sede» suelta."""
    t = normalizar(texto or "")
    if "consejo superior" in t:
        return Instancia.SUPERIOR
    if "consejo de sede" in t:
        return Instancia.SEDE
    if "consejo de facultad" in t:
        return Instancia.FACULTAD
    return None


def _digitos(texto: str | None) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


def _tokens_nombre(nombre: str | None) -> list[str]:
    limpio = re.sub(r"[^a-zñ ]", " ", normalizar(nombre or ""))
    return [t for t in limpio.split() if len(t) > 2]


def _clave_nombre(nombre: str | None) -> str:
    return " ".join(sorted(_tokens_nombre(nombre)))


# ---------------------------------------------------------------------------
# Cruce
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Propuesta:
    leida: DecisionLeida
    sentido: SentidoConsejo
    cruce: Cruce
    motivo: str | None = None
    caso_id: int | None = None
    candidatos: tuple[int, ...] = ()


def _cruzar_una(
    d: DecisionLeida,
    casos: list[Caso],
    texto_acta: str,
    decididos: dict[int, SentidoConsejo],
) -> Propuesta:
    sentido = sentido_de(d.texto_decision)
    if not es_literal(d.fragmento, texto_acta):
        return Propuesta(
            d,
            sentido,
            Cruce.NO_VERIFICADO,
            "El fragmento no aparece literal en el acta.",
        )
    if not es_literal(d.texto_decision, d.fragmento):
        return Propuesta(
            d,
            sentido,
            Cruce.NO_VERIFICADO,
            "El texto de la decisión no está dentro del fragmento citado.",
        )

    doc = _digitos(d.documento)
    num = _digitos(d.numero_caso)
    nombre = _clave_nombre(d.nombre_estudiante)

    def doc_de(c: Caso) -> str:
        return _digitos(c.extraccion.documento if c.extraccion else None)

    def nombre_de(c: Caso) -> str:
        return _clave_nombre(c.extraccion.nombre_estudiante if c.extraccion else None)

    por_doc = {c.id for c in casos if doc and doc_de(c) == doc}
    por_num = {c.id for c in casos if num and str(c.id) == num.lstrip("0")}
    por_nombre = {c.id for c in casos if nombre and nombre_de(c) == nombre}
    union = por_doc | por_num | por_nombre

    if not union:
        propios = set(_tokens_nombre(d.nombre_estudiante))
        parecidos = tuple(
            sorted(
                c.id
                for c in casos
                if len(
                    propios
                    & set(
                        _tokens_nombre(
                            c.extraccion.nombre_estudiante if c.extraccion else None
                        )
                    )
                )
                >= 2
            )
        )
        if parecidos:
            return Propuesta(
                d,
                sentido,
                Cruce.DUDOSO,
                "Solo coincide parte del nombre.",
                candidatos=parecidos,
            )
        return Propuesta(d, sentido, Cruce.SIN_CASO, "Ningún caso de MemorIA coincide.")

    if len(union) > 1:
        return Propuesta(
            d,
            sentido,
            Cruce.DUDOSO,
            "Varios casos coinciden con los datos del acta.",
            candidatos=tuple(sorted(union)),
        )

    caso_id = next(iter(union))
    conflictos = []
    if doc and caso_id not in por_doc:
        conflictos.append("el documento")
    if num and caso_id not in por_num:
        conflictos.append("el número de caso")
    if nombre and caso_id not in por_nombre:
        conflictos.append("el nombre")
    if conflictos:
        return Propuesta(
            d,
            sentido,
            Cruce.DUDOSO,
            f"No coincide {' ni '.join(conflictos)} del acta con el caso #{caso_id}.",
            candidatos=(caso_id,),
        )
    if caso_id not in por_doc and caso_id not in por_num:
        return Propuesta(
            d,
            sentido,
            Cruce.DUDOSO,
            "Solo coincide el nombre: el acta no trae documento ni número de caso.",
            candidatos=(caso_id,),
        )
    previo = decididos.get(caso_id)
    if previo is not None and previo != SentidoConsejo.APLAZO:
        return Propuesta(
            d,
            sentido,
            Cruce.DUDOSO,
            f"El caso #{caso_id} ya tiene una decisión del Consejo "
            f"({ETIQUETA_SENTIDO_CONSEJO[previo].lower()}).",
            candidatos=(caso_id,),
        )
    return Propuesta(d, sentido, Cruce.EXACTO, caso_id=caso_id, candidatos=(caso_id,))


def cruzar(
    leidas: list[DecisionLeida],
    casos: list[Caso],
    texto_acta: str,
    decididos: dict[int, SentidoConsejo] | None = None,
) -> list[Propuesta]:
    """Cruce determinista. Dos decisiones que apuntan al mismo caso van ambas
    a la cola."""
    propuestas = [_cruzar_una(d, casos, texto_acta, decididos or {}) for d in leidas]
    exactos: dict[int, int] = {}
    for p in propuestas:
        if p.cruce == Cruce.EXACTO and p.caso_id is not None:
            exactos[p.caso_id] = exactos.get(p.caso_id, 0) + 1
    salida = []
    for p in propuestas:
        if p.cruce == Cruce.EXACTO and p.caso_id and exactos[p.caso_id] > 1:
            p = Propuesta(
                p.leida,
                p.sentido,
                Cruce.DUDOSO,
                f"Varias decisiones del acta apuntan al caso #{p.caso_id}.",
                candidatos=(p.caso_id,),
            )
        salida.append(p)
    return salida


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------


async def _casos_candidatos(
    db: aiosqlite.Connection, direccion: str | None
) -> list[Caso]:
    marcas = ",".join("?" for _ in _CANDIDATOS)
    sql = f"SELECT id FROM casos WHERE estado IN ({marcas})"
    params: list[object] = [e.value for e in _CANDIDATOS]
    if direccion is not None:
        sql += " AND direccion = ?"
        params.append(direccion)
    cur = await db.execute(sql + " ORDER BY id", params)
    casos = []
    for (caso_id,) in await cur.fetchall():
        caso = await repo.get_caso(db, int(caso_id))
        if caso is not None and caso.extraccion is not None:
            casos.append(caso)
    return casos


async def decision_de(db: aiosqlite.Connection, caso_id: int) -> DecisionConsejo | None:
    return await repo.decision_consejo(db, caso_id)


async def _decididos(db: aiosqlite.Connection) -> dict[int, SentidoConsejo]:
    cur = await db.execute("SELECT caso_id, sentido FROM decisiones_consejo")
    return {int(r[0]): SentidoConsejo(r[1]) for r in await cur.fetchall()}


@dataclass(frozen=True)
class ActaRegistrada:
    acta_id: int
    propuestas: list[Propuesta] = field(default_factory=list)


async def registrar_acta(
    db: aiosqlite.Connection,
    *,
    leida: ActaLeida,
    texto: str,
    direccion: str | None,
    instancia: Instancia | None,
    archivo_nombre: str | None,
    subido_por: str,
) -> ActaRegistrada:
    """Guarda el acta y su cruce. No toca ningún caso."""
    instancia = instancia or instancia_de(leida.instancia_texto) or Instancia.FACULTAD
    numero = leida.numero_acta if es_literal(leida.numero_acta or "", texto) else None
    casos = await _casos_candidatos(db, direccion)
    propuestas = cruzar(leida.decisiones, casos, texto, await _decididos(db))
    cur = await db.execute(
        "INSERT INTO actas_consejo (direccion, instancia, numero, fecha, "
        "archivo_nombre, texto, subido_por) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            direccion,
            instancia.value,
            numero,
            leida.fecha_acta,
            archivo_nombre,
            texto,
            subido_por,
        ),
    )
    assert cur.lastrowid is not None
    acta_id = int(cur.lastrowid)
    for orden, p in enumerate(propuestas, 1):
        await db.execute(
            "INSERT INTO acta_consejo_decisiones (acta_id, orden, leida_json, "
            "sentido, cruce, motivo, candidatos, caso_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                acta_id,
                orden,
                p.leida.model_dump_json(),
                p.sentido.value,
                p.cruce.value,
                p.motivo,
                json.dumps(list(p.candidatos)),
                p.caso_id,
            ),
        )
    await db.commit()
    return ActaRegistrada(acta_id, propuestas)


async def leer_y_registrar(
    db: aiosqlite.Connection,
    *,
    datos: bytes,
    nombre_archivo: str,
    direccion: str | None,
    instancia: Instancia | None,
    subido_por: str,
) -> ActaRegistrada:
    """Del archivo (PDF o DOCX) al acta registrada con su cruce."""
    extension = "." + nombre_archivo.rsplit(".", 1)[-1].lower()
    if extension not in formatos.EXTENSIONES:
        raise ErrorActa("El acta debe ser un PDF o un Word (.docx).")
    if len(datos) > formatos.MAX_BYTES:
        raise ErrorActa("El acta pesa más de 20 MB.")
    texto = await formatos.texto_de_archivo(datos, extension)
    if not texto.strip():
        raise ErrorActa(
            "No pude leer texto en el acta. Si es un PDF escaneado, pida la "
            "versión digital (PDF con texto o Word)."
        )
    estructurador = get_estructurador()
    if estructurador is None:
        raise ErrorActa("Falta configurar ANTHROPIC_API_KEY.")
    resultado = await estructurador.extraer(
        sistema=SISTEMA_ACTA_CONSEJO,
        texto=mensaje_acta(texto),
        imagenes=[],
        modelo_salida=ActaLeida,
        nombre_herramienta=HERRAMIENTA,
        modelo=settings.extraction_model,
        max_tokens=settings.acta_consejo_max_tokens,
    )
    await repo.registrar_uso(
        db,
        caso_id=None,
        operacion="acta_consejo",
        modelo=settings.extraction_model,
        input_tokens=resultado.input_tokens,
        output_tokens=resultado.output_tokens,
    )
    leida = validar(resultado, ActaLeida)
    if leida is None:
        raise ErrorActa(f"No pude leer el acta: {resultado.error or 'sin resultado'}.")
    return await registrar_acta(
        db,
        leida=leida,
        texto=texto,
        direccion=direccion,
        instancia=instancia,
        archivo_nombre=nombre_archivo,
        subido_por=subido_por,
    )


# ---------------------------------------------------------------------------
# Confirmación: lo único que escribe en los casos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Acta:
    id: int
    direccion: str | None
    instancia: Instancia
    numero: str | None
    fecha: str | None
    archivo_nombre: str | None
    subido_por: str
    creado: str | None


async def get_acta(db: aiosqlite.Connection, acta_id: int) -> Acta | None:
    cur = await db.execute("SELECT * FROM actas_consejo WHERE id = ?", (acta_id,))
    r = await cur.fetchone()
    if r is None:
        return None
    return Acta(
        int(r["id"]),
        r["direccion"],
        Instancia(r["instancia"]),
        r["numero"],
        r["fecha"],
        r["archivo_nombre"],
        r["subido_por"],
        str(r["creado"]) if r["creado"] else None,
    )


@dataclass(frozen=True)
class FilaDecision:
    id: int
    acta_id: int
    orden: int
    leida: DecisionLeida
    sentido: SentidoConsejo
    cruce: Cruce
    motivo: str | None
    candidatos: tuple[int, ...]
    caso_id: int | None
    estado: EstadoDecision
    revisado_por: str | None


def _fila(r: aiosqlite.Row) -> FilaDecision:
    return FilaDecision(
        id=int(r["id"]),
        acta_id=int(r["acta_id"]),
        orden=int(r["orden"]),
        leida=DecisionLeida.model_validate_json(r["leida_json"]),
        sentido=SentidoConsejo(r["sentido"]),
        cruce=Cruce(r["cruce"]),
        motivo=r["motivo"],
        candidatos=tuple(int(i) for i in json.loads(r["candidatos"] or "[]")),
        caso_id=int(r["caso_id"]) if r["caso_id"] is not None else None,
        estado=EstadoDecision(r["estado"]),
        revisado_por=r["revisado_por"],
    )


async def decisiones_del_acta(
    db: aiosqlite.Connection, acta_id: int
) -> list[FilaDecision]:
    cur = await db.execute(
        "SELECT * FROM acta_consejo_decisiones WHERE acta_id = ? ORDER BY orden",
        (acta_id,),
    )
    return [_fila(r) for r in await cur.fetchall()]


async def _get_fila(db: aiosqlite.Connection, decision_id: int) -> FilaDecision | None:
    cur = await db.execute(
        "SELECT * FROM acta_consejo_decisiones WHERE id = ?", (decision_id,)
    )
    r = await cur.fetchone()
    return _fila(r) if r else None


async def aplicar(
    db: aiosqlite.Connection,
    decision_id: int,
    *,
    caso_id: int | None,
    persona: str,
    direccion: str | None,
) -> DecisionConsejo:
    """Registra en el caso la decisión del acta. Solo la llama una persona
    (botón o pantalla). `direccion` es el alcance de quien confirma (None:
    todas las áreas). Un caso dudoso exige que la persona elija el caso."""
    fila = await _get_fila(db, decision_id)
    if fila is None:
        raise ErrorActa("No encontré esa decisión.")
    acta = await get_acta(db, fila.acta_id)
    assert acta is not None
    if direccion is not None and acta.direccion not in (None, direccion):
        raise ErrorActa("Esa acta no es de su área.")
    if fila.estado != EstadoDecision.PENDIENTE:
        raise ErrorActa("Esa decisión ya se revisó.")
    if fila.cruce == Cruce.NO_VERIFICADO:
        raise ErrorActa(
            "El fragmento no aparece literal en el acta: no se puede registrar. "
            "Descártela y revise el acta."
        )
    elegido = caso_id if caso_id is not None else fila.caso_id
    if elegido is None:
        raise ErrorActa("Elija el caso al que corresponde la decisión.")
    caso = await repo.get_caso(db, elegido)
    alcance = direccion or acta.direccion
    if (
        caso is None
        or caso.estado not in _CANDIDATOS
        or (alcance is not None and caso.direccion != alcance)
    ):
        raise ErrorActa(f"El caso #{elegido} no está disponible en su área.")
    decision = DecisionConsejo(
        caso_id=caso.id,
        instancia=acta.instancia,
        sentido=fila.sentido,
        texto_decision=fila.leida.texto_decision,
        acta_numero=acta.numero,
        acta_fecha=acta.fecha,
        fragmento=fila.leida.fragmento,
        confirmado_por=persona,
    )
    await db.execute(
        """
        INSERT INTO decisiones_consejo (caso_id, acta_id, decision_id, instancia,
            sentido, texto_decision, acta_numero, acta_fecha, fragmento,
            confirmado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(caso_id) DO UPDATE SET
            acta_id = excluded.acta_id, decision_id = excluded.decision_id,
            instancia = excluded.instancia, sentido = excluded.sentido,
            texto_decision = excluded.texto_decision,
            acta_numero = excluded.acta_numero, acta_fecha = excluded.acta_fecha,
            fragmento = excluded.fragmento,
            confirmado_por = excluded.confirmado_por,
            confirmado = CURRENT_TIMESTAMP
        """,
        (
            caso.id,
            acta.id,
            fila.id,
            decision.instancia.value,
            decision.sentido.value,
            decision.texto_decision,
            decision.acta_numero,
            decision.acta_fecha,
            decision.fragmento,
            persona,
        ),
    )
    await db.execute(
        "UPDATE casos SET estado = ?, actualizado = CURRENT_TIMESTAMP WHERE id = ?",
        (EstadoCaso.DECIDIDO_CONSEJO.value, caso.id),
    )
    await db.execute(
        "UPDATE acta_consejo_decisiones SET estado = ?, caso_id = ?, "
        "revisado_por = ?, revisado = CURRENT_TIMESTAMP WHERE id = ?",
        (EstadoDecision.APLICADA.value, caso.id, persona, fila.id),
    )
    await db.commit()
    await avisar(db, caso, decision)
    return decision


async def descartar(
    db: aiosqlite.Connection,
    decision_id: int,
    *,
    persona: str,
    direccion: str | None,
) -> None:
    fila = await _get_fila(db, decision_id)
    if fila is None:
        raise ErrorActa("No encontré esa decisión.")
    acta = await get_acta(db, fila.acta_id)
    assert acta is not None
    if direccion is not None and acta.direccion not in (None, direccion):
        raise ErrorActa("Esa acta no es de su área.")
    if fila.estado != EstadoDecision.PENDIENTE:
        raise ErrorActa("Esa decisión ya se revisó.")
    await db.execute(
        "UPDATE acta_consejo_decisiones SET estado = ?, revisado_por = ?, "
        "revisado = CURRENT_TIMESTAMP WHERE id = ?",
        (EstadoDecision.DESCARTADA.value, persona, fila.id),
    )
    await db.commit()


async def aplicar_exactos(
    db: aiosqlite.Connection, acta_id: int, *, persona: str, direccion: str | None
) -> list[DecisionConsejo]:
    """Confirma de una vez los cruces exactos pendientes (botón explícito)."""
    aplicadas = []
    for fila in await decisiones_del_acta(db, acta_id):
        if fila.cruce != Cruce.EXACTO or fila.estado != EstadoDecision.PENDIENTE:
            continue
        try:
            aplicadas.append(
                await aplicar(
                    db, fila.id, caso_id=None, persona=persona, direccion=direccion
                )
            )
        except ErrorActa:
            continue  # sigue en la cola para revisarla a mano
    return aplicadas


# ---------------------------------------------------------------------------
# Aviso a cada programa
# ---------------------------------------------------------------------------


def texto_decision(d: DecisionConsejo) -> str:
    acta = " ".join(
        x
        for x in (
            f"Acta {d.acta_numero}" if d.acta_numero else "Acta",
            f"del {d.acta_fecha}" if d.acta_fecha else "",
        )
        if x
    )
    return (
        f"{NOMBRE_INSTANCIA[d.instancia]}: "
        f"{ETIQUETA_SENTIDO_CONSEJO[d.sentido].lower()} ({acta}). "
        f"«{d.texto_decision}»"
    )


async def avisar(db: aiosqlite.Connection, caso: Caso, d: DecisionConsejo) -> int:
    """Mensaje al chat del área del caso. Apagado salvo AVISO_CONSEJO_TELEGRAM."""
    if not settings.aviso_consejo_telegram:
        return 0
    programa = PROGRAMAS[caso.programa].nombre if caso.programa in PROGRAMAS else ""
    nombre = caso.extraccion.nombre_estudiante if caso.extraccion else None
    mensaje = (
        f"<b>Decisión del Consejo · caso #{caso.id}</b>\n"
        f"{escape(nombre or '')}{' · ' + escape(programa) if programa else ''}\n"
        f"{escape(texto_decision(d))}"
    )
    enviados = 0
    for usuario in await repo.usuarios_de(db, caso.direccion):
        try:
            await telegram.send_message(usuario.telegram_id, mensaje)
            enviados += 1
        except Exception:
            logger.exception("No pude avisar la decisión del caso #%s", caso.id)
    return enviados


# ---------------------------------------------------------------------------
# Vista de revisión
# ---------------------------------------------------------------------------


async def no_aparecieron(
    db: aiosqlite.Connection, acta_id: int, direccion: str | None
) -> list[Caso]:
    """Casos recomendados por el comité, sin decisión final del Consejo, que no
    aparecen en ninguna decisión del acta (ni como candidatos)."""
    filas = await decisiones_del_acta(db, acta_id)
    vistos = {f.caso_id for f in filas if f.caso_id} | {
        i for f in filas for i in f.candidatos
    }
    decididos = await _decididos(db)
    salida = []
    for caso in await _casos_candidatos(db, direccion):
        if caso.sentido == Sentido.PENDIENTE or caso.id in vistos:
            continue
        previo = decididos.get(caso.id)
        if previo is not None and previo != SentidoConsejo.APLAZO:
            continue
        salida.append(caso)
    return salida
