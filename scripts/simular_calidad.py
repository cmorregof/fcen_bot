"""Simula el servicio de calidad con los planes FICTICIOS de docs/calidad y deja
lo que vería cada programa en docs/calidad/simulacion-AAAA-MM-DD.md.

Usa una base temporal: no toca ninguna base real ni envía nada a Telegram.

    uv run python scripts/simular_calidad.py [--hoy AAAA-MM-DD]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import re
import tempfile
from datetime import date, datetime
from html import unescape
from pathlib import Path

import aiosqlite
from openpyxl import load_workbook

from app.servicios.calidad import alertas, plan, plantilla, reporte, textos
from app.servicios.calidad.db import init_calidad
from app.servicios.calidad.reloj import ahora

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs" / "calidad"
PLANES = (
    DOCS / "plantilla_plan_mejoramiento.xlsx",
    DOCS / "plantilla_plan_mejoramiento_beta.xlsx",
)
SOPORTES = (
    (
        "Ejemplo Alfa (ficticio)",
        "1.1.2",
        "enlace",
        "https://ejemplo.invalid/acta-jornada",
    ),
    ("Ejemplo Beta (ficticio)", "1.2", "archivo", "propuesta-asignatura.pdf"),
)


def a_markdown(html: str) -> str:
    texto = re.sub(r"</?b>", "**", html)
    texto = re.sub(r"</?i>", "_", texto)
    return unescape(texto)


async def simular(hoy: date) -> str:
    partes = [
        f"# Simulación del servicio de calidad — {hoy.isoformat()}",
        "",
        "Datos 100 % ficticios: los dos planes de `docs/calidad/` usan la plantilla "
        "institucional de cinco hojas. Base temporal; no se envió nada a Telegram.",
        "",
        f"> {textos.ALCANCE}",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        db = await aiosqlite.connect(Path(tmp) / "simulacion.db")
        db.row_factory = aiosqlite.Row
        await init_calidad(db)
        marca = datetime.combine(hoy, ahora().timetz()).isoformat()
        partes += ["", "## Importación (`/importar_plan`)", ""]
        for ruta in PLANES:
            lectura = plantilla.leer_plantilla(ruta.read_bytes())
            if lectura.plan is None:
                raise SystemExit(
                    f"{ruta.name} no es válido: " + "; ".join(lectura.errores)
                )
            resumen = await plan.resumir(db, lectura.plan)
            partes += [
                "### Resumen antes de guardar",
                "",
                a_markdown(textos.texto_resumen_importacion(resumen, ruta.name)),
                "",
            ]
            await plan.aplicar_importacion(
                db, lectura.plan, archivo=ruta.name, usuario_id=1, creado=marca
            )
            otra = await plan.resumir(db, lectura.plan)
            partes += [
                f"Reimportar el mismo archivo: {len(otra.nuevas)} nuevas, "
                f"{len(otra.actualizadas)} actualizadas, {otra.sin_cambios} sin cambios, "
                f"{otra.cortes_nuevos} cortes nuevos (no duplica).",
                "",
            ]
        for programa, codigo, tipo, valor in SOPORTES:
            guardado = await plan.cargar_plan(db, programa)
            assert guardado is not None
            await plan.registrar_soporte(
                db, guardado.ids[codigo], tipo=tipo, valor=valor, referencia=None,
                usuario_id=1, usuario_nombre="Persona Ficticia", creado=marca,
            )  # fmt: skip
        partes.append(
            "**Soportes registrados con `/evidencia`:** "
            + ", ".join(f"{p} {c}" for p, c, _, _ in SOPORTES)
            + " (quedan por revisar; no cambian el % de avance)."
        )
        mapa = await alertas.construir_alertas(db, hoy)
        for guardado in await plan.listar_planes(db):
            partes += [
                "",
                f"## {guardado.programa}",
                "",
                "### Respuesta a `/plan`",
                "",
                a_markdown(textos.texto_plan(guardado, hoy)),
                "",
                "### Alerta quincenal (`/alerta_vista_previa`)",
                "",
                a_markdown(mapa[guardado.programa]),
                "",
                "### Reporte `/reporte` (Excel)",
                "",
            ]
            libro = load_workbook(io.BytesIO(reporte.generar_reporte(guardado, hoy)))
            partes += [f"Pestañas: {', '.join(libro.sheetnames)}.", ""]
            partes += ["| Cifra | Valor | Filas en «fuentes» |", "|---|---|---|"]
            fuentes = list(libro["fuentes"].iter_rows(min_row=2, values_only=True))
            for cifra, valor, *_ in libro["estado"].iter_rows(
                min_row=2, values_only=True
            ):
                n = sum(1 for f in fuentes if f[0] == cifra)
                partes.append(f"| {cifra} | {valor} | {n if n else '—'} |")
        await db.close()
    return "\n".join(partes) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoy", type=date.fromisoformat, default=ahora().date())
    hoy: date = ap.parse_args().hoy
    destino = DOCS / f"simulacion-{hoy.isoformat()}.md"
    destino.write_text(asyncio.run(simular(hoy)), encoding="utf-8")
    print(f"Simulación guardada en {destino}")


if __name__ == "__main__":
    main()
