"""La ficha que el bot responde por cada caso. HTML de Telegram."""

from __future__ import annotations

from html import escape

from app.core.programas import PROGRAMAS
from app.normativa.base import normas_para
from app.schemas.caso import TITULOS_TIPO, Caso, Sentido
from app.services.reglas import Analisis

_ICONO = {"error": "🔴", "aviso": "🟡", "info": "ℹ️"}
_SENTIDO = {
    Sentido.PENDIENTE: "pendiente del comité",
    Sentido.APROBAR: "APROBAR",
    Sentido.NO_APROBAR: "NO APROBAR",
}


def _num(valor: float | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:.1f}" if isinstance(valor, float) else str(valor)
    return texto.replace(".", ",")


def ficha(caso: Caso, analisis: Analisis) -> str:
    e = caso.extraccion
    if e is None:
        return f"Caso #{caso.id}: sin datos todavía."
    programa = PROGRAMAS.get(caso.programa or "")
    lineas = [
        f"<b>Caso #{caso.id}</b> · {escape(programa.nombre if programa else 'programa sin identificar')}"
    ]
    nombre = escape(e.nombre_estudiante or "¿nombre?")
    lineas.append(
        f"{escape(e.tratamiento)} <b>{nombre}</b> · DNI {escape(e.documento or '¿?')}"
    )
    fecha = escape(e.fecha_solicitud or "¿fecha?")
    if analisis.semana is not None:
        fecha += f" (semana {analisis.semana})"
    lineas.append(f"Solicitud del {fecha}")
    if e.tipos:
        lineas.append("Tipo: " + ", ".join(escape(TITULOS_TIPO[t]) for t in e.tipos))
    if e.objeto_solicitud:
        lineas.append(f"Pide: {escape(e.objeto_solicitud)}")
    if e.modalidad_trabajo_grado:
        lineas.append(f"Modalidad TdG: {escape(e.modalidad_trabajo_grado)}")
    for asig in e.asignaturas:
        cred = f", {asig.creditos} cr." if asig.creditos is not None else ""
        cod = f"{asig.codigo} " if asig.codigo else ""
        grupo = f", grupo {escape(asig.grupo)}" if asig.grupo else ""
        lineas.append(f"  · {asig.accion}: {escape(cod + asig.nombre)}{grupo}{cred}")
    if e.proyecto:
        lineas.append(f"Proyecto: «{escape(e.proyecto.titulo or '¿título?')}»")
        lineas.append(f"  · Director(a): {escape(e.proyecto.director or '¿?')}")
        if e.proyecto.codirector:
            lineas.append(f"  · Codirector(a): {escape(e.proyecto.codirector)}")
    if e.jurados:
        lineas.append(f"Jurados que se recomiendan ({len(e.jurados)}):")
        for j in e.jurados:
            detalle = " · ".join(x for x in (j.vinculacion, j.correo) if x)
            lineas.append(
                f"  · {escape(j.nombre)}" + (f" ({escape(detalle)})" if detalle else "")
            )
    for cuadro in e.equivalencias:
        lineas.append(f"Cuadro de {cuadro.figura}: {len(cuadro.filas)} asignaturas")
        for f in cuadro.filas:
            origen = " ".join(x for x in (f.origen.codigo, f.origen.nombre) if x)
            destino = " ".join(x for x in (f.destino.codigo, f.destino.nombre) if x)
            lineas.append(f"  · {escape(origen or '¿?')} → {escape(destino or '¿?')}")

    datos: list[str] = []
    if analisis.creditos_inscritos is not None:
        datos.append(f"inscritos {analisis.creditos_inscritos}")
    if analisis.creditos_tras_solicitud is not None:
        datos.append(f"tras la solicitud {analisis.creditos_tras_solicitud}")
    if analisis.disciplinares_aprobados is not None:
        exig = analisis.disciplinares_exigidos_tdg
        datos.append(
            f"disciplinares aprobados {analisis.disciplinares_aprobados}"
            + (f"/{exig}" if exig else "")
        )
    if analisis.papa is not None:
        datos.append(f"P.A.P.A. {_num(analisis.papa)}")
    if analisis.porcentaje_avance is not None:
        datos.append(f"avance {_num(analisis.porcentaje_avance)} %")
    if datos:
        lineas.append("SIA: " + " · ".join(datos))
    if e.anexos:
        lineas.append("Anexos: " + escape("; ".join(e.anexos)))
    if e.justificacion_breve:
        lineas.append(f"<i>{escape(e.justificacion_breve)}</i>")

    normas = normas_para(e.tipos, caso.programa)
    if normas:
        lineas.append(
            "Normas base: "
            + "; ".join(
                escape(f"{n.norma}, {n.articulo}") + ("" if n.verificada else " *")
                for n in normas
            )
        )
        if any(not n.verificada for n in normas):
            lineas.append("<i>* texto tomado de un acta; falta el PDF de la norma.</i>")

    if analisis.alertas:
        lineas.append("")
        for alerta in analisis.alertas:
            lineas.append(f"{_ICONO[alerta.nivel]} {escape(alerta.mensaje)}")

    lineas.append("")
    lineas.append(f"Recomendación: <b>{_SENTIDO[caso.sentido]}</b>")
    if caso.nota_comite:
        nota = caso.nota_comite
        if len(nota) > 400:
            nota = nota[:400] + " (…)"
        lineas.append(f"Nota del comité: {escape(nota)}")
    if caso.conceptos:
        lineas.append(
            "Conceptos (van al acta): "
            + ", ".join(escape(c.miembro) for c in caso.conceptos)
        )
    lineas.append(
        f"<i>Caso #{caso.id}: para corregir un dato, responde a este mensaje con el cambio.</i>"
    )
    return "\n".join(lineas)


def botones_ficha(caso_id: int) -> list[list[dict[str, str]]]:
    return [
        [
            {"text": "✅ Recomendar aprobar", "callback_data": f"s:{caso_id}:aprobar"},
            {
                "text": "❌ Recomendar no aprobar",
                "callback_data": f"s:{caso_id}:no_aprobar",
            },
            {"text": "⏳ Pendiente", "callback_data": f"s:{caso_id}:pendiente"},
        ],
        [
            {"text": "🗣 Concepto", "callback_data": f"c:{caso_id}"},
            {"text": "📝 Nota", "callback_data": f"n:{caso_id}"},
            {"text": "🗑 Descartar", "callback_data": f"d:{caso_id}"},
        ],
    ]
