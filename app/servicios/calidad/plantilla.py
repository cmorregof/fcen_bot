"""Lector determinista de la plantilla institucional del plan de mejoramiento.

La plantilla tiene cinco hojas: «1. Formulación», «2. Plan de Mejora(miento)»,
«3. Cronograma 20XX» (una por año), «4. Evaluación» y «Presupuesto». Entre
programas cambian la fila del encabezado, las celdas combinadas, el formato de
fechas y de porcentajes y hasta los espacios en el nombre de la hoja; por eso
todo se ubica por palabras clave y nunca por posición fija.

Sin modelo de lenguaje: lo que no se puede leer queda como alerta de lectura.
Las alertas citan hoja, fila y columna, nunca el contenido de la celda.
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel, Field


def plegar(texto: object) -> str:
    """Minúsculas, sin tildes y con espacios simples."""
    sin = unicodedata.normalize("NFD", str(texto or ""))
    sin = "".join(c for c in sin if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin).strip().lower()


# ---------------------------------------------------------------------------
# Modelo de datos: programa → objetivo → acción → tareas del cronograma
# ---------------------------------------------------------------------------


class Corte(BaseModel):
    """Descripción del avance de una acción en un corte semestral."""

    rotulo: str  # fecha ISO del corte, o el encabezado si no trae fecha
    fecha: date | None = None
    descripcion: str = ""
    evidencias: str = ""


class TareaCronograma(BaseModel):
    anio: int
    hoja: str
    fila: int
    descripcion: str
    soporte: str = ""
    responsable: str = ""
    enlace: str = ""
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    avance: float | None = None
    ok: bool | None = None
    estado_texto: str = ""
    reprogramada: bool = False


class Accion(BaseModel):
    codigo: str
    descripcion: str
    objetivo_codigo: str = ""
    indicador: str = ""
    responsables: str = ""
    recursos: str = ""
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    fechas_fin_anteriores: list[date] = Field(default_factory=list)
    avance: float | None = None
    evidencias: str = ""
    cortes: list[Corte] = Field(default_factory=list)
    marcas: list[str] = Field(default_factory=list)  # «NO FUNCIONÓ», etc.
    tareas: list[TareaCronograma] = Field(default_factory=list)
    hoja: str = ""
    fila: int = 0

    @property
    def no_funciono(self) -> bool:
        return any("no funciono" in plegar(m) for m in self.marcas)

    @property
    def reprogramada(self) -> bool:
        return (
            bool(self.fechas_fin_anteriores)
            or any("reprogram" in plegar(m) for m in self.marcas)
            or any(t.reprogramada for t in self.tareas)
        )

    @property
    def enlaces(self) -> list[str]:
        return re.findall(r"https?://\S+", self.evidencias)

    @property
    def origen(self) -> str:
        return f"«{self.hoja}» fila {self.fila}"


class Objetivo(BaseModel):
    codigo: str
    texto: str
    meta: str = ""
    oportunidad: str = ""
    linea_base: str = ""
    acciones: list[Accion] = Field(default_factory=list)


class Oportunidad(BaseModel):
    texto: str
    linea_base: str = ""
    factor: str = ""
    caracteristica: str = ""
    relacion_plan_accion: str = ""


class Evaluacion(BaseModel):
    fecha: date | None = None
    objetivo_codigo: str = ""
    objetivo: str = ""
    avance_declarado: float | None = None
    avance_real: float | None = None
    descripcion: str = ""


class Plan(BaseModel):
    programa: str
    objetivos: list[Objetivo] = Field(default_factory=list)
    oportunidades: list[Oportunidad] = Field(default_factory=list)
    evaluaciones: list[Evaluacion] = Field(default_factory=list)
    cronogramas: list[int] = Field(default_factory=list)
    alertas: list[str] = Field(default_factory=list)

    @property
    def acciones(self) -> list[Accion]:
        return [a for o in self.objetivos for a in o.acciones]

    @property
    def tareas(self) -> list[TareaCronograma]:
        return [t for a in self.acciones for t in a.tareas]

    def avance_promedio(self) -> float | None:
        valores = [a.avance for a in self.acciones if a.avance is not None]
        return sum(valores) / len(valores) if valores else None


@dataclass
class Lectura:
    plan: Plan | None = None
    errores: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Celdas: fechas, porcentajes, códigos y marcas escritas a mano
# ---------------------------------------------------------------------------

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}  # fmt: skip
_RE_FECHA = re.compile(
    r"(?P<iso>(?P<ia>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2}))"
    r"|(?P<num>(?P<nd>\d{1,2})[/-](?P<nm>\d{1,2})[/-](?P<na>\d{4}))"
    r"|(?P<larga>(?P<ld>\d{1,2})\s+de\s+(?P<lm>[a-z]+)\s+(?:de(?:l)?\s+)?(?P<la>\d{4}))"
)
_RE_CODIGO = re.compile(
    r"^\s*(?P<marca>(?:[A-ZÁÉÍÓÚÑ]{2,}[\s:,\-–]+)*)"
    r"(?P<codigo>\d{1,2}(?:\.\d{1,2})*)\.?(?![\d%])\s*(?P<resto>.*)$",
    re.DOTALL,
)
_MARCAS = ("no funciono", "reprogram", "eliminad", "suspendid", "cancelad", "pospuest")
_SI = {"x", "si", "sí", "ok", "✓", "✔", "true", "verdadero", "1"}
_NO = {"no", "false", "falso", "0"}


def fechas_en_texto(texto: str) -> list[date]:
    """Todas las fechas legibles de un texto, en el orden en que aparecen."""
    salida: list[date] = []
    for m in _RE_FECHA.finditer(plegar(texto)):
        try:
            if m.group("iso"):
                f = date(int(m["ia"]), int(m["im"]), int(m["id"]))
            elif m.group("num"):
                f = date(int(m["na"]), int(m["nm"]), int(m["nd"]))
            else:
                mes = _MESES.get(m["lm"])
                if mes is None:
                    continue
                f = date(int(m["la"]), mes, int(m["ld"]))
        except ValueError:
            continue
        salida.append(f)
    return salida


def como_fechas(valor: object) -> list[date]:
    if isinstance(valor, datetime):
        return [valor.date()]
    if isinstance(valor, date):
        return [valor]
    if isinstance(valor, str):
        return fechas_en_texto(valor)
    return []


def como_porcentaje(valor: object, formato: str = "General") -> float | None:
    """% de 0 a 100. Con formato de porcentaje la celda guarda 0–1; sin él,
    la plantilla escribe 0–100. Un texto como «100 %» también vale."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor) * 100 if "%" in (formato or "") else float(valor)
    texto = str(valor).strip().replace(",", ".")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%?", texto)
    if not m:
        return None
    return float(m.group(1))


