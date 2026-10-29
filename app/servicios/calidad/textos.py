"""Mensajes del servicio de calidad (HTML de Telegram)."""

from __future__ import annotations

from datetime import date
from html import escape

from app.servicios.calidad.directorio import Tramite
from app.servicios.calidad.plan import (
    Estado,
    PlanGuardado,
    ResumenImportacion,
    calcular_estado,
    proxima_a_vencer,
    proximo_corte,
)
from app.servicios.calidad.plantilla import Accion

ALCANCE = (
    "Te ayudo a seguir el plan de mejoramiento y a saber a quién acudir. "
    "No reemplazo el seguimiento de la DAMA ni las decisiones de los comités."
)

AYUDA = (
    "<b>Comandos</b>\n"
    "/importar_plan — cargar o actualizar un plan con la plantilla institucional (.xlsx)\n"
    "/plan &lt;programa&gt; — tablero: avance, vencidas, reprogramadas, responsables y próximo corte\n"
    "/evidencia &lt;programa&gt; &lt;código&gt; [enlace] — registrar un soporte de una acción (queda por revisar)\n"
    "/alerta_vista_previa — la alerta quincenal que recibiría cada programa\n"
    "/reporte &lt;programa&gt; — Excel con el estado y las fuentes de cada cifra\n"
    "/a_quien &lt;tema&gt; — dependencia y cargo a quien acudir"
)

ORDEN = (
    Estado.VENCIDA,
    Estado.NO_FUNCIONO,
    Estado.EN_CURSO,
    Estado.POR_INICIAR,
    Estado.CUMPLIDA,
)
ICONO = {
    Estado.VENCIDA: "🔴",
    Estado.NO_FUNCIONO: "⛔",
    Estado.EN_CURSO: "🔵",
    Estado.POR_INICIAR: "⚪",
    Estado.CUMPLIDA: "🟢",
}
PLURAL = {
    Estado.VENCIDA: "vencidas",
    Estado.NO_FUNCIONO: "marcadas «NO FUNCIONÓ»",
    Estado.EN_CURSO: "en curso",
    Estado.POR_INICIAR: "por iniciar",
    Estado.CUMPLIDA: "cumplidas",
}
_CAMPOS = {
    "descripcion": "descripción",
    "indicador": "indicador",
    "responsables": "responsables",
    "fecha_inicio": "inicio",
    "fecha_fin": "fin",
    "avance": "% de avance",
    "evidencias": "evidencias",
    "marcas": "estado escrito",
    "tareas": "tareas del cronograma",
}


def corto(texto: str, n: int = 70) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def pct(valor: float | None) -> str:
    return "s/d" if valor is None else f"{valor:.0f} %"


def agrupar(acciones: list[Accion], hoy: date) -> dict[Estado, list[Accion]]:
    grupos: dict[Estado, list[Accion]] = {e: [] for e in ORDEN}
    for a in acciones:
        grupos[calcular_estado(a, hoy)].append(a)
    return grupos


def motivo_reprogramacion(a: Accion) -> str:
    partes = []
    if a.fechas_fin_anteriores:
        previas = ", ".join(f.isoformat() for f in a.fechas_fin_anteriores)
        partes.append(f"fin anterior {previas}")
    escritos = sorted(
        {
            corto(t.estado_texto, 40)
            for t in a.tareas
            if t.reprogramada and t.estado_texto
        }
    )
    if escritos:
        partes.append("«" + "», «".join(escritos) + "»")
    n = sum(1 for t in a.tareas if t.reprogramada)
    if n:
        partes.append(f"{n} tarea{'s' if n > 1 else ''} del cronograma")
    otras = [m for m in a.marcas if "reprogram" in m.lower()]
    if otras and not partes:
        partes.append("marcada en el plan")
    return "; ".join(partes)


def linea_accion(a: Accion, hoy: date, *, con_responsables: bool = False) -> str:
    fin = a.fecha_fin.isoformat() if a.fecha_fin else "sin fecha"
    texto = (
        f"• <b>{escape(a.codigo)}</b> {pct(a.avance)} — {escape(corto(a.descripcion))} "
        f"(fin {fin})"
    )
    if con_responsables and a.responsables:
        texto += f"\n   Responsables: {escape(corto(a.responsables, 90))}"
    return texto


