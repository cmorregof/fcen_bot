"""Fuentes citables de cada acción en un corte y reglas de privacidad.

Todo lo que el modelo puede citar sale de aquí, con un ID por fuente:

    [P1]   la acción en el plan (hoja y fila) y sus tareas del cronograma
    [C1]   lo escrito en un corte anterior
    [E1]   un enlace de evidencia registrado (en el plan o con /evidencia)
    [S012] un soporte que el revisor ya describió (ID de su inventario)

El catálogo se arma sin modelo. Decide también, sin modelo, si la acción tiene
evidencia nueva en el corte: si no la tiene, el borrador lo dice y no se le
pregunta nada al modelo.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from app.servicios.calidad.plan import CorteGuardado, PlanGuardado
from app.servicios.calidad.plantilla import Accion, Objetivo, TareaCronograma, plegar
from app.servicios.calidad.soportes.modelos import DescripcionArchivo

ID = r"(?:[PCE]\d+|S\d{3,})"
PATRON_ID = re.compile(rf"\b{ID}\b")
# Un corchete con uno o varios IDs: [P2], [P2, E1], [S012; C1].
PATRON_CITA = re.compile(rf"\[({ID}(?:\s*[,;]\s*{ID})*)\]")

# Cortes anteriores que se le muestran al modelo como contexto.
MAX_CORTES_PREVIOS = 2
# Cada fuente se recorta para que el prompt tenga un tamaño predecible.
MAX_CARACTERES_FUENTE = 900

CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TELEFONO = re.compile(r"(?<!\d)(?:\+?57)?\s?3\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
# «profesor Juan Pérez», «la doctora Ana Gómez»: un título seguido de un nombre.
TITULO_Y_NOMBRE = re.compile(
    r"\b(?i:profesora?|docente|director[a]?|coordinador[a]?|ingenier[oa]|"
    r"doctor[a]?|dr|dra|mg|phd|sr|sra|se[ñn]or[a]?|estudiante)\.?\s+"
    r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+"
)

# Palabras de cargos y dependencias: lo que SÍ puede escribirse.
_CARGOS = {
    plegar(p)
    for p in (
        "dirección direccion director directora coordinación coordinacion "
        "coordinador coordinadora comité comite asesor asesora oficina calidad "
        "programa facultad decanatura decano decana vicedecanatura consejo sede "
        "secretaría secretaria académica academica área area unidad jefe jefatura "
        "profesor profesora docente docentes estudiantes estudiante bienestar "
        "departamento escuela maestría maestria doctorado posgrado pregrado "
        "curricular grupo equipo ejemplo ficticio universidad nacional manizales "
        "investigación investigacion extensión extension acreditación acreditacion "
        "autoevaluación autoevaluacion sistema servicio apoyo gestión gestion "
        "ciencias exactas naturales ingeniería ingenieria arquitectura "
        "administración administracion humanas económicas economicas sociales "
        "salud artes educación educacion física fisica química quimica "
        "matemáticas matematicas biología biologia geología geologia "
        "estadística estadistica computación computacion ambiental biotecnología "
        "biotecnologia ecología ecologia currículo curriculo plan mejoramiento "
        "sede nacional colombia caldas"
    ).split()
}
_ENLACES = {"de", "del", "la", "el", "los", "las", "y", "e", "en", "para", "con"}


@dataclass
class Fuente:
    id: str
    tipo: str  # plan | corte | enlace | soporte
    texto: str  # lo que ve el modelo
    ref: str  # lo que lee la persona: hoja y fila, enlace o soporte
    nueva: bool = False
    # La acción en el plan: da el % declarado pero no respalda hechos.
    contexto: bool = False


@dataclass
class AccionCorte:
    accion: Accion
    objetivo: Objetivo
    corte: date
    fuentes: list[Fuente] = field(default_factory=list)
    existente: str = ""  # lo que el plan ya trae escrito para este corte
    anterior: date | None = None  # el corte anterior que el plan conoce
    # Textos del plan ya sin nombres, correos ni teléfonos: son los únicos que
    # viajan al modelo y a las salidas.
    objetivo_texto: str = ""
    descripcion: str = ""
    indicador: str = ""

    @property
    def hay_evidencia_nueva(self) -> bool:
        return any(f.nueva for f in self.fuentes)

    def por_id(self) -> dict[str, Fuente]:
        return {f.id: f for f in self.fuentes}


# ---------------------------------------------------------------------------
# Nombres de personas
# ---------------------------------------------------------------------------


def nombres_en_plan(pg: PlanGuardado) -> set[str]:
    """Nombres de personas que el plan trae en los campos de responsables.

    Los campos suelen traer cargos («Dirección del programa»); un segmento se
    toma como nombre si, quitando palabras de cargos y conectores, le quedan
    dos o más palabras con mayúscula inicial.
    """
    campos: list[str] = []
    for a in pg.plan.acciones:
        campos.append(a.responsables)
        campos += [t.responsable for t in a.tareas]
    nombres: set[str] = set()
    for campo in campos:
        for segmento in re.split(r"[,;/\n]|\s+y\s+|\s+e\s+", campo or ""):
            restantes = [
                p
                for p in re.findall(r"[^\W\d_]+", segmento)
                if p[:1].isupper()
                and plegar(p) not in _CARGOS
                and plegar(p) not in _ENLACES
            ]
            if len(restantes) >= 2:
                nombres.add(" ".join(restantes))
                nombres.update(
                    f"{a} {b}" for a, b in zip(restantes, restantes[1:], strict=False)
                )
    return nombres


def _plano(texto: str) -> tuple[str, list[int]]:
    """Minúsculas y sin tildes, con la posición original de cada carácter."""
    salida: list[str] = []
    mapa: list[int] = []
    for i, ch in enumerate(texto):
        for d in unicodedata.normalize("NFKD", ch):
            if not unicodedata.combining(d):
                salida.append(d.lower())
                mapa.append(i)
    return "".join(salida), mapa


def _tramos(texto: str, nombres: set[str]) -> list[tuple[int, int]]:
    """Dónde aparece cada nombre como palabra completa, sin importar tildes
    ni mayúsculas. Posiciones del texto original."""
    plano, mapa = _plano(texto)
    tramos: list[tuple[int, int]] = []
    for nombre in nombres:
        buscado = _plano(nombre)[0].strip()
        if not buscado:
            continue
        for m in re.finditer(rf"(?<!\w){re.escape(buscado)}(?!\w)", plano):
            tramos.append((mapa[m.start()], mapa[m.end() - 1] + 1))
    return tramos


def ocultar(texto: str, nombres: set[str]) -> str:
    """Quita nombres conocidos, títulos con nombre, correos y teléfonos antes
    de mandar o mostrar texto del plan o de los soportes."""
    fusion: list[list[int]] = []
    for ini, fin in sorted(_tramos(texto, nombres)):
        if fusion and ini <= fusion[-1][1]:
            fusion[-1][1] = max(fusion[-1][1], fin)
        else:
            fusion.append([ini, fin])
    for ini, fin in reversed(fusion):
        texto = texto[:ini] + "[responsable]" + texto[fin:]
    texto = TITULO_Y_NOMBRE.sub("[persona]", texto)
    texto = CORREO.sub("[correo]", texto)
    return TELEFONO.sub("[teléfono]", texto)


def con_nombre_de_persona(texto: str, nombres: set[str]) -> bool:
    """Verificación de la salida: un nombre conocido, un correo, un teléfono o
    un título seguido de un nombre."""
    if CORREO.search(texto) or TELEFONO.search(texto) or TITULO_Y_NOMBRE.search(texto):
        return True
    return bool(_tramos(texto, nombres))


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------


def citas_en_texto(texto: str) -> list[str]:
    ids: list[str] = []
    for grupo in PATRON_CITA.findall(texto or ""):
        ids += PATRON_ID.findall(grupo)
    return ids


def _recorte(texto: str) -> str:
    texto = " ".join(texto.split())
    return (
        texto
        if len(texto) <= MAX_CARACTERES_FUENTE
        else texto[:MAX_CARACTERES_FUENTE] + "…"
    )


def _enlaces(texto: str) -> list[str]:
    return [u.rstrip(".,;)") for u in re.findall(r"https?://\S+", texto or "")]


def cortes_de(pg: PlanGuardado, accion: Accion) -> list[CorteGuardado]:
    """Cortes de la acción: el historial guardado, o los del último archivo."""
    guardados = pg.cortes.get(accion.codigo)
    if guardados:
        return list(guardados)
    return [
        CorteGuardado(0, c.rotulo, c.fecha, c.descripcion, c.evidencias, 0)
        for c in accion.cortes
    ]


def fechas_de_corte(pg: PlanGuardado) -> list[date]:
    """Fechas de corte que el plan ya conoce, de la más reciente a la más vieja."""
    fechas = {
        c.fecha
        for a in pg.plan.acciones
        for c in cortes_de(pg, a)
        if c.fecha is not None
    }
    return sorted(fechas, reverse=True)


def armar(
    pg: PlanGuardado,
    corte: date,
    soportes_revisor: dict[str, list[tuple[str, DescripcionArchivo]]],
    nombres: set[str],
) -> list[AccionCorte]:
    """Una `AccionCorte` por acción del plan, con sus fuentes numeradas."""
    resultado: list[AccionCorte] = []
    for objetivo in pg.plan.objetivos:
        for accion in objetivo.acciones:
            resultado.append(
                _una(pg, objetivo, accion, corte, soportes_revisor, nombres)
            )
    return resultado


def _una(
    pg: PlanGuardado,
    objetivo: Objetivo,
    a: Accion,
    corte: date,
    soportes_revisor: dict[str, list[tuple[str, DescripcionArchivo]]],
    nombres: set[str],
) -> AccionCorte:
    cortes = cortes_de(pg, a)
    previos = [c for c in cortes if c.fecha is not None and c.fecha < corte]
    previos.sort(key=lambda c: c.fecha or date.min)
    anterior = previos[-1].fecha if previos else None
    actuales = [c for c in cortes if c.fecha == corte]
    ac = AccionCorte(
        a,
        objetivo,
        corte,
        existente=ocultar(
            " ".join(c.descripcion for c in actuales if c.descripcion).strip(),
            nombres,
        ),
        anterior=anterior,
        objetivo_texto=ocultar(objetivo.texto, nombres),
        descripcion=ocultar(a.descripcion, nombres),
        indicador=ocultar(a.indicador, nombres),
    )
    n = {"P": 0, "C": 0, "E": 0}

    def nuevo(prefijo: str) -> str:
        n[prefijo] += 1
        return f"{prefijo}{n[prefijo]}"

    def agregar(
        prefijo: str,
        tipo: str,
        texto: str,
        ref: str,
        nueva: bool,
        contexto: bool = False,
    ) -> None:
        ac.fuentes.append(
            Fuente(
                nuevo(prefijo),
                tipo,
                ocultar(_recorte(texto), nombres),
                ref,
                nueva,
                contexto,
            )
        )

    # La acción en el plan: contexto, nunca evidencia nueva ni respaldo de hechos.
    partes = [f"avance declarado en el plan: {_pct(a.avance)}"]
    if a.fecha_inicio or a.fecha_fin:
        partes.append(f"fechas {a.fecha_inicio or '?'} a {a.fecha_fin or '?'}")
    if a.reprogramada:
        partes.append("tiene reprogramaciones")
    if a.marcas:
        partes.append("marcas del plan: " + ", ".join(a.marcas))
    agregar(
        "P",
        "plan",
        "Acción en el plan: " + "; ".join(partes),
        a.origen,
        False,
        contexto=True,
    )

    for t in a.tareas:
        hecha = _hecha(t)
        datos = [f"«{t.descripcion}»", f"avance {_pct(t.avance)}"]
        datos.append("marcada como cumplida" if hecha else "sin marcar como cumplida")
        if t.fecha_fin:
            datos.append(f"fecha fin {t.fecha_fin}")
        if t.soporte:
            datos.append(f"soporte esperado: {t.soporte}")
        if t.reprogramada:
            datos.append("reprogramada")
        if t.estado_texto:
            datos.append(f"nota del plan: {t.estado_texto}")
        agregar(
            "P",
            "plan",
            "Tarea del cronograma: " + "; ".join(datos),
            f"«{t.hoja}» fila {t.fila}",
            # El cronograma trae fechas planeadas, no la fecha en que se cumplió
            # cada tarea: sirve de contexto, no de evidencia nueva.
            False,
        )

    for c in previos[-MAX_CORTES_PREVIOS:]:
        if c.descripcion:
            agregar(
                "C",
                "corte",
                f"Descripción escrita en el corte {c.fecha}: «{c.descripcion}»",
                f"corte {c.fecha} de {a.origen}",
                False,
            )

    vistos: set[str] = set()
    previas = {u for c in previos for u in _enlaces(c.evidencias)}
    for c in actuales:
        for url in _enlaces(c.evidencias):
            if url not in vistos:
                vistos.add(url)
                agregar(
                    "E",
                    "enlace",
                    f"Enlace de evidencia del corte {c.fecha} (no se ve su contenido): {url}",
                    url,
                    url not in previas,
                )
    for url in _enlaces(a.evidencias):
        if url not in vistos:
            vistos.add(url)
            agregar(
                "E",
                "enlace",
                f"Enlace de evidencia en el plan (no se ve su contenido): {url}",
                url,
                False,
            )
    for t in a.tareas:
        for url in _enlaces(t.enlace):
            if url not in vistos:
                vistos.add(url)
                agregar(
                    "E",
                    "enlace",
                    f"Enlace de la tarea «{t.descripcion}» en el cronograma "
                    f"(no se ve su contenido): {url}",
                    url,
                    False,
                )
    for s in pg.soportes.get(a.codigo, []):
        if s.tipo != "enlace" or s.valor in vistos:
            continue
        vistos.add(s.valor)
        registrado = s.creado[:10]
        nueva = _entre(_fecha_iso(registrado), anterior, corte)
        agregar(
            "E",
            "enlace",
            f"Enlace de evidencia registrado el {registrado} (no se ve su "
            f"contenido): {s.valor}",
            f"{s.valor} (registrado el {registrado})",
            nueva,
        )

    # Soportes que el revisor ya describió. Son nuevos solo si la fecha del
    # documento cae por completo entre el corte anterior (exclusivo) y este;
    # sin fecha legible son contexto.
    for id_, d in soportes_revisor.get(a.codigo, []):
        texto = f"Soporte descrito por el revisor: {d.que_es}"
        if d.fecha_documento:
            texto += f"; fecha del documento {d.fecha_documento}"
        if d.que_prueba:
            texto += f"; podría probar: {d.que_prueba}"
        if d.ilegible_o_incompleto:
            texto += "; se ve ilegible o incompleto"
        ac.fuentes.append(
            Fuente(
                id_,
                "soporte",
                ocultar(_recorte(texto), nombres),
                f"soporte {id_} del inventario del revisor",
                not d.ilegible_o_incompleto
                and _periodo_en(d.fecha_documento, anterior, corte),
            )
        )
    return ac


def _hecha(t: TareaCronograma) -> bool:
    return bool(t.ok) or (t.avance is not None and t.avance >= 100)


def _fecha_iso(texto: str) -> date | None:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _entre(fecha: date | None, anterior: date | None, corte: date) -> bool:
    """anterior < fecha <= corte, con la fecha real; sin fecha, no es nueva."""
    return (
        fecha is not None and fecha <= corte and (anterior is None or fecha > anterior)
    )


def _periodo_en(texto: str, anterior: date | None, corte: date) -> bool:
    """«AAAA-MM-DD», «AAAA-MM» o «AAAA»: el periodo entero está en la ventana."""
    m = re.fullmatch(r"\s*(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?\s*", texto or "")
    if not m:
        return False
    anio, mes, dia = int(m[1]), int(m[2] or 0), int(m[3] or 0)
    try:
        if dia:
            ini = fin = date(anio, mes, dia)
        elif mes:
            ini, fin = (
                date(anio, mes, 1),
                date(anio, mes, calendar.monthrange(anio, mes)[1]),
            )
        else:
            ini, fin = date(anio, 1, 1), date(anio, 12, 31)
    except ValueError:
        return False
    return fin <= corte and (anterior is None or ini > anterior)


def _pct(valor: float | None) -> str:
    return "sin dato" if valor is None else f"{valor:.0f} %"