def como_ok(valor: object) -> bool | None:
    if isinstance(valor, bool):
        return valor
    texto = plegar(valor)
    if texto in _SI:
        return True
    if texto in _NO:
        return False
    return None


def separar_codigo(texto: str) -> tuple[str, list[str], str]:
    """«NO FUNCIONÓ 1.1. Revisión…» → ("1.1", ["NO FUNCIONÓ"], "Revisión…")."""
    m = _RE_CODIGO.match(texto or "")
    if not m:
        return "", marcas_en(texto), (texto or "").strip()
    marca = m["marca"].strip(" :,-–")
    marcas = [marca] if marca else []
    for extra in marcas_en(m["resto"]):
        if extra not in marcas:
            marcas.append(extra)
    return m["codigo"], marcas, m["resto"].strip()


def marcas_en(texto: str) -> list[str]:
    """Estados escritos a mano que aparecen dentro de un texto."""
    p = plegar(texto)
    return [_ROTULO_MARCA[m] for m in _MARCAS if m in p]


_ROTULO_MARCA = {
    "no funciono": "NO FUNCIONÓ",
    "reprogram": "reprogramación",
    "eliminad": "eliminada",
    "suspendid": "suspendida",
    "cancelad": "cancelada",
    "pospuest": "pospuesta",
}


# ---------------------------------------------------------------------------
# Hojas y encabezados
# ---------------------------------------------------------------------------


