"""Rutas de decisión y umbrales de las solicitudes (config/solicitudes.yaml).

El archivo lo edita la Vicedecanatura Académica (docs/solicitudes.md). Dice,
para cada tipo de solicitud, que el comité asesor recomienda y quién decide;
y guarda los umbrales que usan las reglas deterministas de
`app/services/reglas.py`.

Si el archivo falta o tiene un error, el servicio de actas no arranca: más
vale un error claro al desplegar que una alerta con un umbral equivocado.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.normativa.base import NORMAS
from app.schemas.caso import TITULOS_TIPO, TipoSolicitud

Instancia = Literal[
    "consejo_facultad", "consejo_sede", "consejo_superior", "por_confirmar"
]

NOMBRE_INSTANCIA: dict[str, str] = {
    "consejo_facultad": "Consejo de Facultad",
    "consejo_sede": "Consejo de Sede",
    "consejo_superior": "Consejo Superior Universitario",
    "por_confirmar": "por confirmar",
}
POR_CONFIRMAR = "por_confirmar"


class ConfigSolicitudesError(RuntimeError):
    """El archivo de rutas falta o no es válido."""


class _Estricto(BaseModel):
    # Una clave mal escrita en el YAML es un error, no un dato que se ignora.
    model_config = ConfigDict(extra="forbid", frozen=True)


def _norma_existe(ref: str) -> None:
    if ref not in NORMAS:
        raise ValueError(
            f"la norma «{ref}» no está transcrita en app/normativa/base.py "
            f"(disponibles: {', '.join(sorted(NORMAS))})"
        )


class Umbral(_Estricto):
    valor: int = Field(ge=1)
    # `norma` remite a un texto literal de app/normativa; `fuente` es para lo
    # que todavía no está transcrito o no es norma (una instrucción).
    norma: str | None = None
    fuente: str | None = None
    nota: str | None = None

    @model_validator(mode="after")
    def _con_origen(self) -> Self:
        if not self.norma and not self.fuente:
            raise ValueError("cada umbral necesita «norma» o «fuente»")
        if self.norma:
            _norma_existe(self.norma)
        return self

    @property
    def cita(self) -> str:
        """De dónde sale el umbral, para citarlo en la alerta."""
        if self.norma:
            n = NORMAS[self.norma]
            return f"{n.norma}, {n.articulo}"
        return self.fuente or ""


class Umbrales(_Estricto):
    carga_minima: Umbral
    semana_limite_asignaturas: Umbral
    semana_limite_tdg_actividades: Umbral
    semana_limite_traslado: Umbral
    jurados_minimo: Umbral
    tdg_creditos_disciplinares: dict[str, Umbral] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coherentes(self) -> Self:
        desconocidos = set(self.tdg_creditos_disciplinares) - set(PROGRAMAS)
        if desconocidos:
            raise ValueError(
                "tdg_creditos_disciplinares tiene programas que no existen: "
                + ", ".join(sorted(desconocidos))
                + f" (válidos: {', '.join(PROGRAMAS)})"
            )
        if (
            self.semana_limite_asignaturas.valor
            > self.semana_limite_tdg_actividades.valor
        ):
            raise ValueError(
                "semana_limite_asignaturas no puede ser mayor que "
                "semana_limite_tdg_actividades"
            )
        return self

    def tdg_creditos(self, programa: str | None) -> Umbral | None:
        return self.tdg_creditos_disciplinares.get(programa or "")


class Plazo(_Estricto):
    """Días calendario para un tramo del trámite (indicador «fuera de plazo»)."""

    dias: int = Field(ge=1)
    # Quién fijó el plazo: norma, circular o instrucción. Sin fuente no hay plazo.
    fuente: str = Field(min_length=1)
    nota: str | None = None


class Plazos(_Estricto):
    # De la solicitud a la recomendación del comité asesor.
    comite: Plazo | None = None
    # De la recomendación del comité a la decisión que consta en el acta del
    # Consejo.
    consejo: Plazo | None = None


class Flujo(_Estricto):
    """Decisiones de negocio de la línea de estados (app/services/flujo.py).

    Los valores por defecto reproducen lo que hacía MemorIA antes de la línea
    única: no había prerrevisión y todo caso pasaba por el comité."""

    # Si es true, un caso no entra al comité hasta que el programa lo marque
    # «procedente». Con false, entra al comité cuando termina la lectura.
    prerrevision_obligatoria: bool = False
    # Si es true, un caso que el programa marca «improcedente» igual pasa por
    # el comité (con la marca a la vista). Con false, se queda en
    # «improcedente»: se guarda para las métricas, pero no va al comité.
    improcedente_va_a_comite: bool = True
    nota: str | None = None


class Ruta(_Estricto):
    # El comité asesor recomienda; nunca decide (AGENTS.md).
    recomienda: Literal["comite_asesor"] = "comite_asesor"
    decide: Instancia
    acto: str = Field(min_length=1)
    normas: list[str] = Field(default_factory=list)
    nota: str | None = None

    @model_validator(mode="after")
    def _normas_existen(self) -> Self:
        for ref in self.normas:
            _norma_existe(ref)
        return self

    @property
    def por_confirmar(self) -> bool:
        return self.decide == POR_CONFIRMAR

    @property
    def nombre_decide(self) -> str:
        return NOMBRE_INSTANCIA[self.decide]

    @property
    def nombre_acto(self) -> str:
        return "por confirmar" if self.acto == POR_CONFIRMAR else self.acto


class ConfigSolicitudes(_Estricto):
    umbrales: Umbrales
    # Vacíos mientras la Vicedecanatura no los fije (docs/indicadores.md).
    plazos: Plazos = Field(default_factory=Plazos)
    # Por defecto, el comportamiento anterior a la línea única.
    flujo: Flujo = Field(default_factory=Flujo)
    solicitudes: dict[TipoSolicitud, Ruta]

    @model_validator(mode="after")
    def _todas_las_solicitudes(self) -> Self:
        faltan = [t.value for t in TipoSolicitud if t not in self.solicitudes]
        if faltan:
            raise ValueError(
                "faltan estos tipos de solicitud en «solicitudes»: " + ", ".join(faltan)
            )
        return self

    def ruta(self, tipo: TipoSolicitud) -> Ruta:
        return self.solicitudes[tipo]


def cargar(ruta: Path) -> ConfigSolicitudes:
    """Lee y valida el archivo. Cualquier problema sale como un error claro."""
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigSolicitudesError(
            f"No encuentro {ruta}. El servicio de actas lo necesita para saber "
            "quién decide cada solicitud y con qué umbrales (docs/solicitudes.md)."
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigSolicitudesError(f"{ruta} no es un YAML válido: {exc}") from exc
    try:
        return ConfigSolicitudes.model_validate(datos)
    except ValidationError as exc:
        problemas = "\n".join(
            f"  - {'.'.join(str(p) for p in e['loc']) or '(raíz)'}: {e['msg']}"
            for e in exc.errors()
        )
        raise ConfigSolicitudesError(
            f"{ruta} tiene errores (docs/solicitudes.md explica el formato):\n"
            f"{problemas}"
        ) from exc


@lru_cache(maxsize=4)
def _cargar_cacheado(ruta: Path) -> ConfigSolicitudes:
    return cargar(ruta)


def actual() -> ConfigSolicitudes:
    """La configuración en uso (SOLICITUDES_PATH o config/solicitudes.yaml)."""
    return _cargar_cacheado(settings.solicitudes_path)


def recargar() -> ConfigSolicitudes:
    _cargar_cacheado.cache_clear()
    return actual()


def jurados_minimo() -> int:
    """La variable de entorno JURADOS_MINIMO, si está definida, gana al YAML."""
    if settings.jurados_minimo is not None:
        return settings.jurados_minimo
    return actual().umbrales.jurados_minimo.valor


def cita_jurados_minimo(valor: int) -> str:
    """De dónde sale el mínimo de jurados que usa la alerta."""
    if settings.jurados_minimo is not None and valor == settings.jurados_minimo:
        return "variable de entorno JURADOS_MINIMO; no es norma"
    umbral = actual().umbrales.jurados_minimo
    return umbral.cita + ("" if umbral.norma else "; no es norma")


def decisores(
    tipos: list[TipoSolicitud],
) -> list[tuple[Ruta, list[TipoSolicitud]]]:
    """Quién decide, agrupado por instancia y en el orden de los tipos."""
    config = actual()
    grupos: dict[str, tuple[Ruta, list[TipoSolicitud]]] = {}
    for tipo in tipos or [TipoSolicitud.OTRO]:
        ruta = config.ruta(tipo)
        grupos.setdefault(ruta.decide, (ruta, []))[1].append(tipo)
    return list(grupos.values())


def texto_decide(tipos: list[TipoSolicitud]) -> str:
    """«Consejo de Facultad», o una instancia por tipo si no coinciden."""
    grupos = decisores(tipos)
    if len(grupos) == 1:
        return grupos[0][0].nombre_decide
    return "; ".join(
        f"{ruta.nombre_decide} ({', '.join(TITULOS_TIPO[t] for t in ts)})"
        for ruta, ts in grupos
    )


def fuera_de_facultad(tipos: list[TipoSolicitud]) -> list[str]:
    """Instancias confirmadas distintas del Consejo de Facultad (Sede, Superior)."""
    return [
        ruta.nombre_decide
        for ruta, _ in decisores(tipos)
        if ruta.decide not in ("consejo_facultad", POR_CONFIRMAR)
    ]
