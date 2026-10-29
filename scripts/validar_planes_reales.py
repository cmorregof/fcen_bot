"""Valida el lector de la plantilla contra los planes reales, FUERA del repo.

Imprime SOLO conteos y estados por archivo: nunca nombres, textos ni enlaces.
Las alertas de lectura citan hoja, fila y columna, no el contenido.

    uv run python scripts/validar_planes_reales.py [carpeta] [--hoy AAAA-MM-DD]

Por defecto lee ~/fcen_insumos/calidad/planes_reales/. Los planes reales nunca
entran al repositorio.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

from app.servicios.calidad.plan import Estado, calcular_estado, proximo_corte
from app.servicios.calidad.plantilla import leer_plantilla

CARPETA = Path.home() / "fcen_insumos" / "calidad" / "planes_reales"


def validar(ruta: Path, hoy: date) -> list[str]:
    lectura = leer_plantilla(ruta.read_bytes())
    if lectura.plan is None:
        return [
            f"{ruta.name}: NO SE LEYÓ ({len(lectura.errores)} errores)",
            *(f"  - {e}" for e in lectura.errores),
        ]
    plan = lectura.plan
    acciones = plan.acciones
    estados = Counter(calcular_estado(a, hoy) for a in acciones)
    promedio = plan.avance_promedio()
    corte = proximo_corte(plan, hoy)
    tareas = plan.tareas
    lineas = [
        f"{ruta.name}",
        f"  objetivos {len(plan.objetivos)} · acciones {len(acciones)} · tareas {len(tareas)} "
        f"· cronogramas {plan.cronogramas} · oportunidades {len(plan.oportunidades)} "
        f"· evaluaciones {len(plan.evaluaciones)}",
        f"  avance promedio {promedio:.1f} %"
        if promedio is not None
        else "  avance promedio s/d",
        "  " + " · ".join(f"{e.value} {estados.get(e, 0)}" for e in Estado),
        f"  reprogramadas {sum(a.reprogramada for a in acciones)} · tareas reprogramadas "
        f"{sum(t.reprogramada for t in tareas)} · tareas OK {sum(bool(t.ok) for t in tareas)}",
        f"  acciones sin %: {sum(a.avance is None for a in acciones)} · sin fecha fin: "
        f"{sum(a.fecha_fin is None for a in acciones)} · sin tareas: "
        f"{sum(not a.tareas for a in acciones)}",
        f"  cortes por acción: {sorted(Counter(len(a.cortes) for a in acciones).items())} "
        f"· próximo corte {corte[0].isoformat() + (' (estimado)' if corte[1] else '') if corte else 's/d'}",
        f"  alertas de lectura: {len(plan.alertas)}",
    ]
    lineas += [f"    - {a}" for a in plan.alertas]
    return lineas


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta", nargs="?", type=Path, default=CARPETA)
    ap.add_argument("--hoy", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    archivos = sorted(args.carpeta.glob("*.xlsx"))
    if not archivos:
        raise SystemExit(f"No hay .xlsx en {args.carpeta}")
    print(f"Corte de estados: {args.hoy.isoformat()}\n")
    for ruta in archivos:
        print("\n".join(validar(ruta, args.hoy)) + "\n")


if __name__ == "__main__":
    main()
