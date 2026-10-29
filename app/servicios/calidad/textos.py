"""Mensajes del servicio de calidad (HTML de Telegram)."""

from __future__ import annotations

from datetime import date
from html import escape

from app.servicios.calidad.directorio import Tramite
from app.servicios.calidad.plan import Estado, Resumen, Tarea

ALCANCE = (
    "Te ayudo a seguir el plan de mejoramiento y a saber a quién acudir. "
    "No reemplazo el seguimiento de la DAMA ni las decisiones de los comités."
)

AYUDA = (
    "<b>Comandos</b>\n"
    "/importar_plan — cargar o actualizar el plan desde un .xlsx\n"
    "/plan &lt;programa&gt; — tareas por estado, con su responsable\n"
    "/evidencia &lt;código&gt; — registrar un archivo o enlace y marcar la tarea cumplida\n"
    "/alerta_vista_previa — la alerta quincenal que recibiría cada programa\n"
    "/reporte &lt;programa&gt; — Excel con el estado y las fuentes de cada cifra\n"
    "/a_quien &lt;tema&gt; — dependencia y cargo a quien acudir"
)

_ROTULO = {
    Estado.VENCIDA: "🔴 Vencidas",
    Estado.PROXIMA: "🟡 Próximas a vencer (4 semanas)",
    Estado.PENDIENTE: "⚪ Pendientes",
    Estado.CUMPLIDA: "🟢 Cumplidas",
}
PLURAL = {
    Estado.VENCIDA: "vencidas",
    Estado.PROXIMA: "próximas a vencer",
    Estado.PENDIENTE: "pendientes",
    Estado.CUMPLIDA: "cumplidas",
}
ORDEN = (Estado.VENCIDA, Estado.PROXIMA, Estado.PENDIENTE, Estado.CUMPLIDA)


def responsable(t: Tarea) -> str:
    return f"{escape(t.cargo)} — {escape(t.dependencia)}"


def linea_tarea(t: Tarea, *, con_evidencia: bool = False) -> str:
    texto = (
        f"• <b>{escape(t.codigo)}</b> {escape(t.tarea)} "
        f"(límite {t.fecha_limite.isoformat()})\n   Responsable: {responsable(t)}"
    )
    if con_evidencia and t.evidencias:
        e = t.evidencias[-1]
        texto += (
            f"\n   Evidencia: {escape(e.valor)} "
            f"(registró {escape(e.registrado_nombre or str(e.registrado_por))}, "
            f"{e.creado[:10]})"
        )
    return texto


def agrupar(tareas: list[Tarea], hoy: date) -> dict[Estado, list[Tarea]]:
    grupos: dict[Estado, list[Tarea]] = {e: [] for e in ORDEN}
    for t in tareas:
        grupos[t.estado(hoy)].append(t)
    return grupos


def texto_plan(programa: str, tareas: list[Tarea], hoy: date) -> str:
    grupos = agrupar(tareas, hoy)
    cuentas = " · ".join(f"{len(grupos[e])} {PLURAL[e]}" for e in ORDEN)
    partes = [f"<b>Plan de mejoramiento — {escape(programa)}</b>", cuentas]
    for e in ORDEN:
        if grupos[e]:
            partes.append(f"\n<b>{_ROTULO[e]} ({len(grupos[e])})</b>")
            partes.extend(
                linea_tarea(t, con_evidencia=e is Estado.CUMPLIDA) for t in grupos[e]
            )
    return "\n".join(partes)


def texto_alerta(programa: str, tareas: list[Tarea], hoy: date) -> str:
    grupos = agrupar(tareas, hoy)
    partes = [f"<b>Alerta quincenal — {escape(programa)}</b> ({hoy.isoformat()})"]
    if not grupos[Estado.VENCIDA] and not grupos[Estado.PROXIMA]:
        partes.append("Sin tareas vencidas ni próximas a vencer sin evidencia.")
    for e in (Estado.VENCIDA, Estado.PROXIMA):
        if grupos[e]:
            partes.append(f"\n<b>{_ROTULO[e]} sin evidencia ({len(grupos[e])})</b>")
            partes.extend(linea_tarea(t) for t in grupos[e])
    partes.append("\nRegistra la evidencia con /evidencia &lt;código&gt;.")
    partes.append(f"<i>{ALCANCE}</i>")
    return "\n".join(partes)


def texto_resumen_importacion(resumen: Resumen, archivo: str) -> str:
    partes = [
        f"<b>Resumen de {escape(archivo)}</b>",
        f"• Nuevas: {len(resumen.nuevas)}",
        f"• Actualizadas: {len(resumen.actualizadas)}",
        f"• Sin cambios: {resumen.sin_cambios}",
    ]
    for fila, cambios in resumen.actualizadas[:10]:
        campos = ", ".join(cambios)
        partes.append(f"   {escape(fila.codigo)}: cambia {escape(campos)}")
    if resumen.ausentes:
        codigos = ", ".join(escape(c) for _, c in resumen.ausentes[:10])
        partes.append(
            f"• En el plan guardado pero no en este archivo: {len(resumen.ausentes)} "
            f"({codigos}). No se borran."
        )
    partes.append("\nNada se guarda hasta que confirmes.")
    return "\n".join(partes)


def texto_directorio(
    consulta: str, encontrados: list[Tramite], temas: list[str]
) -> str:
    if not encontrados:
        lista = "\n".join(f"• {escape(t)}" for t in temas)
        return (
            f"No encontré «{escape(consulta)}» en el directorio, así que no te "
            "indico un responsable. Temas disponibles:\n" + lista
        )
    partes = []
    for t in encontrados:
        partes.append(
            f"<b>{escape(t.tema)}</b>\n"
            f"→ Dependencia: {escape(t.dependencia)}\n"
            f"→ Cargo: {escape(t.cargo)}\n"
            f"→ Correo: {escape(t.correo)}\n"
            f"→ Vigencia: {escape(t.vigencia)}"
        )
    partes.append(
        "<i>Datos de ejemplo hasta que la Vicedecanatura complete el directorio.</i>"
    )
    return "\n\n".join(partes)