class _Hoja:
    """Hoja con las celdas combinadas resueltas a su valor de arriba a la izquierda."""

    def __init__(self, ws: Worksheet) -> None:
        self.ws = ws
        self.titulo = ws.title.strip()
        self.max_fila = ws.max_row
        self.max_col = ws.max_column
        self._combinadas: dict[tuple[int, int], tuple[int, int]] = {}
        for rango in ws.merged_cells.ranges:
            for f in range(rango.min_row, rango.max_row + 1):
                for c in range(rango.min_col, rango.max_col + 1):
                    if (f, c) != (rango.min_row, rango.min_col):
                        self._combinadas[(f, c)] = (rango.min_row, rango.min_col)

    def valor(self, fila: int, col: int, *, combinada: bool = True) -> Any:
        if combinada and (fila, col) in self._combinadas:
            fila, col = self._combinadas[(fila, col)]
        elif (fila, col) in self._combinadas:
            return None
        return self.ws.cell(fila, col).value

    def formato(self, fila: int, col: int) -> str:
        return str(self.ws.cell(fila, col).number_format or "General")

    def texto(self, fila: int, col: int | None, *, combinada: bool = True) -> str:
        if col is None:
            return ""
        v = self.valor(fila, col, combinada=combinada)
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.date().isoformat()
        return str(v).strip()

    def es_combinada_interior(self, fila: int, col: int) -> bool:
        return (fila, col) in self._combinadas


def _palabras(texto: str, *claves: str) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", texto) for k in claves)


def _buscar_encabezado(
    hoja: _Hoja, grupos: Iterable[tuple[str, ...]], hasta: int = 25
) -> int | None:
    grupos = list(grupos)
    for f in range(1, min(hasta, hoja.max_fila) + 1):
        textos = [plegar(hoja.valor(f, c)) for c in range(1, hoja.max_col + 1)]
        textos = [t for t in textos if t and len(t) < 80]
        if all(any(_palabras(t, *g) for t in textos) for g in grupos):
            return f
    return None


def _rotulos(hoja: _Hoja, fila: int, filas: int = 3) -> dict[int, str]:
    """Rótulo de cada columna: el encabezado y las subfilas cortas debajo."""
    salida: dict[int, str] = {}
    for c in range(1, hoja.max_col + 1):
        partes = []
        for f in range(fila, fila + filas):
            v = hoja.valor(f, c)
            if isinstance(v, str) and 0 < len(v.strip()) < 70:
                t = plegar(v)
                if t not in partes:
                    partes.append(t)
        if partes:
            salida[c] = " ".join(partes)
    return salida


def _programa(hoja: _Hoja, hasta: int) -> str:
    descartar = ("plan de mejora", "evaluacion", "oportunidades", "fecha de inicio",
                 "cronograma", "formulacion")  # fmt: skip
    for f in range(1, hasta):
        for c in range(1, min(hoja.max_col, 30) + 1):
            v = hoja.valor(f, c, combinada=False)
            if isinstance(v, str) and v.strip() and len(v) < 120:
                if not any(d in plegar(v) for d in descartar):
                    return re.sub(r"\s+", " ", v).strip()
    return ""


def _hojas(libro: Any, *claves: str) -> list[_Hoja]:
    return [
        _Hoja(ws)
        for ws in libro.worksheets
        if any(k in plegar(ws.title) for k in claves)
    ]


def _codigo_padre(codigo: str) -> str:
    partes = codigo.split(".")
    return ".".join(partes[:-1]) if len(partes) > 1 else codigo


def _ref(hoja: _Hoja, fila: int, col: int | None = None) -> str:
    celda = f"{get_column_letter(col)}{fila}" if col else f"fila {fila}"
    return f"«{hoja.titulo}» {celda}"


# ---------------------------------------------------------------------------
# Hoja 2: plan de mejora
# ---------------------------------------------------------------------------


@dataclass
class _ColumnasPlan:
    objetivo: int | None = None
    meta: int | None = None
    oportunidad: int | None = None
    linea_base: int | None = None
    accion: int | None = None
    indicador: int | None = None
    responsables: int | None = None
    recursos: list[int] = field(default_factory=list)
    inicio: int | None = None
    fin: int | None = None
    avance: int | None = None
    evidencias: list[tuple[int, date | None]] = field(default_factory=list)
    cortes: list[tuple[int, str, date | None]] = field(default_factory=list)


