"""Verificaciones deterministas. Ninguna usa el modelo.

Cada regla cita la norma de donde sale. Las reglas no deciden: producen
alertas para la administrativa y datos para el ANÁLISIS del acta.

Los umbrales (carga mínima, semanas límite, créditos disciplinares para el
Trabajo de Grado, mínimo de jurados) están en config/solicitudes.yaml, que
edita la Vicedecanatura Académica; cada uno cita su norma o su fuente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.core import solicitudes
from app.core.programas import Programa, normalizar
from app.schemas.caso import (
    Alerta,
    DatosSIA,
    ExtraccionCaso,
    FilaCreditos,
    TipoSolicitud,
)

# Los jurados se recomiendan, no se proponen: no es norma.
INSTRUCCION_JURADOS = "instrucción del Consejo de Facultad, 28-oct-2026"

_COLUMNAS = ("exigidos", "aprobados", "pendientes", "inscritos", "cursados")


@dataclass
class Analisis:
    creditos_inscritos: int | None = None
    creditos_tras_solicitud: int | None = None
    disciplinares_aprobados: int | None = None
    disciplinares_exigidos_tdg: int | None = None
    papa: float | None = None
    porcentaje_avance: float | None = None
    semana: int | None = None
    alertas: list[Alerta] = field(default_factory=list)

    def agregar(self, nivel: str, mensaje: str) -> None:
        self.alertas.append(Alerta(nivel=nivel, mensaje=mensaje))  # type: ignore[arg-type]


def _fila(sia: DatosSIA, nombre: str) -> FilaCreditos | None:
    objetivo = normalizar(nombre)
    for fila in sia.resumen_creditos:
        if normalizar(fila.tipologia) == objetivo:
            return fila
    return None


def _filas_base(sia: DatosSIA) -> list[FilaCreditos]:
    """Filas por tipología, sin TOTAL, NIVELACIÓN ni TOTAL ESTUDIANTE."""
    especiales = {"total", "nivelacion", "total estudiante"}
    return [
        f for f in sia.resumen_creditos if normalizar(f.tipologia) not in especiales
    ]


def verificar_tabla_sia(sia: DatosSIA) -> list[str]:
    """Las sumas que la tabla del SIA siempre cumple. Si no cuadran, se leyó mal."""
    problemas: list[str] = []
    base = _filas_base(sia)
    total = _fila(sia, "TOTAL")
    nivelacion = _fila(sia, "NIVELACIÓN")
    total_est = _fila(sia, "TOTAL ESTUDIANTE")
    if total and base:
        for col in _COLUMNAS:
            valores = [getattr(f, col) for f in base]
            esperado = getattr(total, col)
            if esperado is None or any(v is None for v in valores):
                continue
            suma = sum(v for v in valores if v is not None)
            if suma != esperado:
                problemas.append(
                    f"la columna {col} suma {suma} pero TOTAL dice {esperado}"
                )
    if total and nivelacion and total_est:
        for col in _COLUMNAS:
            a, b, c = (
                getattr(total, col),
                getattr(nivelacion, col),
                getattr(total_est, col),
            )
            if None not in (a, b, c) and a + b != c:
                problemas.append(
                    f"TOTAL + NIVELACIÓN en {col} da {a + b} pero TOTAL ESTUDIANTE dice {c}"
                )
    for f in base:
        if None in (f.exigidos, f.aprobados, f.pendientes):
            continue
        assert f.exigidos is not None and f.aprobados is not None
        if f.pendientes != max(f.exigidos - f.aprobados, 0):
            problemas.append(
                f"en {f.tipologia}, exigidos − aprobados no coincide con pendientes"
            )
    return problemas


def creditos_inscritos(sia: DatosSIA) -> int | None:
    total = _fila(sia, "TOTAL ESTUDIANTE") or _fila(sia, "TOTAL")
    if total and total.inscritos is not None:
        return total.inscritos
    creditos = [c.creditos for c in sia.cursos_inscritos]
    if creditos and all(c is not None for c in creditos):
        return sum(c for c in creditos if c is not None)
    return None


def disciplinares_aprobados(sia: DatosSIA) -> int | None:
    filas = [
        f for f in _filas_base(sia) if normalizar(f.tipologia).startswith("disciplinar")
    ]
    if not filas or any(f.aprobados is None for f in filas):
        return None
    return sum(f.aprobados for f in filas if f.aprobados is not None)


def _ya_inscritas(sia: DatosSIA | None) -> set[str]:
    if sia is None:
        return set()
    return {(c.codigo or "").strip() for c in sia.cursos_inscritos if c.codigo}


def _es_trabajo_grado(texto: str | None) -> bool:
    return normalizar(texto or "").startswith(normalizar("Trabajo de Grado"))


def creditos_tras_solicitud(
    extraccion: ExtraccionCaso, inscritos: int | None
) -> int | None:
    """Créditos inscritos después de las inscripciones y cancelaciones pedidas.

    Una asignatura que el estudiante pide «inscribir» pero que ya aparece en
    los cursos inscritos del SIA no se vuelve a sumar. Tampoco el Trabajo de
    Grado pedido sin código cuando el SIA ya muestra uno inscrito.
    """
    if inscritos is None or not extraccion.asignaturas:
        return None
    ya = _ya_inscritas(extraccion.sia)
    tdg_inscrito = extraccion.sia is not None and any(
        _es_trabajo_grado(c.tipologia) for c in extraccion.sia.cursos_inscritos
    )
    delta = 0
    for asig in extraccion.asignaturas:
        if asig.accion == "apertura":
            continue
        if asig.accion == "inscribir" and (asig.codigo or "").strip() in ya:
            continue
        if (
            asig.accion == "inscribir"
            and not (asig.codigo or "").strip()
            and tdg_inscrito
            and _es_trabajo_grado(asig.nombre)
        ):
            continue
        if asig.creditos is None:
            return None
        delta += asig.creditos if asig.accion == "inscribir" else -asig.creditos
    return inscritos + delta


def completar_tipos(extraccion: ExtraccionCaso) -> ExtraccionCaso:
    """Agrega «carga mínima» cuando el estudiante quedaría por debajo de ella.

    Art. 10 del Acuerdo 008 de 2008: inscribir menos de la carga mínima
    requiere autorización del Consejo de Facultad, aunque el estudiante no lo
    pida con ese nombre (p. ej., quien solo inscribe Trabajo de Grado). El
    valor sale de config/solicitudes.yaml.
    """
    sia = extraccion.sia
    if sia is None or TipoSolicitud.CARGA_MINIMA in extraccion.tipos:
        return extraccion
    inscritos = creditos_inscritos(sia)
    if inscritos is None:
        return extraccion
    tras = creditos_tras_solicitud(extraccion, inscritos)
    final = tras if tras is not None else inscritos
    if final >= solicitudes.actual().umbrales.carga_minima.valor:
        return extraccion
    return extraccion.model_copy(
        update={"tipos": [*extraccion.tipos, TipoSolicitud.CARGA_MINIMA]}
    )


def _normalizar_saltos(texto: str) -> str:
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def cita_literal(
    cita: str, texto_original: str, cuerpo_transcrito: str | None = None
) -> bool:
    """La cita es una subcadena exacta del texto de donde sale: el correo o el
    formato pegados o, si el correo llegó como imagen, su transcripción. Solo
    se toleran los saltos de línea de Windows y los espacios de los extremos."""
    fragmento = _normalizar_saltos(cita).strip()
    if not fragmento:
        return True
    fuentes = [texto_original, cuerpo_transcrito or ""]
    return any(fragmento in _normalizar_saltos(f) for f in fuentes if f.strip())


# En el oficio y el acta los jurados se recomiendan; el estudiante no los
# «propone» ni los «sugiere» (instrucción del Consejo de Facultad, 28-oct-2026).
_PROPONE = re.compile(r"\b(propon|propues|propus|sugier|suger|sugir)\w*", re.IGNORECASE)


def semana_del_periodo(fecha: str | None, inicio: date | None) -> int | None:
    if not fecha or not inicio:
        return None
    try:
        dia = date.fromisoformat(fecha[:10])
    except ValueError:
        return None
    dias = (dia - inicio).days
    return dias // 7 + 1 if dias >= 0 else 0


def lleva_zapc(e: ExtraccionCaso) -> bool:
    """ZAPC solo se abre con asignaturas de posgrado (§5.4)."""
    return "posgrado" in (e.modalidad_trabajo_grado or "").lower() and any(
        a.accion == "apertura" for a in e.asignaturas
    )


def analizar(
    extraccion: ExtraccionCaso,
    programa: Programa | None,
    *,
    periodo_inicio: date | None,
    hay_imagenes: bool,
    texto_original: str | None = None,
    jurados_minimo: int | None = None,
) -> Analisis:
    """`texto_original` es el texto pegado del caso; sin él no se verifica la
    cita. Si `jurados_minimo` es None, sale de la variable JURADOS_MINIMO o,
    si no está definida, de config/solicitudes.yaml."""
    a = Analisis()
    tipos = set(extraccion.tipos)
    config = solicitudes.actual()
    umbrales = config.umbrales
    if jurados_minimo is None:
        jurados_minimo = solicitudes.jurados_minimo()

    # Identificación
    doc = (extraccion.documento or "").strip()
    if not doc:
        a.agregar("error", "No encontré el número de documento del estudiante.")
    elif not doc.isdigit():
        a.agregar("aviso", f"El documento «{doc}» tiene caracteres que no son dígitos.")
    elif len(doc) == 9 or len(doc) < 6 or len(doc) > 11:
        a.agregar(
            "aviso",
            f"El documento {doc} tiene {len(doc)} dígitos, algo inusual: verifícalo.",
        )
    if not extraccion.nombre_estudiante:
        a.agregar("error", "No encontré el nombre del estudiante.")
    if not extraccion.fecha_solicitud:
        a.agregar("aviso", "No encontré la fecha del correo.")
    if not extraccion.tipos:
        a.agregar("aviso", "No identifiqué el tipo de solicitud.")

    for asig in extraccion.asignaturas:
        if asig.accion != "apertura" and not (asig.grupo or "").strip():
            a.agregar(
                "aviso",
                f"Falta el grupo de {asig.nombre}: el cuadro del oficio lo exige. "
                "Responde a la ficha con el grupo.",
            )

    # Cuadro comparativo: sin él no se puede ejecutar el reconocimiento.
    filas = [f for c in extraccion.equivalencias for f in c.filas]
    if not filas and tipos & {
        TipoSolicitud.TRASLADO,
        TipoSolicitud.DOBLE_TITULACION,
        TipoSolicitud.HOMOLOGACION,
    }:
        a.agregar(
            "info",
            "La solicitud no trae cuadro de equivalencias. Si el trámite lo "
            "requiere, pídelo al estudiante o agrégalo con una corrección.",
        )
    sin_destino = [
        f.origen.nombre or f.origen.codigo or "?"
        for f in filas
        if not (f.destino.codigo and f.destino.nombre)
    ]
    if sin_destino:
        a.agregar(
            "aviso",
            "En el cuadro de equivalencias falta el código o el nombre de destino de: "
            + ", ".join(sin_destino)
            + ".",
        )

    # La cita del oficio tiene que estar tal cual en lo que escribió el estudiante.
    cita = (extraccion.cita_textual or "").strip()
    if (
        cita
        and texto_original is not None
        and not cita_literal(cita, texto_original, extraccion.cuerpo_transcrito)
    ):
        muestra = cita if len(cita) <= 80 else cita[:80] + "…"
        a.agregar(
            "error",
            f"La cita «{muestra}» no aparece tal cual en lo que escribió el "
            "estudiante. No la corregí: en el borrador sale en amarillo. Responde "
            "a la ficha con el fragmento exacto.",
        )

    # Proyecto de tesis o trabajo final de posgrado
    if TipoSolicitud.PROYECTO_TESIS in tipos:
        proyecto = extraccion.proyecto
        faltan = [
            nombre
            for nombre, valor in (
                ("el título", proyecto.titulo if proyecto else None),
                ("el director", proyecto.director if proyecto else None),
            )
            if not (valor or "").strip()
        ]
        if faltan:
            a.agregar(
                "aviso",
                f"Falta {' y '.join(faltan)} del proyecto: en el borrador sale en "
                "amarillo. Responde a la ficha con el dato.",
            )
        if programa is not None and programa.nivel != "posgrado":
            a.agregar(
                "aviso",
                f"Es una inscripción de proyecto de tesis, pero el programa es "
                f"{programa.nombre} (pregrado). Revisa el programa del caso.",
            )

    # Jurados de Trabajo de Grado
    if TipoSolicitud.DESIGNACION_JURADOS in tipos or extraccion.jurados:
        n = len(extraccion.jurados)
        if n < jurados_minimo:
            a.agregar(
                "aviso",
                f"La solicitud trae {n} jurado{'' if n == 1 else 's'}; se presentan "
                f"mínimo {jurados_minimo} ({umbrales.jurados_minimo.cita}"
                + ("" if umbrales.jurados_minimo.norma else "; no es norma")
                + ").",
            )
        if _PROPONE.search(extraccion.objeto_solicitud):
            a.agregar(
                "aviso",
                "La frase de la solicitud dice que el estudiante propone o sugiere "
                "jurados. En el oficio los jurados se recomiendan "
                f"({INSTRUCCION_JURADOS}): corrígela respondiendo a la ficha.",
            )

    if any(a.accion == "apertura" for a in extraccion.asignaturas) and not lleva_zapc(
        extraccion
    ):
        a.agregar(
            "aviso",
            "La solicitud trae una apertura (ZAPC) pero no es de asignaturas de "
            "posgrado: no saldrá en el oficio ni en el acta. Revísala.",
        )

    # Historia académica
    sia = extraccion.sia
    if sia is None or not sia.resumen_creditos:
        detalle = (
            "Los pantallazos no muestran el «Resumen de créditos»."
            if hay_imagenes
            else "No hay pantallazos de la historia académica."
        )
        a.agregar("aviso", detalle)
    else:
        for problema in verificar_tabla_sia(sia):
            a.agregar("aviso", f"Revisa la lectura del pantallazo: {problema}.")
        a.creditos_inscritos = creditos_inscritos(sia)
        a.disciplinares_aprobados = disciplinares_aprobados(sia)
        a.papa = sia.papa
        a.porcentaje_avance = sia.porcentaje_avance

    # Créditos después de la solicitud
    if a.creditos_inscritos is not None:
        a.creditos_tras_solicitud = creditos_tras_solicitud(
            extraccion, a.creditos_inscritos
        )
        final = (
            a.creditos_tras_solicitud
            if a.creditos_tras_solicitud is not None
            else a.creditos_inscritos
        )
        carga = umbrales.carga_minima
        if final < carga.valor:
            if TipoSolicitud.CARGA_MINIMA in tipos:
                ruta = config.ruta(TipoSolicitud.CARGA_MINIMA)
                quien = (
                    "quién la autoriza está por confirmar"
                    if ruta.por_confirmar
                    else f"la autoriza el {ruta.nombre_decide}"
                )
                a.agregar(
                    "info",
                    f"Quedaría con {final} créditos inscritos, por debajo de la carga "
                    f"mínima de {carga.valor} ({carga.cita}): {quien}.",
                )
            else:
                a.agregar(
                    "aviso",
                    f"Quedaría con {final} créditos inscritos, por debajo de la carga "
                    f"mínima de {carga.valor}, y la solicitud no pide carga mínima.",
                )

    # Semana del periodo (Acuerdo 027 de 2024; Acuerdo 089 de 2014 para traslados)
    a.semana = semana_del_periodo(extraccion.fecha_solicitud, periodo_inicio)
    sensibles = {
        TipoSolicitud.INSCRIPCION_EXTEMPORANEA,
        TipoSolicitud.TRABAJO_GRADO,
        TipoSolicitud.PAE,
        TipoSolicitud.TRASLADO,
    }
    if tipos & sensibles:
        if a.semana is None:
            if periodo_inicio is None:
                a.agregar(
                    "info",
                    "No puedo verificar la semana límite: falta configurar la fecha "
                    "de inicio del periodo (PERIODO_INICIO).",
                )
            elif extraccion.fecha_solicitud:
                a.agregar(
                    "aviso",
                    f"No entendí la fecha «{extraccion.fecha_solicitud}»: no pude "
                    "verificar la semana límite.",
                )
        else:
            sem_asig = umbrales.semana_limite_asignaturas
            sem_tdg = umbrales.semana_limite_tdg_actividades
            sem_traslado = umbrales.semana_limite_traslado
            if TipoSolicitud.TRASLADO in tipos and a.semana >= sem_traslado.valor:
                a.agregar(
                    "aviso",
                    f"Llegó en la semana {a.semana}; el traslado se presenta antes de la "
                    f"semana {sem_traslado.valor} ({sem_traslado.cita}).",
                )
            # Trabajo de Grado (en cualquier modalidad) y actividades académicas:
            # semana 13. Demás asignaturas: semana 10.
            limite: solicitudes.Umbral | None = None
            if tipos & {TipoSolicitud.TRABAJO_GRADO, TipoSolicitud.PAE}:
                limite = sem_tdg
            elif TipoSolicitud.INSCRIPCION_EXTEMPORANEA in tipos:
                limite = sem_asig
            if (
                limite is sem_tdg
                and TipoSolicitud.INSCRIPCION_EXTEMPORANEA in tipos
                and sem_asig.valor < a.semana <= sem_tdg.valor
            ):
                a.agregar(
                    "aviso",
                    f"Llegó en la semana {a.semana}: el Trabajo de Grado se puede "
                    f"autorizar hasta la semana {sem_tdg.valor}, pero las demás "
                    f"asignaturas solo hasta la {sem_asig.valor} ({sem_asig.cita}).",
                )
            if limite is not None and a.semana > limite.valor:
                a.agregar(
                    "aviso",
                    f"Llegó en la semana {a.semana}; el Consejo de Facultad puede "
                    f"autorizarla hasta la semana {limite.valor} ({limite.cita}).",
                )

    # Regla propia del programa para Trabajo de Grado
    exigidos = umbrales.tdg_creditos(programa.clave if programa else None)
    if exigidos and TipoSolicitud.TRABAJO_GRADO in tipos:
        a.disciplinares_exigidos_tdg = exigidos.valor
        if (
            a.disciplinares_aprobados is not None
            and a.disciplinares_aprobados < exigidos.valor
        ):
            pide_excepcion = TipoSolicitud.EXCEPCION_NORMA in tipos
            a.agregar(
                "info" if pide_excepcion else "aviso",
                f"Tiene {a.disciplinares_aprobados} de los "
                f"{exigidos.valor} créditos disciplinares que "
                "exige el programa para inscribir Trabajo de Grado"
                + (
                    "; la solicitud pide la excepción."
                    if pide_excepcion
                    else ": haría falta una excepción a la norma."
                ),
            )

    # Las dudas del modelo que repiten lo que ya avisan las reglas se omiten.
    ya_revisado = ("documento", "cédula", "cedula", "dni", "correo", "nombre", "fecha")
    for duda in extraccion.dudas[:3]:
        if any(p in duda.lower() for p in ya_revisado):
            continue
        a.agregar("aviso", f"El modelo no está seguro: {duda}")
    return a
