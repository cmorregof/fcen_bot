"""Carga (o recarga) los datos ficticios del entorno de práctica.

Se corre una vez por servicio, con las variables de ese servicio, y solo sirve
con MEMORIA_PRACTICA=true: así nunca toca la base de producción.

    MEMORIA_PRACTICA=true BOT_SERVICIO=actas uv run python scripts/sembrar_practica.py
    ... --asistentes asistentes.csv     # además autoriza a los asistentes

Es idempotente: vacía las tablas del servicio (menos los correos autorizados) y
las vuelve a llenar, así que correrlo dos veces deja lo mismo. No llama al
modelo: los casos ya traen su extracción.

El CSV de asistentes (correo,nombre,rol,direccion) tiene datos de personas
reales: guárdelo fuera del repositorio.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app import practica
from app.core.config import settings


async def main(asistentes: Path | None) -> None:
    resultado = await practica.reiniciar()
    print(
        f"Práctica «{settings.bot_servicio}» reiniciada en {settings.db_path} "
        f"({resultado['registros']} registros ficticios)."
    )
    if asistentes is not None:
        n = await practica.autorizar_asistentes(asistentes)
        print(f"{n} asistentes autorizados en {settings.bot_servicio}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--asistentes", type=Path, help="CSV correo,nombre,rol,direccion"
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(args.asistentes))
    except practica.NoEsPractica as exc:
        sys.exit(str(exc))
