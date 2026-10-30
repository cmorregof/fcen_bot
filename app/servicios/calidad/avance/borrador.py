"""Borrador de la descripción de avance de un corte, por acción.

El modelo PROPONE frases; cada frase cita sus fuentes ([P1], [C1], [E1],
[S012]). Un verificador determinista comprueba las citas contra el catálogo de
la acción (`fuentes`): la frase sin cita válida, o con un nombre de persona, no
entra al texto propuesto: se muestra aparte, marcada, y no se afirma.

Si la acción no tiene evidencia nueva en el corte, el borrador lo dice sin
preguntarle nada al modelo. Calidad revisa y aprueba; el modelo no decide.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.servicios.calidad.avance.fuentes import (
    PATRON_CITA,
    AccionCorte,
    Fuente,
    citas_en_texto,
    con_nombre_de_persona,
    ocultar,
)
from app.servicios.calidad.soportes.cliente import ClienteConTope, ClienteModelo
from app.servicios.calidad.soportes.describir import Cache
from app.servicios.calidad.soportes.modelos import PRECIOS_USD_POR_MILLON, Uso

MODELO_AVANCE = "claude-sonnet-5-5"
VERSION_PROMPT = "avance-v1"
SIN_EVIDENCIA_NUEVA = "Sin evidencia nueva en el corte."

# Supuestos de la estimación (tokens). Son holgados a propósito.
TOKENS_FIJOS = 1500  # sistema + herramienta
SALIDA = 3000  # incluye razonamiento
CARACTERES_POR_TOKEN = 3

MOTIVO_SIN_CITA = "no cita ninguna fuente"
MOTIVO_CITA_INVALIDA = "cita una fuente que no existe para esta acción"
MOTIVO_NOMBRE = "menciona a una persona; use solo el cargo o la dependencia"
MOTIVO_CITAS_NO_COINCIDEN = "las citas del campo no coinciden con las del texto"
MOTIVO_DATO_SIN_FUENTE = (
    "trae cifras, fechas o enlaces que no están en las fuentes que cita"
)
MOTIVO_SOLO_CONTEXTO = (
    "solo cita la acción en el plan (contexto): no respalda ese hecho"
)
# Lo que queda de una frase que nombraba a una persona: ni la salida ni la
# caché guardan el texto original.
OMITIDA = "[frase omitida: menciona a una persona]"

SISTEMA = """Eres asistente de la oficina de calidad académica de una facultad \
universitaria. Redactas una PROPUESTA de la descripción de avance de una acción \
de un plan de mejoramiento en un corte semestral, para el informe de \
autoevaluación. La oficina de calidad la revisa y la aprueba, la edita o la \
descarta; el Comité Asesor recomienda y el Consejo de Facultad decide. Tú no \
decides si la acción se cumplió.

