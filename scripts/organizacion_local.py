"""Revisa la organización de las evidencias de uno o varios zips, sin modelo.

Hace lo mismo que la carga en la web (descomprimir con los mismos cuidados,
inventariar y revisar carpetas y nombres según el instructivo), pero en el
equipo: no gasta créditos y no sube nada. Por cada programa deja
`organizacion.xlsx` e `indice_electronico.xlsx`.

Las partes de una descarga dividida de Drive («…-1-001.zip», «…-2-001.zip»)
se juntan solas en un mismo programa.

Uso:
    uv run python scripts/organizacion_local.py --salida "$FUERA_DEL_REPO" \\
        Ing_Fisica.zip "Soportes de acciones-20261110T1-1-001.zip" …

La salida debe quedar FUERA del repositorio: trae nombres de documentos reales.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servicios.calidad.soportes.carga import (  # noqa: E402
    ZipNoValido,
    extraer,
    grupo_de_parte,
)
from app.servicios.calidad.soportes.inventario import (  # noqa: E402
    carpetas,
    inventariar,
)
from app.servicios.calidad.soportes.organizacion import revisar  # noqa: E402
from app.servicios.calidad.soportes.salidas import (  # noqa: E402
    indice_electronico_xlsx,
    organizacion_xlsx,
)

MAX_BYTES = 4_000_000_000
MAX_ARCHIVOS = 20_000


def agrupar(zips: list[Path]) -> dict[str, list[Path]]:
    grupos: dict[str, list[Path]] = {}
    for z in sorted(zips):
        grupos.setdefault(grupo_de_parte(z.name), []).append(z)
    return grupos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zips", nargs="+", type=Path)
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()
    salida = args.salida.resolve()
    if salida.is_relative_to(RAIZ):
        print("La salida debe quedar fuera del repositorio.", file=sys.stderr)
        return 2
    for programa, partes in agrupar(args.zips).items():
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "soportes"
            try:
                extraer(partes, destino, max_bytes=MAX_BYTES, max_archivos=MAX_ARCHIVOS)
            except ZipNoValido as exc:
                print(f"{programa}: {exc}", file=sys.stderr)
                continue
            archivos = inventariar(destino)
            org = revisar(archivos, carpetas(destino))
            carpeta = salida / programa
            shutil.rmtree(carpeta, ignore_errors=True)
            organizacion_xlsx(carpeta / "organizacion.xlsx", org)
            indice_electronico_xlsx(carpeta / "indice_electronico.xlsx", org)
        print(
            f"{programa}: {len(partes)} zip, {len(archivos)} archivos, "
            f"{len(org.acciones)} acciones, "
            f"{len(org.resumen()['acciones_con_observaciones'])} con observaciones "  # type: ignore[arg-type]
            f"-> {carpeta}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