def _columnas_plan(rotulos: dict[int, str]) -> _ColumnasPlan:
    col = _ColumnasPlan()
    for c, r in sorted(rotulos.items()):
        fechas = fechas_en_texto(r)
        if _palabras(r, "descripcion"):
            m = re.search(r"\(([^)]*)\)", r)
            rotulo = fechas[0].isoformat() if fechas else (m.group(1) if m else r)
            col.cortes.append((c, rotulo, fechas[0] if fechas else None))
        elif _palabras(r, "evidencia", "evidencias"):
            col.evidencias.append((c, fechas[0] if fechas else None))
        elif "avance" in r and col.avance is None:
            col.avance = c
        elif _palabras(r, "objetivo", "objetivo(s)") and col.objetivo is None:
            col.objetivo = c
        elif _palabras(r, "accion", "accion(es)", "acciones") and col.accion is None:
            col.accion = c
        elif _palabras(r, "meta") and col.meta is None:
            col.meta = c
        elif _palabras(r, "oportunidad") and col.oportunidad is None:
            col.oportunidad = c
        elif _palabras(r, "linea base") and col.linea_base is None:
            col.linea_base = c
        elif _palabras(r, "indicador") and col.indicador is None:
            col.indicador = c
        elif _palabras(r, "responsable", "responsables") and col.responsables is None:
            col.responsables = c
        elif _palabras(r, "inicio") and col.inicio is None:
            col.inicio = c
        elif _palabras(r, "fin", "final") and col.fin is None:
            col.fin = c
        elif _palabras(r, "recursos"):
            col.recursos.append(c)
    return col


