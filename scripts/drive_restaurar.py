"""Restaura la base de este servicio desde una copia nocturna en Drive.

Se corre dentro del contenedor del servicio (`railway ssh`), que ya tiene las
variables DRIVE_* y el volumen. Ver docs/respaldo-drive.md.

    python scripts/drive_restaurar.py                 # lista las copias
    python scripts/drive_restaurar.py --archivo memoria_actas_20261030.db.gz
        # descarga, descomprime y verifica junto a la base; no la toca
    python scripts/drive_restaurar.py --archivo ... --aplicar
        # además aparta la base actual (fcen.db.antes-<fecha>) y pone la copia

Después de --aplicar hay que reiniciar el servicio en Railway.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.drive import cliente as drive  # noqa: E402
from app.services.drive import respaldo  # noqa: E402


async def _main(archivo: str, aplicar: bool) -> None:
    cliente = drive.obtener()
    if cliente is None:
        sys.exit("Faltan las variables DRIVE_* en este servicio.")
    carpeta = await drive.carpeta(
        cliente, settings.drive_carpeta_id, [respaldo.CARPETA, settings.bot_servicio]
    )
    copias = sorted(
        (a for a in await cliente.listar(carpeta) if not a.carpeta),
        key=lambda a: a.nombre,
        reverse=True,
    )
    if not archivo:
        print(f"Copias de {settings.bot_servicio} (la más reciente primero):")
        for a in copias:
            print(f"  {a.nombre}")
        return
    elegida = next((a for a in copias if a.nombre == archivo), None)
    if elegida is None:
        sys.exit(f"No encontré {archivo} en Respaldos/{settings.bot_servicio}.")
    if archivo.endswith(".dump"):
        # Copia de Postgres: se descarga y se indica cómo restaurarla; este
        # script no toca la base en Postgres.
        destino = settings.data_dir / archivo
        destino.write_bytes(await cliente.descargar(elegida.id))
        print(f"Copia de Postgres descargada en {destino}.")
        print(
            "Para restaurarla, vea «Postgres» en docs/respaldo-drive.md (pg_restore)."
        )
        return
    if not archivo.endswith(".db.gz"):
        sys.exit("Este script restaura copias de SQLite (.db.gz) o descarga .dump.")

    base = settings.db_path
    nueva = base.with_name(f"{base.name}.restaurando")
    nueva.write_bytes(gzip.decompress(await cliente.descargar(elegida.id)))
    with sqlite3.connect(nueva) as con:
        resultado = con.execute("PRAGMA integrity_check").fetchone()[0]
    if resultado != "ok":
        sys.exit(f"La copia no pasó la verificación: {resultado}")
    print(f"Copia verificada en {nueva}.")
    if not aplicar:
        print("No toqué la base. Para ponerla en uso, repita con --aplicar.")
        return
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    for sufijo in ("", "-wal", "-shm"):
        actual = base.with_name(base.name + sufijo)
        if actual.exists():
            actual.rename(base.with_name(f"{base.name}{sufijo}.antes-{sello}"))
    nueva.rename(base)
    print(
        f"Base restaurada desde {archivo}. La anterior quedó como {base.name}.antes-{sello}."
    )
    print("Reinicie el servicio en Railway para que la use.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--archivo", default="")
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    asyncio.run(_main(args.archivo, args.aplicar))


if __name__ == "__main__":
    main()
