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

from app.core.conexion import Conexion, Fila
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
from app.services import flujo, formatos
from app.services.extraccion import get_estructurador

logger = logging.getLogger(__name__)

HERRAMIENTA = "registrar_acta"

# Casos que pueden aparecer en un acta del Consejo: ya tienen ficha.
_CANDIDATOS = (EstadoCaso.LISTO, EstadoCaso.CERRADO, EstadoCaso.DECIDIDO_CONSEJO)


class ErrorActa(Exception):
    """El acta no se pudo leer o la decisión no se pudo aplicar; el mensaje se
    muestra tal cual. `sin_cambios`: no se escribió nada, no hay que revertir
    (en una conexión compartida, revertir desharía lo de otra llamada)."""

    def __init__(self, mensaje: str, *, sin_cambios: bool = False) -> None:
        super().__init__(mensaje)
        self.sin_cambios = sin_cambios


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


# Rechazo explícito, palabra completa: «negociación», «negocio» o
# «rechazable» no son rechazos.
_RECHAZO = re.compile(
    r"\b(niegan?|negad[oa]s?|nego|negar|denieg(a|an)|denegad[oa]s?|denego|"
    r"denegar|rechaz(a|an|ad[oa]s?|o|ar)|improbad[oa]s?|desaprueb(a|an)|"
    r"desaprobad[oa]s?|improcedentes?)\b|\bno\s+(es\s+)?procede"
)
_APLAZO = re.compile(r"\b(aplaz|pospon|pospus)")
_VERBO_APROBAR = re.compile(r"^(aprob|aprueb|autoriz|conced|avala|aval[oó])")
_NEGADORES = {"no", "ni", "nunca", "tampoco", "sin"}
# Cuántas palabras antes del verbo puede estar la negación de su cláusula
# («no se le aprueba», «no ha sido autorizada»).
_VENTANA_NEGACION = 4


def sentido_de(texto_decision: str) -> SentidoConsejo:
    """Del texto literal al sentido, con una regla fija. Una negación nunca
    da «aprobó»: si niega el verbo es «no aprobó»; si hay una negación que no
    se puede atar al verbo, es ambiguo y queda «otro», con su texto."""
    t = normalizar(texto_decision)
    palabras = re.findall(r"[a-zñ]+", t)
    hay_negacion = any(p in _NEGADORES for p in palabras)
    if _APLAZO.search(t):
        return SentidoConsejo.OTRO if hay_negacion else SentidoConsejo.APLAZO
    rechazo = _RECHAZO.search(t) is not None
    verbos = [i for i, p in enumerate(palabras) if _VERBO_APROBAR.match(p)]
    for i in verbos:
        if any(p in _NEGADORES for p in palabras[max(0, i - _VENTANA_NEGACION) : i]):
            return SentidoConsejo.NO_APROBO
    if rechazo:
        # «Se aprueba el recurso contra el rechazo anterior»: aprobar y
        # rechazo juntos, sin negar el verbo, es ambiguo.
        return SentidoConsejo.OTRO if verbos else SentidoConsejo.NO_APROBO
    if not verbos:
        return SentidoConsejo.OTRO
    return SentidoConsejo.OTRO if hay_negacion else SentidoConsejo.APROBO


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


def _numeros(fragmento: str) -> set[str]:
    """Números del fragmento, con o sin puntos de miles (1.000.000.001)."""
    return {_digitos(m.group()) for m in re.finditer(r"\d(?:[\d.]*\d)?", fragmento)}


def _documento_en(documento: str, fragmento: str) -> bool:
    return bool(documento) and documento in _numeros(fragmento)


def _caso_en(numero: str, fragmento: str) -> bool:
    """El número de caso aparece como «caso … 12» o «#12»."""
    if not numero:
        return False
    patron = rf"(\bcaso\b[^\d]{{0,20}}|#\s*)0*{int(numero)}(?!\d)"
    return re.search(patron, normalizar(fragmento)) is not None