def _leer_hoja_plan(hoja: _Hoja, alertas: list[str]) -> list[Objetivo]:
    fila_enc = _buscar_encabezado(
        hoja, [("objetivo", "objetivo(s)"), ("accion", "accion(es)"), ("avance",)]
    )
    if fila_enc is None:
        alertas.append(f"«{hoja.titulo}»: no encontré la fila de encabezados.")
        return []
    rot = _rotulos(hoja, fila_enc, 2)
    col = _columnas_plan(rot)
    if col.accion is None:
        alertas.append(f"«{hoja.titulo}»: no encontré la columna de acciones.")
        return []
    for nombre in ("avance", "fin", "responsables", "indicador"):
        if getattr(col, nombre) is None:
            alertas.append(f"«{hoja.titulo}»: no encontré la columna «{nombre}».")

    objetivos: dict[str, Objetivo] = {}
    codigos: set[str] = set()
    for f in range(fila_enc + 2, hoja.max_fila + 1):
        if hoja.es_combinada_interior(f, col.accion):
            continue
        valor_accion = hoja.valor(f, col.accion, combinada=False)
        bruto = valor_accion.strip() if isinstance(valor_accion, str) else ""
        if len(bruto) < 3:
            continue  # vacía, interior de una combinada o número suelto
        codigo, marcas, descripcion = separar_codigo(bruto)
        avance_v = hoja.valor(f, col.avance) if col.avance else None
        fin_v = hoja.valor(f, col.fin) if col.fin else None
        if not codigo and not como_fechas(fin_v) and como_porcentaje(avance_v) is None:
            continue  # fila de instrucciones o rótulo
        if not codigo:
            codigo = f"F{f}"
            alertas.append(
                f"{_ref(hoja, f, col.accion)}: acción sin numeración; la identifico como {codigo}."
            )
        if codigo in codigos:
            nuevo = f"{codigo}-F{f}"
            alertas.append(
                f"{_ref(hoja, f, col.accion)}: el código {codigo} se repite; la identifico como {nuevo}."
            )
            codigo = nuevo
        codigos.add(codigo)

        obj_texto = hoja.texto(f, col.objetivo)
        obj_codigo, _, _ = separar_codigo(obj_texto)
        if not obj_codigo:
            obj_codigo = _codigo_padre(codigo) if not codigo.startswith("F") else "?"
        objetivo = objetivos.get(obj_codigo)
        if objetivo is None:
            objetivo = objetivos[obj_codigo] = Objetivo(
                codigo=obj_codigo,
                texto=obj_texto,
                meta=hoja.texto(f, col.meta),
                oportunidad=hoja.texto(f, col.oportunidad),
                linea_base=hoja.texto(f, col.linea_base),
            )

        avance = (
            como_porcentaje(avance_v, hoja.formato(f, col.avance))
            if col.avance
            else None
        )
        if col.avance and avance is None:
            alertas.append(
                f"{_ref(hoja, f, col.avance)}: acción {codigo} sin % de avance legible."
            )
        if avance is not None and not 0 <= avance <= 100:
            alertas.append(
                f"{_ref(hoja, f, col.avance)}: % de avance fuera de 0–100 ({avance:g})."
            )
        if (
            col.avance
            and avance is not None
            and 0 < avance < 1
            and "%" not in hoja.formato(f, col.avance)
        ):
            alertas.append(
                f"{_ref(hoja, f, col.avance)}: % ambiguo ({avance:g}); lo leo como {avance:g} %, revísalo."
            )

        fines = como_fechas(fin_v)
        inicios = como_fechas(hoja.valor(f, col.inicio)) if col.inicio else []
        if col.fin and not fines:
            alertas.append(
                f"{_ref(hoja, f, col.fin)}: acción {codigo} sin fecha de fin legible."
            )
        cortes = [
            Corte(rotulo=r, fecha=fc, descripcion=hoja.texto(f, c))
            for c, r, fc in col.cortes
        ]
        evidencias = []
        for c, fecha_ev in col.evidencias:
            texto = hoja.texto(f, c)
            if not texto:
                continue
            emparejado = next(
                (k for k in cortes if fecha_ev and k.fecha == fecha_ev), None
            )
            if emparejado is not None:
                emparejado.evidencias = texto
            evidencias.append(texto)
        objetivo.acciones.append(
            Accion(
                codigo=codigo,
                descripcion=descripcion,
                objetivo_codigo=obj_codigo,
                indicador=hoja.texto(f, col.indicador),
                responsables=hoja.texto(f, col.responsables),
                recursos=_recursos(hoja, f, col.recursos, rot),
                fecha_inicio=inicios[0] if inicios else None,
                fecha_fin=fines[-1] if fines else None,
                fechas_fin_anteriores=fines[:-1],
                avance=avance,
                evidencias="\n".join(evidencias),
                cortes=[k for k in cortes if k.descripcion or k.evidencias],
                marcas=marcas,
                hoja=hoja.titulo,
                fila=f,
            )
        )
    return list(objetivos.values())


def _recursos(hoja: _Hoja, fila: int, columnas: list[int], rot: dict[int, str]) -> str:
    """«x» en HUMANOS/FÍSICOS… → el nombre de la columna; otro texto, tal cual."""
    salida = []
    for c in columnas:
        valor = hoja.texto(fila, c)
        if not valor or plegar(valor) in ("n/a", "na", "no"):
            continue
        salida.append(rot[c].split()[-1] if plegar(valor) in ("x", "si") else valor)
    return ", ".join(salida)


# ---------------------------------------------------------------------------
# Hoja 3: cronogramas por año
# ---------------------------------------------------------------------------


@dataclass
class _ColumnasCrono:
    objetivo: int | None = None
    accion: int | None = None
    acc_inicio: int | None = None
    acc_fin: int | None = None
    tarea: int | None = None
    soporte: int | None = None
    responsable: int | None = None
    drive: int | None = None
    estado: int | None = None
    avance: int | None = None
    ok: int | None = None
    inicio: int | None = None
    fin: int | None = None
    meses: dict[int, tuple[int, int]] = field(
        default_factory=dict
    )  # col → (mes, semana)