def _texto_corte(pg: PlanGuardado, hoy: date) -> str:
    corte = proximo_corte(pg.plan, hoy)
    if corte is None:
        return "Próximo corte: el plan no trae fechas de corte."
    fecha, estimado = corte
    nota = " (estimado: último corte del plan + 6 meses)" if estimado else ""
    return f"Próximo corte: {fecha.isoformat()}{nota}"


def texto_plan(pg: PlanGuardado, hoy: date) -> str:
    plan = pg.plan
    acciones = plan.acciones
    grupos = agrupar(acciones, hoy)
    reprogramadas = [a for a in acciones if a.reprogramada]
    anios = ", ".join(str(a) for a in plan.cronogramas) or "sin cronograma"
    partes = [
        f"<b>Plan de mejoramiento — {escape(plan.programa)}</b>",
        f"{len(acciones)} acciones · avance promedio {pct(plan.avance_promedio())} · "
        f"{len(plan.tareas)} tareas en el cronograma ({anios})",
        " · ".join(f"{ICONO[e]} {len(grupos[e])} {PLURAL[e]}" for e in ORDEN)
        + f" · 🔁 {len(reprogramadas)} reprogramadas",
        _texto_corte(pg, hoy),
        "\n<b>Acciones y % de avance</b>",
    ]
    partes += [
        f"{ICONO[calcular_estado(a, hoy)]} {escape(a.codigo)} {pct(a.avance)} — "
        f"{escape(corto(a.descripcion, 55))}"
        for a in acciones
    ]
    if grupos[Estado.VENCIDA]:
        partes.append(
            f"\n<b>🔴 Vencidas ({len(grupos[Estado.VENCIDA])})</b> — fin pasada y avance &lt; 100 %"
        )
        partes += [
            linea_accion(a, hoy, con_responsables=True) for a in grupos[Estado.VENCIDA]
        ]
    if reprogramadas:
        partes.append(f"\n<b>🔁 Reprogramadas ({len(reprogramadas)})</b>")
        partes += [
            f"• <b>{escape(a.codigo)}</b> {escape(motivo_reprogramacion(a))}"
            for a in reprogramadas
        ]
    if grupos[Estado.NO_FUNCIONO]:
        partes.append(
            f"\n<b>⛔ Marcadas «NO FUNCIONÓ» ({len(grupos[Estado.NO_FUNCIONO])})</b>"
        )
        partes += [
            linea_accion(a, hoy, con_responsables=True)
            for a in grupos[Estado.NO_FUNCIONO]
        ]
    for e in (Estado.EN_CURSO, Estado.POR_INICIAR, Estado.CUMPLIDA):
        if grupos[e]:
            codigos = ", ".join(escape(a.codigo) for a in grupos[e])
            partes.append(
                f"\n<b>{ICONO[e]} {PLURAL[e].capitalize()} ({len(grupos[e])})</b>: {codigos}"
            )
    partes.append("\n<b>Responsables (acciones abiertas)</b>")
    partes += texto_responsables(acciones, hoy)
    soportes = sum(len(v) for v in pg.soportes.values())
    if soportes:
        partes.append(f"\nSoportes registrados en el bot, por revisar: {soportes}.")
    return "\n".join(partes)


def texto_responsables(acciones: list[Accion], hoy: date) -> list[str]:
    por: dict[str, list[str]] = {}
    for a in acciones:
        if calcular_estado(a, hoy) in (Estado.CUMPLIDA, Estado.NO_FUNCIONO):
            continue
        quien = corto(a.responsables, 80) or "sin responsable en el plan"
        por.setdefault(quien, []).append(a.codigo)
    return [
        f"• {escape(quien)}: {', '.join(escape(c) for c in codigos)}"
        for quien, codigos in sorted(por.items(), key=lambda kv: -len(kv[1]))
    ] or ["• No hay acciones abiertas."]