Reglas:
- Usa solo las fuentes numeradas que se te dan. No supongas hechos que no están.
- Cada frase termina citando sus fuentes con su ID entre corchetes, p. ej. \
[P2] o [P2, E1], y el campo `citas` repite esos mismos IDs. Cita solo IDs de la \
lista. Una frase sin cita no se usa.
- Las cifras, fechas y enlaces de una frase deben aparecer tal cual en las fuentes \
que cita; si no están, no los escribas. [P1] solo da el % declarado: no respalda \
que algo se haya hecho.
- [P] es el plan y el cronograma; [C] es lo escrito en un corte anterior; [E] es \
un enlace registrado: solo prueba que el enlace existe, no sabes qué contiene; \
[S] es la descripción de un soporte: di «según la descripción del soporte».
- Las fuentes marcadas «(nueva en este corte)» son lo que cambió desde el corte \
anterior. Lo escrito en cortes anteriores no se repite como avance nuevo.
- No inventes cifras, fechas ni asistentes. No cambies el % de avance declarado \
y no propongas otro.
- Si algo no tiene soporte, dilo: «No se evidencia…» y cita la fuente que lo \
esperaba. No lo des por hecho.
- Tercera persona, tono institucional, 3 a 6 frases cortas, en español.
- No escribas nombres de personas, correos ni teléfonos: usa solo el cargo o la \
dependencia (la dirección del programa, el Comité Asesor).
Registra tu propuesta con la herramienta `registrar_avance`."""


class FraseAvance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: str = Field(description="Una frase, terminada con sus citas [ID].")
    citas: list[str] = Field(description="IDs de las fuentes citadas, p. ej. P2.")


class AvanceAccion(BaseModel):
    """Propuesta del modelo para una acción. Una persona la revisa."""

    model_config = ConfigDict(extra="forbid")

    frases: list[FraseAvance]


@dataclass
class FraseVerificada:
    texto: str
    citas: list[str]  # IDs válidos
    motivo: str = ""  # vacío si pasó el verificador

    @property
    def valida(self) -> bool:
        return not self.motivo


@dataclass
class AccionBorrador:
    base: AccionCorte
    frases: list[FraseVerificada] = field(default_factory=list)
    sin_evidencia_nueva: bool = False
    error: str = ""

    @property
    def parrafo(self) -> str:
        return " ".join(f.texto for f in self.frases if f.valida)

    @property
    def rechazadas(self) -> list[FraseVerificada]:
        return [f for f in self.frases if not f.valida]

    @property
    def citas(self) -> list[str]:
        vistas: list[str] = []
        for f in self.frases:
            for c in f.citas:
                if f.valida and c not in vistas:
                    vistas.append(c)
        return vistas

    @property
    def alertas(self) -> list[str]:
        salida = []
        if self.error:
            salida.append(f"Sin propuesta del modelo: {self.error}")
        if self.rechazadas:
            salida.append(
                f"{len(self.rechazadas)} frase(s) sin fuente verificada: no se afirman."
            )
        return salida


@dataclass
class Borrador:
    programa: str
    corte: str  # ISO
    acciones: list[AccionBorrador]
    uso: Uso = field(default_factory=Uso)
    detenido: str = ""

    def resumen(self) -> dict[str, object]:
        """Cifras, sin texto del plan ni nombres."""
        return {
            "acciones": len(self.acciones),
            "sin_evidencia_nueva": sum(a.sin_evidencia_nueva for a in self.acciones),
            "con_propuesta": sum(
                1 for a in self.acciones if not a.sin_evidencia_nueva and a.parrafo
            ),
            "sin_propuesta": sum(1 for a in self.acciones if a.error),
            "frases_rechazadas": sum(len(a.rechazadas) for a in self.acciones),
            "costo_usd": round(self.uso.costo(), 2),
            "detenido": self.detenido,
        }


# ---------------------------------------------------------------------------
# Texto para el modelo y verificación
# ---------------------------------------------------------------------------


def texto_para_modelo(ac: AccionCorte) -> str:
    a = ac.accion
    partes = [
        f"Corte que se describe: {ac.corte.isoformat()}. "
        f"Corte anterior: {ac.anterior or 'ninguno registrado'}.",
        f"Objetivo: {ac.objetivo_texto}",
        f"Acción {a.codigo}: {ac.descripcion}",
        f"Indicador de cumplimiento: {ac.indicador}",
        "",
        "Fuentes (cita solo estas):",
    ]
    for f in ac.fuentes:
        marca = " (nueva en este corte)" if f.nueva else ""
        partes.append(f"[{f.id}]{marca} {f.texto}")
    partes += ["", "Redacta la propuesta de descripción de avance de esta acción."]
    return "\n".join(partes)


_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_PORCENTAJE = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
_URL = re.compile(r"https?://[^\s)\]]+")


def _numeros(texto: str) -> set[str]:
    """Cifras de un texto, sin ceros a la izquierda ni coma decimal."""
    salida: set[str] = set()
    for n in _NUMERO.findall(texto):
        n = n.replace(",", ".")
        salida.add(str(int(float(n))) if float(n).is_integer() else n)
    return salida


def _hechos_sin_fuente(
    ac: AccionCorte, texto: str, citadas: list[str], catalogo: dict[str, Fuente]
) -> str:
    """Motivo si la frase afirma datos que sus fuentes no traen, o si solo cita
    el contexto del plan; vacío si pasa. Comparación literal, sin modelo."""
    fuentes_citadas = [catalogo[c] for c in citadas]
    respaldo = " ".join(f"{f.texto} {f.ref}" for f in fuentes_citadas)
    cabecera = f"{ac.accion.codigo} {ac.corte} {ac.anterior or ''}"
    permitidas = _numeros(respaldo) | _numeros(cabecera)
    sin_citas = PATRON_CITA.sub("", texto)
    for url in _URL.findall(sin_citas):
        if url.rstrip(".,;") not in respaldo:
            return MOTIVO_DATO_SIN_FUENTE
    cifras = _numeros(_URL.sub("", sin_citas))
    if not cifras <= permitidas:
        return MOTIVO_DATO_SIN_FUENTE
    declarado = ac.accion.avance
    for p in _PORCENTAJE.findall(sin_citas):
        valor = float(p.replace(",", "."))
        en_fuentes = any(
            float(q.replace(",", ".")) == valor for q in _PORCENTAJE.findall(respaldo)
        )
        if not en_fuentes and (declarado is None or valor != declarado):
            return MOTIVO_DATO_SIN_FUENTE
    if all(f.contexto for f in fuentes_citadas) and not cifras:
        return MOTIVO_SOLO_CONTEXTO
    return ""


def depurar(frases: list[FraseAvance], nombres: set[str]) -> list[FraseAvance]:
    """Antes de guardar en la caché o mostrar: la frase que nombra a una persona
    se reemplaza por un marcador; el resto pierde correos y teléfonos."""
    salida: list[FraseAvance] = []
    for f in frases:
        if con_nombre_de_persona(f.texto, nombres):
            salida.append(FraseAvance(texto=OMITIDA, citas=[]))
        else:
            salida.append(f)
    return salida


def verificar(
    ac: AccionCorte, frases: list[FraseAvance], nombres: set[str]
) -> list[FraseVerificada]:
    """Determinista. La frase pasa si:
    1. cita en el texto al menos una fuente y el campo `citas` coincide;
    2. todas las citas existen en el catálogo de la acción;
    3. cifras, fechas y enlaces están literalmente en las fuentes que cita, y
       el % es el declarado o está en ellas;
    4. no se apoya solo en el contexto del plan, ni nombra a una persona."""
    catalogo = ac.por_id()
    salida: list[FraseVerificada] = []
    for f in frases:
        texto = " ".join(f.texto.split())
        if not texto:
            continue
        if texto == OMITIDA or con_nombre_de_persona(texto, nombres):
            salida.append(FraseVerificada(OMITIDA, [], MOTIVO_NOMBRE))
            continue
        texto = ocultar(texto, nombres)
        en_texto = list(dict.fromkeys(citas_en_texto(texto)))
        en_campo = list(
            dict.fromkeys(x.strip().strip("[]") for x in f.citas if x.strip())
        )
        if not en_texto:
            motivo = MOTIVO_SIN_CITA
        elif set(en_texto) != set(en_campo):
            motivo = MOTIVO_CITAS_NO_COINCIDEN
        elif any(c not in catalogo for c in en_texto):
            motivo = MOTIVO_CITA_INVALIDA
        else:
            motivo = _hechos_sin_fuente(ac, texto, en_texto, catalogo)
        if motivo:
            salida.append(FraseVerificada(texto, [], motivo))
        else:
            salida.append(FraseVerificada(texto, en_texto))
    return salida


def sin_evidencia(ac: AccionCorte) -> AccionBorrador:
    """Sin evidencia nueva no se llama al modelo: la frase sale del plan."""
    p1 = next((f for f in ac.fuentes if f.tipo == "plan"), None)
    frases = (
        [FraseVerificada(f"{SIN_EVIDENCIA_NUEVA} [{p1.id}]", [p1.id])] if p1 else []
    )
    return AccionBorrador(ac, frases, sin_evidencia_nueva=True)


# ---------------------------------------------------------------------------
# Estimación y generación
# ---------------------------------------------------------------------------


def _clave(texto: str) -> str:
    base = f"{MODELO_AVANCE}|{VERSION_PROMPT}|{SISTEMA}|{texto}"
    return "avance-" + hashlib.sha256(base.encode()).hexdigest()[:32]


@dataclass
class Estimacion:
    acciones: int
    sin_evidencia_nueva: int
    al_modelo: int
    en_cache: int
    costo: float


def estimar(acciones: list[AccionCorte], cache: Cache) -> Estimacion:
    # Lee la caché del disco: desde el event loop se llama con to_thread.
    """Costo de llamar al modelo solo por las acciones con evidencia nueva que
    no estén ya en la caché."""
    p_in, p_out = PRECIOS_USD_POR_MILLON[MODELO_AVANCE]
    al_modelo = en_cache = sin_nueva = 0
    ent = sal = 0
    for ac in acciones:
        if not ac.hay_evidencia_nueva:
            sin_nueva += 1
            continue
        texto = texto_para_modelo(ac)
        if cache.leer(_clave(texto)):
            en_cache += 1
            continue
        al_modelo += 1
        ent += TOKENS_FIJOS + len(texto) // CARACTERES_POR_TOKEN
        sal += SALIDA
    costo = ent * p_in / 1e6 + sal * p_out / 1e6
    return Estimacion(len(acciones), sin_nueva, al_modelo, en_cache, costo)


def excede_tope(est: Estimacion, tope_usd: float) -> str:
    if est.costo <= tope_usd:
        return ""
    return (
        f"La estimación ({est.costo:.2f} USD) pasa del tope por borrador "
        f"({tope_usd:.2f} USD). Pida subir el tope o genere el borrador de menos acciones."
    )


async def _proponer(
    ac: AccionCorte,
    texto: str,
    nombres: set[str],
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso,
) -> AccionBorrador:
    clave = _clave(texto)
    propuesta: AvanceAccion | None = None
    guardado = await asyncio.to_thread(cache.leer, clave)
    if guardado and guardado.get("datos"):
        try:
            propuesta = AvanceAccion.model_validate(guardado["datos"])
        except ValidationError:
            propuesta = None
    error = ""
    if propuesta is None:
        resp = await cliente.llamar(
            modelo=MODELO_AVANCE,
            sistema=SISTEMA,
            bloques=[],
            texto=texto,
            salida=AvanceAccion,
            nombre_herramienta="registrar_avance",
            esfuerzo="medium",
            max_tokens=SALIDA,
        )
        uso.registrar(MODELO_AVANCE, resp)
        if resp.entrada is None:
            error = resp.error
        else:
            try:
                propuesta = AvanceAccion.model_validate(resp.entrada)
                # A la caché no entra el texto de una frase que nombra a una persona.
                propuesta.frases = depurar(propuesta.frases, nombres)
                await asyncio.to_thread(
                    cache.guardar, clave, {"datos": propuesta.model_dump(mode="json")}
                )
            except ValidationError:
                error = "el modelo devolvió datos no válidos"
    if propuesta is None:
        return AccionBorrador(ac, error=error or "sin respuesta")
    # La caché guarda lo que dijo el modelo; la verificación se repite siempre.
    return AccionBorrador(ac, verificar(ac, propuesta.frases, nombres))


async def generar(
    programa: str,
    corte: str,
    acciones: list[AccionCorte],
    nombres: set[str],
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso | None = None,
    tope_usd: float | None = None,
    concurrencia: int = 4,
    progreso: Callable[[int, int], None] | None = None,
) -> Borrador:
    uso = uso if uso is not None else Uso()
    if tope_usd is not None:
        cliente = ClienteConTope(cliente, uso, tope_usd)
    semaforo = asyncio.Semaphore(concurrencia)
    hechas = [0]

    async def una(ac: AccionCorte) -> AccionBorrador:
        if not ac.hay_evidencia_nueva:
            resultado = sin_evidencia(ac)
        else:
            async with semaforo:
                resultado = await _proponer(
                    ac, texto_para_modelo(ac), nombres, cliente, cache, uso
                )
        hechas[0] += 1
        if progreso:
            progreso(hechas[0], len(acciones))
        return resultado

    resultados = await asyncio.gather(*(una(ac) for ac in acciones))
    return Borrador(
        programa,
        corte,
        list(resultados),
        uso,
        str(getattr(cliente, "detenido", "") or ""),
    )