def _columnas_crono(rotulos: dict[int, str], max_col: int) -> _ColumnasCrono:
    col = _ColumnasCrono()
    mes_actual: tuple[int, int] | None = None
    for c in range(1, max_col + 1):
        r = rotulos.get(c, "")
        primera = r.split(" ")[0] if r else ""
        if primera in _MESES:
            mes = _MESES[primera]
            if mes_actual is None or mes_actual[0] != mes:
                mes_actual = (mes, c)  # el mes puede venir combinado sobre sus semanas
            col.meses[c] = (mes, c - mes_actual[1] + 1)
            continue
        if not r:
            if mes_actual and c - mes_actual[1] < 6:
                col.meses[c] = (mes_actual[0], c - mes_actual[1] + 1)
            continue
        if "semana" in r and mes_actual:
            col.meses[c] = (mes_actual[0], c - mes_actual[1] + 1)
            continue
        mes_actual = None
        if "fecha accion" in r:
            if _palabras(r, "inicio"):
                col.acc_inicio = c
            elif _palabras(r, "fin", "final"):
                col.acc_fin = c
        elif _palabras(r, "objetivo") and col.objetivo is None:
            col.objetivo = c
        elif _palabras(r, "accion") and col.accion is None:
            col.accion = c
        elif _palabras(r, "soporte", "corte de cumplimiento"):
            col.soporte = c
        elif _palabras(r, "responsable"):
            col.responsable = c
        elif _palabras(r, "drive", "enlace", "link"):
            col.drive = c
        elif _palabras(r, "estado"):
            col.estado = c
        elif _palabras(r, "avance"):
            col.avance = c
        elif _palabras(r, "ok"):
            col.ok = c
        elif _palabras(r, "inicio"):
            col.inicio = c
        elif _palabras(r, "fin", "final"):
            col.fin = c
        elif "tareas especificas" in r or "tarea especifica" in r:
            col.tarea = c if col.tarea is None else col.tarea
    return col


def _leer_cronograma(
    hoja: _Hoja, acciones: dict[str, Accion], alertas: list[str]
) -> int:
    """Pega las tareas del cronograma a sus acciones. Devuelve cuántas leyó."""
    anios = re.findall(r"20\d\d", hoja.titulo)
    anio = int(anios[0]) if anios else 0
    fila_enc = _buscar_encabezado(
        hoja, [("objetivo",), ("accion",), ("indicador", "fecha accion")]
    )
    if fila_enc is None:
        alertas.append(f"«{hoja.titulo}»: no encontré la fila de encabezados.")
        return 0
    col = _columnas_crono(_rotulos(hoja, fila_enc, 3), hoja.max_col)
    if col.accion is None:
        alertas.append(f"«{hoja.titulo}»: no encontré la columna de acciones.")
        return 0
    if col.tarea is None:
        alertas.append(
            f"«{hoja.titulo}»: no tiene columna de tareas específicas; solo leo las marcas de las acciones."
        )

    leidas = 0
    actual: Accion | None = None
    sin_pareja: set[str] = set()
    for f in range(fila_enc + 2, hoja.max_fila + 1):
        bruto_acc = hoja.valor(f, col.accion, combinada=False)
        texto_acc = bruto_acc.strip() if isinstance(bruto_acc, str) else ""
        if texto_acc:
            codigo, marcas, _ = separar_codigo(texto_acc)
            if codigo:
                actual = acciones.get(codigo)
                if actual is None:
                    actual = _por_prefijo(acciones, codigo)
                if actual is None:
                    sin_pareja.add(codigo)
                else:
                    for m in marcas:
                        if m not in actual.marcas:
                            actual.marcas.append(m)
                    fines = (
                        como_fechas(hoja.valor(f, col.acc_fin)) if col.acc_fin else []
                    )
                    if len(fines) > 1:
                        for previa in fines[:-1]:
                            if (
                                previa not in actual.fechas_fin_anteriores
                                and previa != actual.fecha_fin
                            ):
                                actual.fechas_fin_anteriores.append(previa)
            elif len(texto_acc) > 3 and hoja.texto(f, col.tarea) == "":
                actual = None  # leyenda o rótulo al pie
        if col.tarea is None:
            continue
        descripcion = hoja.texto(f, col.tarea, combinada=False)
        if not descripcion or hoja.es_combinada_interior(f, col.tarea):
            continue
        if actual is None:
            continue
        drive = hoja.texto(f, col.drive)
        enlace = drive if re.match(r"\s*https?://", drive) else ""
        estado = " ".join(
            t for t in (drive if not enlace else "", hoja.texto(f, col.estado)) if t
        )
        notas_gantt = [
            hoja.texto(f, c, combinada=False)
            for c in col.meses
            if isinstance(hoja.valor(f, c, combinada=False), str)
        ]
        marcas_tarea = marcas_en(estado + " " + " ".join(notas_gantt))
        inicios = como_fechas(hoja.valor(f, col.inicio)) if col.inicio else []
        fines = como_fechas(hoja.valor(f, col.fin)) if col.fin else []
        if not fines and anio:
            semanas = [
                (mes, semana)
                for c, (mes, semana) in col.meses.items()
                if hoja.valor(f, c, combinada=False) not in (None, "", 0)
            ]
            if semanas:
                mes, semana = max(semanas)
                fines = [date(anio, mes, min(7 * semana, 28))]
                if not inicios:
                    mes0, sem0 = min(semanas)
                    inicios = [date(anio, mes0, min(7 * (sem0 - 1) + 1, 28))]
        avance = None
        if col.avance:
            avance = como_porcentaje(
                hoja.valor(f, col.avance), hoja.formato(f, col.avance)
            )
        actual.tareas.append(
            TareaCronograma(
                anio=anio,
                hoja=hoja.titulo,
                fila=f,
                descripcion=descripcion,
                soporte=hoja.texto(f, col.soporte),
                responsable=hoja.texto(f, col.responsable),
                enlace=enlace,
                fecha_inicio=inicios[0] if inicios else None,
                fecha_fin=fines[-1] if fines else None,
                avance=avance,
                ok=como_ok(hoja.valor(f, col.ok)) if col.ok else None,
                estado_texto=estado,
                reprogramada=len(fines) > 1
                or any(m in ("reprogramación", "pospuesta") for m in marcas_tarea),
            )
        )
        leidas += 1
    for codigo in sorted(sin_pareja):
        alertas.append(
            f"«{hoja.titulo}»: la acción {codigo} no está en el plan; sus tareas no se cargaron."
        )
    return leidas


