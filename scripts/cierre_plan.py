"""Revisa los soportes de un plan de mejoramiento y prepara el borrador de cierre.

Uso:
    uv run python scripts/cierre_plan.py --carpeta ~/fcen_insumos/calidad/MCMA_proceso1 \\
        --plan "…/Plan de mejoramiento MCMA 2016.xlsx" \\
        --salidas ~/fcen_insumos/calidad/salidas/MCMA_cierre \\
        --programa "Maestría en Ciencias – Matemática Aplicada" [--estimar]

Con --estimar solo calcula el costo, sin llamar al modelo. La API key se lee de
ANTHROPIC_API_KEY o del archivo indicado con --env (nunca se imprime). Las
salidas y la caché quedan en --salidas, que debe estar FUERA del repositorio.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios.calidad.soportes.cliente import ClienteAnthropic  # noqa: E402
from app.servicios.calidad.soportes.describir import Cache  # noqa: E402
from app.servicios.calidad.soportes.revisor import (  # noqa: E402
    estimar,
    preparar,
    revisar,
)


def leer_env(ruta: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not ruta.exists():
        return valores
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--carpeta", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--salidas", type=Path, required=True)
    ap.add_argument("--programa", default="Programa")
    ap.add_argument("--env", type=Path, default=RAIZ / ".env")
    ap.add_argument("--concurrencia", type=int, default=4)
    ap.add_argument("--estimar", action="store_true", help="solo estima el costo")
    args = ap.parse_args()

    carpeta = args.carpeta.expanduser().resolve()
    salidas = args.salidas.expanduser().resolve()
    if salidas.is_relative_to(RAIZ):
        print("Las salidas deben quedar fuera del repositorio.", file=sys.stderr)
        return 2

    archivos, acciones = preparar(carpeta, args.plan.expanduser())
    est = estimar(archivos, acciones, Cache(salidas / ".cache"))
    print(
        f"Inventario: {len(archivos)} archivos; {len(acciones)} acciones. "
        f"Al modelo: {est.archivos_al_modelo} (en caché: {est.en_cache})."
    )
    print(
        f"Estimación: descripción {est.tokens_descripcion[0]:,} tokens de entrada y "
        f"{est.tokens_descripcion[1]:,} de salida; cruce {est.tokens_cruce[0]:,} y "
        f"{est.tokens_cruce[1]:,}. Costo estimado: {est.costo:.2f} USD."
    )
    if args.estimar:
        return 0

    env = leer_env(args.env.expanduser())
    api_key = os.environ.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_API_KEY", "")
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID") or env.get(
        "ANTHROPIC_WORKSPACE_ID", ""
    )
    if not api_key:
        print("Falta ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2
    cliente = ClienteAnthropic(api_key, workspace)
    informe = asyncio.run(
        revisar(
            carpeta,
            args.plan.expanduser(),
            salidas,
            cliente,
            args.programa,
            args.concurrencia,
            avisar=print,
        )  # fmt: skip
    )
    print()
    print(
        f"Tiempo: {informe.segundos / 60:.1f} min. Costo real: {informe.uso.costo():.2f} USD."
    )
    for modelo, (ent, sal, n) in informe.uso.por_modelo.items():
        print(f"  {modelo}: {n} llamadas, {ent:,} tokens de entrada, {sal:,} de salida")
    print("Veredictos propuestos:", dict(informe.veredictos()))
    fallos = [d for d in informe.descripciones.values() if d.datos is None]
    print(f"Archivos sin descripción: {len(fallos)}")
    for error, cuantos in Counter(d.error for d in fallos).most_common():
        ids = [d.archivo_id for d in fallos if d.error == error]
        print(
            f"  {cuantos} × {error} ({', '.join(ids[:8])}{'…' if len(ids) > 8 else ''})"
        )
    if fallos:
        print("Volver a correr retoma desde la caché: solo se pagan los que faltan.")
    alertas = sum(len(c.alertas) for c in informe.cruces)
    print(f"Alertas del verificador: {alertas}")
    sugeridas = sum(1 for c in informe.cruces if c.sugerencia)
    print(f"Sugerencias para acciones sin evidencia: {sugeridas}")
    if informe.error_sugerencias:
        print(f"Sugerencias: {informe.error_sugerencias}")
    for nombre, ruta in informe.salidas.items():
        print(f"{nombre}: {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