def _nombre_en(nombre: str | None, fragmento: str) -> bool:
    tokens = _tokens_nombre(nombre)
    return bool(tokens) and set(tokens) <= set(_tokens_nombre(fragmento))


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

    # Un identificador solo se usa si está en el fragmento: el modelo pudo
    # tomarlo de otra fila del acta.
    doc = _digitos(d.documento)
    num = _digitos(d.numero_caso)
    nombre = _clave_nombre(d.nombre_estudiante)
    ausentes = []
    if doc and not _documento_en(doc, d.fragmento):
        ausentes.append("el documento")
        doc = ""
    if num and not _caso_en(num, d.fragmento):
        ausentes.append("el número de caso")
        num = ""
    if nombre and not _nombre_en(d.nombre_estudiante, d.fragmento):
        ausentes.append("el nombre")
        nombre = ""
    if ausentes and not (doc or num or nombre):
        return Propuesta(
            d,
            sentido,
            Cruce.NO_VERIFICADO,
            f"El fragmento no contiene {' ni '.join(ausentes)} del estudiante.",
        )
    nota_ausentes = (
        f"El fragmento no contiene {' ni '.join(ausentes)} que leyó el modelo."
    )

    def doc_de(c: Caso) -> str:
        return _digitos(c.extraccion.documento if c.extraccion else None)

    def nombre_de(c: Caso) -> str:
        return _clave_nombre(c.extraccion.nombre_estudiante if c.extraccion else None)

    por_doc = {c.id for c in casos if doc and doc_de(c) == doc}
    por_num = {c.id for c in casos if num and str(c.id) == num.lstrip("0")}
    por_nombre = {c.id for c in casos if nombre and nombre_de(c) == nombre}
    union = por_doc | por_num | por_nombre

    if not union:
        propios = set(_tokens_nombre(d.nombre_estudiante if nombre else None))
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
    if ausentes:
        return Propuesta(d, sentido, Cruce.DUDOSO, nota_ausentes, candidatos=(caso_id,))
    caso = next(c for c in casos if c.id == caso_id)
    if caso.sentido == Sentido.PENDIENTE:
        return Propuesta(
            d,
            sentido,
            Cruce.DUDOSO,
            f"El caso #{caso_id} no tiene recomendación del comité registrada.",
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


async def _casos_candidatos(db: Conexion, direccion: str | None) -> list[Caso]:
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


async def decision_de(db: Conexion, caso_id: int) -> DecisionConsejo | None:
    return await repo.decision_consejo(db, caso_id)


async def _decididos(db: Conexion) -> dict[int, SentidoConsejo]:
    cur = await db.execute("SELECT caso_id, sentido FROM decisiones_consejo")
    return {int(r[0]): SentidoConsejo(r[1]) for r in await cur.fetchall()}


@dataclass(frozen=True)
class ActaRegistrada:
    acta_id: int
    propuestas: list[Propuesta] = field(default_factory=list)


async def registrar_acta(
    db: Conexion,
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
    db: Conexion,
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
    if len(texto) > settings.acta_consejo_max_caracteres:
        raise ErrorActa(
            f"El acta tiene {len(texto):,} caracteres y el máximo es "
            f"{settings.acta_consejo_max_caracteres:,}. Suba solo la sección de "
            "asuntos estudiantiles, o divídala en partes.".replace(",", ".")
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
        if resultado.error and "incompleta" in resultado.error:
            # stop_reason == "max_tokens": la lista de decisiones quedó cortada.
            raise ErrorActa(
                "El acta es demasiado larga para leerla de una vez: la lectura "
                "quedó cortada y se perderían decisiones. No se registró nada. "
                "Suba la sección de asuntos estudiantiles en partes."
            )
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


async def get_acta(db: Conexion, acta_id: int) -> Acta | None:
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


def _fila(r: Fila) -> FilaDecision:
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


async def decisiones_del_acta(db: Conexion, acta_id: int) -> list[FilaDecision]:
    cur = await db.execute(
        "SELECT * FROM acta_consejo_decisiones WHERE acta_id = ? ORDER BY orden",
        (acta_id,),
    )
    return [_fila(r) for r in await cur.fetchall()]


async def _get_fila(db: Conexion, decision_id: int) -> FilaDecision | None:
    cur = await db.execute(
        "SELECT * FROM acta_consejo_decisiones WHERE id = ?", (decision_id,)
    )
    r = await cur.fetchone()
    return _fila(r) if r else None


async def texto_acta(db: Conexion, acta_id: int) -> str:
    cur = await db.execute("SELECT texto FROM actas_consejo WHERE id = ?", (acta_id,))
    r = await cur.fetchone()
    return str(r[0]) if r else ""


def asignable_a_mano(fila: FilaDecision, texto: str) -> bool:
    """Una decisión sin verificar se puede asignar a mano si lo que se
    registraría es literal: el fragmento está en el acta y la decisión en el
    fragmento. Solo faltó verificar a quién se refiere."""
    return (
        fila.cruce == Cruce.NO_VERIFICADO
        and es_literal(fila.leida.fragmento, texto)
        and es_literal(fila.leida.texto_decision, fila.leida.fragmento)
    )


async def fila_visible(
    db: Conexion, fila: FilaDecision, acta: Acta, direccion: str | None
) -> bool:
    """Quien no es admin solo ve y toca las decisiones cuyo caso o candidatos
    son de su área. Una decisión sin caso ni candidatos solo la ve el área que
    subió el acta (en un acta subida por admin, solo admin)."""
    if direccion is None:
        return True
    if acta.direccion not in (None, direccion):
        return False
    ids = ({fila.caso_id} if fila.caso_id else set()) | set(fila.candidatos)
    if not ids:
        return acta.direccion == direccion
    marcas = ",".join("?" for _ in ids)
    cur = await db.execute(
        f"SELECT 1 FROM casos WHERE id IN ({marcas}) AND direccion = ? LIMIT 1",
        (*ids, direccion),
    )
    return await cur.fetchone() is not None


async def _fila_de_su_area(
    db: Conexion, decision_id: int, direccion: str | None
) -> tuple[FilaDecision, Acta]:
    fila = await _get_fila(db, decision_id)
    acta = await get_acta(db, fila.acta_id) if fila else None
    if (
        fila is None
        or acta is None
        or not await fila_visible(db, fila, acta, direccion)
    ):
        raise ErrorActa("No encontré esa decisión en su área.")
    if fila.estado != EstadoDecision.PENDIENTE:
        raise ErrorActa("Esa decisión ya se revisó.")
    return fila, acta


async def _tomar(
    db: Conexion,
    fila_id: int,
    estado: EstadoDecision,
    persona: str,
    caso_id: int | None = None,
) -> None:
    """Pasa la decisión de pendiente a revisada en una sola sentencia: si dos
    clics llegan a la vez, solo uno la toma."""
    cur = await db.execute(
        "UPDATE acta_consejo_decisiones SET estado = ?, "
        "caso_id = COALESCE(?, caso_id), revisado_por = ?, "
        "revisado = CURRENT_TIMESTAMP WHERE id = ? AND estado = ?",
        (estado.value, caso_id, persona, fila_id, EstadoDecision.PENDIENTE.value),
    )
    if cur.rowcount != 1:
        # Es la primera escritura de esta llamada: nada que revertir.
        raise ErrorActa("Esa decisión ya se revisó.", sin_cambios=True)


async def aplicar(
    db: Conexion,
    decision_id: int,
    *,
    caso_id: int | None,
    persona: str,
    direccion: str | None,
    reemplazar: bool = False,
    rol: str = "administrativa",
    canal: str = "web",
) -> DecisionConsejo:
    """Registra en el caso la decisión del acta. Solo la llama una persona
    (botón o pantalla). `direccion` es el alcance de quien confirma (None:
    todas las áreas). Un caso dudoso exige que la persona elija el caso. Una
    decisión final ya registrada solo se reemplaza con `reemplazar`, y nunca
    por un aplazamiento."""
    fila, acta = await _fila_de_su_area(db, decision_id, direccion)
    if fila.cruce == Cruce.NO_VERIFICADO and not (
        caso_id is not None and asignable_a_mano(fila, await texto_acta(db, acta.id))
    ):
        raise ErrorActa(
            "La decisión no se pudo verificar contra el texto del acta: no se "
            "puede registrar. Descártela y revise el acta."
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
    previa = await repo.decision_consejo(db, caso.id)
    if previa is not None and previa.sentido != SentidoConsejo.APLAZO:
        if fila.sentido == SentidoConsejo.APLAZO:
            raise ErrorActa(
                f"El caso #{caso.id} ya tiene una decisión del Consejo "
                f"({ETIQUETA_SENTIDO_CONSEJO[previa.sentido].lower()}); un "
                "aplazamiento no la reemplaza."
            )
        if not reemplazar:
            raise ErrorActa(
                f"El caso #{caso.id} ya tiene una decisión del Consejo "
                f"({ETIQUETA_SENTIDO_CONSEJO[previa.sentido].lower()}, acta "
                f"{previa.acta_numero or 'sin número'}). Confirme que quiere "
                "reemplazarla."
            )
    # La línea única (app/services/flujo.py) dice si el caso admite la decisión.
    try:
        await flujo.validar_consejo(db, caso.id, fila.sentido, rol)
    except flujo.TransicionNoPermitida as exc:
        await db.rollback()  # pudo materializar la etapa; no se guarda nada
        raise ErrorActa(str(exc)) from exc
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
    try:
        await _tomar(db, fila.id, EstadoDecision.APLICADA, persona, caso.id)
        await _guardar_decision(db, decision, acta.id, fila.id, reemplazar)
        # Un aplazamiento no es decisión: el caso sigue en su estado y en curso.
        if decision.sentido != SentidoConsejo.APLAZO:
            await db.execute(
                "UPDATE casos SET estado = ?, actualizado = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (EstadoCaso.DECIDIDO_CONSEJO.value, caso.id),
            )
        # La fecha del hecho es la de la sesión que consta en el acta.
        await flujo.transicionar(
            db,
            caso.id,
            flujo.accion_consejo(decision.sentido),
            rol=rol,
            persona=persona,
            canal=canal,
            fecha=acta.fecha or None,
            detalle=texto_decision(decision),
            commit=False,
        )
        await db.commit()
    except flujo.TransicionNoPermitida as exc:
        await db.rollback()
        raise ErrorActa(str(exc)) from exc
    except ErrorActa as exc:
        if not exc.sin_cambios:
            await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    await avisar(db, caso, decision)
    return decision


async def _guardar_decision(
    db: Conexion,
    decision: DecisionConsejo,
    acta_id: int,
    fila_id: int,
    reemplazar: bool,
) -> None:
    """Inserta la decisión. La condición sobre la previa va en la misma
    sentencia: si otra confirmación registró una decisión final entre la
    lectura y la escritura, no se pisa."""
    cur = await db.execute(
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
        WHERE decisiones_consejo.sentido = 'aplazo'
            OR (? = 1 AND excluded.sentido != 'aplazo')
        """,
        (
            decision.caso_id,
            acta_id,
            fila_id,
            decision.instancia.value,
            decision.sentido.value,
            decision.texto_decision,
            decision.acta_numero,
            decision.acta_fecha,
            decision.fragmento,
            decision.confirmado_por,
            reemplazar,
        ),
    )
    if cur.rowcount != 1:
        raise ErrorActa(
            f"El caso #{decision.caso_id} ya tiene una decisión del Consejo. "
            "Confirme que quiere reemplazarla."
        )


async def descartar(
    db: Conexion,
    decision_id: int,
    *,
    persona: str,
    direccion: str | None,
) -> None:
    fila, _ = await _fila_de_su_area(db, decision_id, direccion)
    await _tomar(db, fila.id, EstadoDecision.DESCARTADA, persona)
    await db.commit()


async def aplicar_exactos(
    db: Conexion,
    acta_id: int,
    *,
    persona: str,
    direccion: str | None,
    rol: str = "administrativa",
    canal: str = "web",
) -> list[DecisionConsejo]:
    """Confirma de una vez los cruces exactos pendientes (botón explícito)."""
    aplicadas = []
    for fila in await decisiones_del_acta(db, acta_id):
        if fila.cruce != Cruce.EXACTO or fila.estado != EstadoDecision.PENDIENTE:
            continue
        try:
            aplicadas.append(
                await aplicar(
                    db,
                    fila.id,
                    caso_id=None,
                    persona=persona,
                    direccion=direccion,
                    rol=rol,
                    canal=canal,
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


async def avisar(db: Conexion, caso: Caso, d: DecisionConsejo) -> int:
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
    db: Conexion, acta_id: int, direccion: str | None
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