def _por_prefijo(acciones: dict[str, Accion], codigo: str) -> Accion | None:
    """Si el cronograma numera 1.1 y el plan 1.1.1 (o al revés) y hay una sola pareja."""
    candidatas = [
        a
        for c, a in acciones.items()
        if c.startswith(codigo + ".") or codigo.startswith(c + ".")
    ]
    return candidatas[0] if len(candidatas) == 1 else None


# ---------------------------------------------------------------------------
# Hojas 1 y 4: formulación y evaluación
# ---------------------------------------------------------------------------


def _leer_formulacion(hoja: _Hoja, alertas: list[str]) -> list[Oportunidad]:
    fila_enc = _buscar_encabezado(
        hoja, [("oportunidad de mejora", "oportunidad"), ("linea base",)]
    )
    if fila_enc is None:
        alertas.append(f"«{hoja.titulo}»: no encontré la fila de encabezados.")
        return []
    rot = _rotulos(hoja, fila_enc, 1)

    def buscar(*claves: str) -> int | None:
        return next((c for c, r in sorted(rot.items()) if _palabras(r, *claves)), None)

    c_op = buscar("oportunidad")
    c_lb, c_fa = buscar("linea base"), buscar("factor")
    c_ca, c_re = buscar("caracteristica"), buscar("relacion")
    salida: list[Oportunidad] = []
    for f in range(fila_enc + 1, hoja.max_fila + 1):
        if c_op is None or hoja.es_combinada_interior(f, c_op):
            continue
        texto = hoja.texto(f, c_op, combinada=False)
        if not texto:
            continue
        salida.append(
            Oportunidad(
                texto=texto,
                linea_base=hoja.texto(f, c_lb),
                factor=hoja.texto(f, c_fa),
                caracteristica=hoja.texto(f, c_ca),
                relacion_plan_accion=hoja.texto(f, c_re),
            )
        )
    return salida