def texto_alerta(pg: PlanGuardado, hoy: date) -> str:
    acciones = pg.plan.acciones
    grupos = agrupar(acciones, hoy)
    proximas = [a for a in acciones if proxima_a_vencer(a, hoy)]
    reprogramadas = [
        a
        for a in acciones
        if a.reprogramada and calcular_estado(a, hoy) is not Estado.CUMPLIDA
    ]
    partes = [
        f"<b>Alerta quincenal — {escape(pg.programa)}</b> ({hoy.isoformat()})",
        _texto_corte(pg, hoy),
    ]
    if not (
        grupos[Estado.VENCIDA]
        or proximas
        or reprogramadas
        or grupos[Estado.NO_FUNCIONO]
    ):
        partes.append(
            "Sin acciones vencidas, próximas a vencer, reprogramadas ni marcadas «NO FUNCIONÓ»."
        )
    secciones = (
        (f"🔴 Vencidas ({len(grupos[Estado.VENCIDA])})", grupos[Estado.VENCIDA]),
        (f"🟡 Vencen en las próximas 4 semanas ({len(proximas)})", proximas),
        (
            f"⛔ Marcadas «NO FUNCIONÓ» ({len(grupos[Estado.NO_FUNCIONO])})",
            grupos[Estado.NO_FUNCIONO],
        ),
    )
    for titulo, lista in secciones:
        if lista:
            partes.append(f"\n<b>{titulo}</b>")
            partes += [linea_accion(a, hoy, con_responsables=True) for a in lista]
    if reprogramadas:
        partes.append(f"\n<b>🔁 Reprogramadas sin cumplir ({len(reprogramadas)})</b>")
        partes += [
            f"• <b>{escape(a.codigo)}</b> {escape(motivo_reprogramacion(a))}"
            for a in reprogramadas
        ]
    partes.append(
        "\nRegistra un soporte con /evidencia &lt;programa&gt; &lt;código&gt; [enlace]."
    )
    partes.append(f"<i>{ALCANCE}</i>")
    return "\n".join(partes)


def texto_resumen_importacion(resumen: ResumenImportacion, archivo: str) -> str:
    anios = ", ".join(str(a) for a in resumen.cronogramas) or "ninguno"
    estado = "nuevo" if resumen.plan_nuevo else "ya estaba cargado: se actualiza"
    partes = [
        f"<b>Resumen de {escape(archivo)}</b>",
        f"Programa: <b>{escape(resumen.programa)}</b> ({estado})",
        f"• Objetivos: {resumen.objetivos} · acciones: {resumen.acciones} · "
        f"tareas del cronograma: {resumen.tareas} (años: {anios})",
        f"• Avance promedio de las acciones: {pct(resumen.avance)}",
        f"• Acciones nuevas: {len(resumen.nuevas)} · actualizadas: "
        f"{len(resumen.actualizadas)} · sin cambios: {resumen.sin_cambios}",
    ]
    for codigo, cambios in resumen.actualizadas[:10]:
        campos = ", ".join(_CAMPOS.get(c, c) for c in cambios)
        partes.append(f"   {escape(codigo)}: cambia {escape(campos)}")
    if len(resumen.actualizadas) > 10:
        partes.append(f"   … y {len(resumen.actualizadas) - 10} más")
    partes.append(
        f"• Cortes de avance: {resumen.cortes_nuevos} nuevos, "
        f"{resumen.cortes_cambiados} con cambios. Los anteriores se conservan."
    )
    if resumen.ausentes:
        partes.append(
            f"• Guardadas antes pero no en este archivo: {len(resumen.ausentes)} "
            f"({escape(', '.join(resumen.ausentes[:10]))}). No se borran."
        )
    if resumen.alertas:
        partes.append(f"\n<b>⚠️ Alertas de lectura ({len(resumen.alertas)})</b>")
        partes += [f"• {escape(a)}" for a in resumen.alertas[:15]]
        if len(resumen.alertas) > 15:
            partes.append(f"… y {len(resumen.alertas) - 15} más")
    else:
        partes.append("\nSin alertas de lectura.")
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
