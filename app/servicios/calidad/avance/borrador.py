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
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.servicios.calidad.avance.fuentes import (
    AccionCorte,
    citas_en_texto,
    con_nombre_de_persona,
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

SISTEMA = """Eres asistente de la oficina de calidad académica de una facultad \
universitaria. Redactas una PROPUESTA de la descripción de avance de una acción \
de un plan de mejoramiento en un corte semestral, para el informe de \
autoevaluación. La oficina de calidad la revisa y la aprueba, la edita o la \
descarta; el Comité Asesor recomienda y el Consejo de Facultad decide. Tú no \
decides si la acción se cumplió.

Reglas:
- Usa solo las fuentes numeradas que se te dan. No supongas hechos que no están.
- Cada frase termina citando sus fuentes con su ID entre corchetes, p. ej. \
[P2] o [P2, E1]. Cita solo IDs de la lista. Una frase sin cita no se usa.
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
        f"Objetivo: {ac.objetivo.texto}",
        f"Acción {a.codigo}: {a.descripcion}",
        f"Indicador de cumplimiento: {a.indicador}",
        "",
        "Fuentes (cita solo estas):",
    ]
    for f in ac.fuentes:
        marca = " (nueva en este corte)" if f.nueva else ""
        partes.append(f"[{f.id}]{marca} {f.texto}")
    partes += ["", "Redacta la propuesta de descripción de avance de esta acción."]
    return "\n".join(partes)


def verificar(
    ac: AccionCorte, frases: list[FraseAvance], nombres: set[str]
) -> list[FraseVerificada]:
    """Determinista: cada frase cita al menos una fuente de la acción, todas
    sus citas existen y no nombra personas."""
    catalogo = ac.por_id()
    salida: list[FraseVerificada] = []
    for f in frases:
        texto = " ".join(f.texto.split())
        if not texto:
            continue
        citadas: list[str] = []
        for c in [*citas_en_texto(texto), *(x.strip().strip("[]") for x in f.citas)]:
            if c and c not in citadas:
                citadas.append(c)
        if not citadas:
            salida.append(FraseVerificada(texto, [], MOTIVO_SIN_CITA))
        elif any(c not in catalogo for c in citadas):
            salida.append(FraseVerificada(texto, [], MOTIVO_CITA_INVALIDA))
        elif con_nombre_de_persona(texto, nombres):
            salida.append(FraseVerificada(texto, citadas, MOTIVO_NOMBRE))
        else:
            salida.append(FraseVerificada(texto, citadas))
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
    guardado = cache.leer(clave)
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
                cache.guardar(clave, {"datos": propuesta.model_dump(mode="json")})
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