def _leer_evaluacion(hoja: _Hoja, alertas: list[str]) -> list[Evaluacion]:
    fila_enc = _buscar_encabezado(hoja, [("fecha de evaluacion",), ("objetivo",)])
    if fila_enc is None:
        alertas.append(f"«{hoja.titulo}»: no encontré la fila de encabezados.")
        return []
    rot = _rotulos(hoja, fila_enc, 1)

    def buscar(*claves: str) -> int | None:
        return next(
            (c for c, r in sorted(rot.items()) if any(k in r for k in claves)), None
        )

    c_fe, c_ob = buscar("fecha de evaluacion"), buscar("objetivo")
    c_de, c_re = buscar("estado actual"), buscar("estado real")
    c_ds = buscar("descripcion")
    salida: list[Evaluacion] = []
    for f in range(fila_enc + 1, hoja.max_fila + 1):
        if c_ob is None or hoja.es_combinada_interior(f, c_ob):
            continue
        objetivo = hoja.texto(f, c_ob, combinada=False)
        if not objetivo:
            continue
        declarado = (
            como_porcentaje(hoja.valor(f, c_de), hoja.formato(f, c_de))
            if c_de
            else None
        )
        real = (
            como_porcentaje(hoja.valor(f, c_re), hoja.formato(f, c_re))
            if c_re
            else None
        )
        descripcion = hoja.texto(f, c_ds)
        if declarado is None and real is None and not descripcion:
            continue
        fechas = como_fechas(hoja.valor(f, c_fe)) if c_fe else []
        codigo, _, _ = separar_codigo(objetivo)
        salida.append(
            Evaluacion(
                fecha=fechas[-1] if fechas else None,
                objetivo_codigo=codigo,
                objetivo=objetivo,
                avance_declarado=declarado,
                avance_real=real,
                descripcion=descripcion,
            )
        )
    return salida


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def leer_plantilla(contenido: bytes) -> Lectura:
    """Lee un plan con la plantilla institucional. Errores: no se puede guardar.
    Alertas (en el plan): se puede guardar, pero alguien debe revisarlas."""
    lectura = Lectura()
    try:
        libro = load_workbook(io.BytesIO(contenido), data_only=True)
    except Exception:
        lectura.errores.append("No pude abrir el archivo: debe ser un .xlsx válido.")
        return lectura

    hojas_plan = _hojas(libro, "plan de mejora")
    if not hojas_plan:
        lectura.errores.append(
            "No encontré la hoja «2. Plan de Mejora». ¿El archivo usa la plantilla "
            "institucional del plan de mejoramiento?"
        )
        return lectura
    alertas: list[str] = []
    if len(hojas_plan) > 1:
        alertas.append(
            f"Hay {len(hojas_plan)} hojas de plan; leo solo «{hojas_plan[0].titulo}»."
        )
    hoja_plan = hojas_plan[0]
    objetivos = _leer_hoja_plan(hoja_plan, alertas)
    acciones = {a.codigo: a for o in objetivos for a in o.acciones}
    if not acciones:
        lectura.errores.append(
            f"«{hoja_plan.titulo}»: no encontré acciones con su % de avance o sus fechas."
        )
        return lectura

    formulacion = _hojas(libro, "formulacion")
    evaluacion = _hojas(libro, "evaluacion")
    programa = _programa(hoja_plan, 5) or (
        _programa(formulacion[0], 5) if formulacion else ""
    )
    if not programa:
        lectura.errores.append(
            "No encontré el nombre del programa en las primeras filas de la hoja del plan."
        )
        return lectura

    cronogramas: list[int] = []
    for hoja in sorted(_hojas(libro, "cronograma"), key=lambda h: h.titulo.strip()):
        _leer_cronograma(hoja, acciones, alertas)
        anios = re.findall(r"20\d\d", hoja.titulo)
        if anios:
            cronogramas.append(int(anios[0]))
    if not cronogramas:
        alertas.append("No encontré hojas «3. Cronograma 20XX».")
    if not formulacion:
        alertas.append("No encontré la hoja «1. Formulación».")
    if not evaluacion:
        alertas.append("No encontré la hoja «4. Evaluación».")

    lectura.plan = Plan(
        programa=programa,
        objetivos=objetivos,
        oportunidades=[o for h in formulacion for o in _leer_formulacion(h, alertas)],
        evaluaciones=[e for h in evaluacion for e in _leer_evaluacion(h, alertas)],
        cronogramas=sorted(cronogramas),
        alertas=alertas,
    )
    return lectura
