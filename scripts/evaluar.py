"""Mide qué tan bien lee el bot los casos reales (necesita ANTHROPIC_API_KEY).

Uso:
    uv run python scripts/evaluar.py casos_reales/
    uv run python scripts/evaluar.py casos_reales/ --solo fis20 --paralelo 2

Cada subcarpeta de `casos_reales/` es un caso: `correo.txt` (lo que pegaría la
administrativa, puede estar vacío), los pantallazos (`pantallazo_*.png|jpg`) y
`esperado.json` con lo que dice el acta. El script pasa cada caso por la misma
extracción y las mismas reglas que usa el bot, compara campo por campo e
imprime una tabla. Deja `_extraccion.json` en cada carpeta y
`_resultados.json` en la carpeta raíz.

`casos_reales/` está en .gitignore: los casos reales nunca van al repositorio.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.db.session import connect
from app.schemas.caso import Caso, EstadoCaso, ExtraccionCaso
from app.services.extraccion import cuerpo_del_correo, extraer_caso
from app.services.reglas import Analisis, analizar, verificar_tabla_sia

IMAGENES = {".png", ".jpg", ".jpeg"}
TOLERANCIA_DECIMAL = 0.051

# Orden de las columnas de la tabla.
CAMPOS = (
    "nombre",
    "documento",
    "trato",
    "fecha",
    "programa",
    "tipos",
    "inscritos",
    "tras_solic",
    "disciplin",
    "papa",
    "avance",
    "codigos",
    "cuerpo",
    "tabla_sia",
    "privacidad",
)


def normalizar(texto: str | None) -> str:
    sin = "".join(
        c
        for c in unicodedata.normalize("NFKD", texto or "")
        if not unicodedata.combining(c)
    )
    return " ".join(sin.upper().split())


@dataclass
class ResultadoCaso:
    id: str
    campos: dict[str, bool | None] = field(default_factory=dict)
    detalles: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    def marcar(self, campo: str, ok: bool | None, detalle: str = "") -> None:
        self.campos[campo] = ok
        if ok is False and detalle:
            self.detalles[campo] = detalle


def comparar(
    caso_id: str,
    esperado: dict[str, Any],
    extraccion: ExtraccionCaso,
    analisis: Analisis,
    programa: str | None,
    texto: str,
) -> ResultadoCaso:
    """Compara lo extraído con lo que dice el acta. None = no se evalúa."""
    r = ResultadoCaso(caso_id)
    sia = extraccion.sia

    nombres = [esperado.get("nombre_estudiante")] + list(
        esperado.get("nombre_alternativas", [])
    )
    obtenido = normalizar(extraccion.nombre_estudiante)
    r.marcar(
        "nombre",
        obtenido in {normalizar(n) for n in nombres if n},
        extraccion.nombre_estudiante or "(vacío)",
    )

    doc_esp = esperado.get("documento")
    doc = (extraccion.documento or "").strip() or None
    r.marcar("documento", doc == doc_esp, f"{doc} ≠ {doc_esp}")

    trato = esperado.get("tratamiento")
    if trato:
        r.marcar("trato", extraccion.tratamiento == trato, extraccion.tratamiento)

    fecha_esp = esperado.get("fecha_solicitud")
    fecha = (extraccion.fecha_solicitud or "")[:10] or None
    if esperado.get("fecha_sin_anio") and fecha_esp:
        r.marcar(
            "fecha",
            fecha is not None and fecha[5:] == fecha_esp[5:],
            f"{fecha} ≠ {fecha_esp}",
        )
    else:
        # Si el acta no trae fecha, lo correcto es dejarla vacía.
        r.marcar("fecha", fecha == fecha_esp, f"{fecha} ≠ {fecha_esp}")

    if esperado.get("programa") and not esperado.get("sin_sia"):
        r.marcar(
            "programa",
            programa == esperado["programa"],
            f"{programa} ≠ {esperado['programa']}",
        )

    tipos = {t.value for t in extraccion.tipos}
    faltan = [t for t in esperado.get("tipos_incluye", []) if t not in tipos]
    r.marcar("tipos", not faltan, f"faltan {faltan}; dio {sorted(tipos)}")

    for campo, clave, valor in (
        ("inscritos", "creditos_inscritos", analisis.creditos_inscritos),
        ("tras_solic", "creditos_tras_solicitud", analisis.creditos_tras_solicitud),
        ("disciplin", "disciplinares_aprobados", analisis.disciplinares_aprobados),
    ):
        if esperado.get(clave) is not None:
            r.marcar(campo, valor == esperado[clave], f"{valor} ≠ {esperado[clave]}")

    for campo, clave, decimal in (
        ("papa", "papa", sia.papa if sia else None),
        ("avance", "porcentaje_avance", sia.porcentaje_avance if sia else None),
    ):
        if esperado.get(clave) is not None:
            r.marcar(
                campo,
                decimal is not None
                and abs(decimal - esperado[clave]) < TOLERANCIA_DECIMAL,
                f"{decimal} ≠ {esperado[clave]}",
            )

    codigos_esp = esperado.get("codigos_asignaturas") or []
    if codigos_esp:
        codigos = {(a.codigo or "").strip() for a in extraccion.asignaturas}
        faltan_c = [c for c in codigos_esp if c not in codigos]
        r.marcar("codigos", not faltan_c, f"faltan {faltan_c}; dio {sorted(codigos)}")

    cuerpo = cuerpo_del_correo(texto, extraccion)
    encabezado = any(
        linea.strip().lower() in {"para mí", "para mi"}
        or linea.strip().startswith("Para:")
        for linea in cuerpo.splitlines()
    )
    r.marcar(
        "cuerpo",
        bool(cuerpo.strip()) and not encabezado,
        "vacío" if not cuerpo.strip() else "trae encabezados de Gmail",
    )

    if sia and sia.resumen_creditos:
        problemas = verificar_tabla_sia(sia)
        r.marcar("tabla_sia", not problemas, "; ".join(problemas))
    elif not esperado.get("sin_sia"):
        r.marcar("tabla_sia", False, "no leyó el Resumen de créditos")

    prohibidas = esperado.get("no_debe_contener") or []
    if prohibidas:
        visible = normalizar(
            " ".join(
                [extraccion.justificacion_breve, extraccion.objeto_solicitud]
                + extraccion.anexos
                + extraccion.dudas
            )
        )
        halladas = [p for p in prohibidas if normalizar(p) in visible]
        r.marcar("privacidad", not halladas, f"aparece {halladas}")
    return r


def leer_caso(carpeta: Path) -> tuple[dict[str, Any], str, list[str]]:
    meta: dict[str, Any] = json.loads(
        (carpeta / "esperado.json").read_text(encoding="utf-8")
    )
    correo = carpeta / "correo.txt"
    texto = correo.read_text(encoding="utf-8") if correo.exists() else ""
    imagenes = sorted(
        str(p)
        for p in carpeta.iterdir()
        if p.suffix.lower() in IMAGENES and not p.name.startswith("_")
    )
    return meta, texto, imagenes


async def evaluar_caso(
    db: Any, numero: int, carpeta: Path, semaforo: asyncio.Semaphore
) -> ResultadoCaso:
    meta, texto, imagenes = leer_caso(carpeta)
    esperado: dict[str, Any] = meta["esperado"]
    direccion = meta.get("direccion") or PROGRAMAS[esperado["programa"]].direccion
    caso = Caso(
        id=numero,
        chat_id=0,
        direccion=direccion,
        estado=EstadoCaso.ABIERTO,
        texto=texto,
        imagenes=imagenes,
    )
    async with semaforo:
        salida = await extraer_caso(db, caso)
    async with db.execute(
        "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) "
        "FROM uso_modelo WHERE caso_id = ?",
        (numero,),
    ) as cur:
        fila = await cur.fetchone()
    tokens_in, tokens_out = (int(fila[0]), int(fila[1])) if fila else (0, 0)
    caso_id = str(meta.get("id") or carpeta.name)
    if salida.extraccion is None:
        r = ResultadoCaso(caso_id, error=salida.error or "sin resultado")
    else:
        (carpeta / "_extraccion.json").write_text(
            salida.extraccion.model_dump_json(indent=2), encoding="utf-8"
        )
        analisis = analizar(
            salida.extraccion,
            salida.programa,
            periodo_inicio=settings.periodo_inicio,
            hay_imagenes=bool(imagenes),
            texto_original=texto,
            jurados_minimo=settings.jurados_minimo,
        )
        r = comparar(
            caso_id,
            esperado,
            salida.extraccion,
            analisis,
            salida.programa.clave if salida.programa else None,
            texto,
        )
    r.input_tokens, r.output_tokens = tokens_in, tokens_out
    return r


def tabla(resultados: list[ResultadoCaso]) -> str:
    simbolo = {True: "✓", False: "✗", None: "·"}
    ancho = max([len(r.id) for r in resultados] + [4])
    cabecera = "caso".ljust(ancho) + "  " + " ".join(c[:4].ljust(4) for c in CAMPOS)
    lineas = [cabecera, "-" * len(cabecera)]
    for r in resultados:
        if r.error:
            lineas.append(f"{r.id.ljust(ancho)}  ERROR: {r.error}")
            continue
        celdas = " ".join(simbolo[r.campos.get(c)].ljust(4) for c in CAMPOS)
        lineas.append(f"{r.id.ljust(ancho)}  {celdas}")
    lineas.append("-" * len(cabecera))
    totales = []
    for c in CAMPOS:
        evaluados = [
            bool(r.campos[c]) for r in resultados if r.campos.get(c) is not None
        ]
        if evaluados:
            totales.append(f"{c}: {sum(evaluados)}/{len(evaluados)}")
    lineas.append("Aciertos  " + " · ".join(totales))
    fallos = [
        f"  {r.id} · {campo}: {detalle}"
        for r in resultados
        for campo, detalle in r.detalles.items()
    ]
    if fallos:
        lineas += ["", "Fallos:"] + fallos
    return "\n".join(lineas)


def costo(resultados: list[ResultadoCaso]) -> tuple[int, int, float]:
    tin = sum(r.input_tokens for r in resultados)
    tout = sum(r.output_tokens for r in resultados)
    usd = (tin * settings.precio_input_mtok + tout * settings.precio_output_mtok) / 1e6
    return tin, tout, usd


async def main(argv: list[str] | None = None) -> list[ResultadoCaso]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("carpeta", type=Path)
    parser.add_argument(
        "--solo", default="", help="solo los casos cuyo nombre empieza así"
    )
    parser.add_argument("--paralelo", type=int, default=3)
    args = parser.parse_args(argv)

    raiz: Path = args.carpeta
    carpetas = sorted(
        d
        for d in raiz.iterdir()
        if d.is_dir()
        and (d / "esperado.json").exists()
        and d.name.startswith(args.solo)
    )
    if not carpetas:
        raise SystemExit(f"No hay casos con esperado.json en {raiz}")
    print(f"Evaluando {len(carpetas)} casos con {settings.extraction_model}…")

    settings.db_path = raiz / "_evaluacion.db"
    settings.db_path.unlink(missing_ok=True)
    db = await connect()
    semaforo = asyncio.Semaphore(max(1, args.paralelo))
    try:
        resultados = await asyncio.gather(
            *(
                evaluar_caso(db, i, carpeta, semaforo)
                for i, carpeta in enumerate(carpetas, 1)
            )
        )
    finally:
        await db.close()

    print(tabla(resultados))
    tin, tout, usd = costo(resultados)
    print(
        f"\nTokens: {tin:,} de entrada y {tout:,} de salida · "
        f"costo estimado {usd:.2f} USD ({usd / len(resultados):.3f} por caso)"
    )
    (raiz / "_resultados.json").write_text(
        json.dumps(
            [
                {
                    "id": r.id,
                    "error": r.error,
                    "campos": r.campos,
                    "fallos": r.detalles,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                }
                for r in resultados
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Detalle en {raiz / '_resultados.json'}")
    return resultados


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
