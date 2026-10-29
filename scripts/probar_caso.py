"""Prueba la lectura de un caso real sin Telegram (necesita ANTHROPIC_API_KEY).

Uso:
    uv run python scripts/probar_caso.py casos_reales/caso_01 [programa]

La carpeta tiene `correo.txt` (el texto pegado del correo) y los pantallazos
(.png/.jpg). Imprime la ficha y escribe el borrador en la misma carpeta.
`casos_reales/` está en .gitignore: los casos reales nunca van al repositorio.
"""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import date
from pathlib import Path

from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.db.session import connect
from app.schemas.caso import Caso, EstadoCaso
from app.services.documento import CasoDocumento, DatosOficio, construir_oficio
from app.services.extraccion import cita_del_caso, extraer_caso
from app.services.ficha import ficha
from app.services.reglas import analizar


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    carpeta = Path(sys.argv[1])
    direccion_por_defecto = sys.argv[2] if len(sys.argv) > 2 else None
    texto = (
        (carpeta / "correo.txt").read_text(encoding="utf-8")
        if (carpeta / "correo.txt").exists()
        else ""
    )
    imagenes = sorted(
        str(p)
        for p in carpeta.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg"} and not p.name.startswith("_")
    )
    settings.db_path = carpeta / "_prueba.db"
    db = await connect()
    direccion = (
        PROGRAMAS[direccion_por_defecto].direccion
        if direccion_por_defecto
        else "ciencias_naturales"
    )
    caso = Caso(
        id=0,
        chat_id=0,
        direccion=direccion,
        estado=EstadoCaso.ABIERTO,
        texto=texto,
        imagenes=imagenes,
    )
    salida = await extraer_caso(db, caso)
    await db.close()
    if salida.extraccion is None:
        raise SystemExit(f"Error: {salida.error}")
    programa = salida.programa or (
        PROGRAMAS[direccion_por_defecto] if direccion_por_defecto else None
    )
    caso = caso.model_copy(
        update={
            "extraccion": salida.extraccion,
            "programa": programa.clave if programa else None,
            "estado": EstadoCaso.LISTO,
        }
    )
    analisis = analizar(
        salida.extraccion,
        programa,
        periodo_inicio=settings.periodo_inicio,
        hay_imagenes=bool(imagenes),
        texto_original=texto,
        jurados_minimo=settings.jurados_minimo,
    )
    print(re.sub(r"<[^>]+>", "", ficha(caso, analisis)))
    (carpeta / "_extraccion.json").write_text(
        salida.extraccion.model_dump_json(indent=2), encoding="utf-8"
    )
    if programa:
        cita, verificada = cita_del_caso(texto, salida.extraccion)
        item = CasoDocumento(
            caso,
            salida.extraccion,
            analisis,
            cita,
            cita_verificada=verificada,
        )
        docx = construir_oficio(
            DatosOficio(programa=programa, fecha=date.today(), casos=[item]),
            settings.periodo_actual,
        )
        (carpeta / "_borrador.docx").write_bytes(docx)
        print(f"\nBorrador: {carpeta / '_borrador.docx'}")


if __name__ == "__main__":
    asyncio.run(main())
