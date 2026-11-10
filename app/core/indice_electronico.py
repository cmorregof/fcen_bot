"""Formato oficial «Índice electrónico» del expediente.

Es el formato de la Vicedecanatura (00IndiceElectronicoPlanesMejoraFCEN.xlsx):
encabezado del fondo en las filas 3 a 5; Oficina Productora, Serie, Subserie
e identificación del expediente en C7:G10; bloque de expediente físico en
I7:L10; títulos B–L en la fila 12 y una fila por documento desde la 13, con
las fórmulas de foliación del formato; al final, fecha de cierre y firma.

Lo usan el índice de los planes de mejoramiento (servicio de calidad) y el
archivo oficial de actas, oficios y resoluciones en Drive. Es determinista:
no pasa por un modelo de lenguaje.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, replace
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

COLUMNAS = [
    "Nombre Documento", "Fecha Creación Documento", "Fecha Incorporación Expediente",
    "Orden Documento", "Número Páginas", "Página Inicio", "Página Fin", "Formato",
    "Tamaño", "Origen", "Observaciones",
]  # fmt: skip
FILA_TITULOS = 12
PRIMERA_FILA = 13
ROTULO_CIERRE = "Fecha de cierre del expediente"
ROTULO_FIRMA = "Firma del jefe de la oficina productora"
AMARILLO = PatternFill("solid", fgColor="FFFF00")
_ANCHOS = [2, 42, 14, 14, 10, 10, 9, 9, 10, 10, 13, 40]

# Caracteres de control que no caben en XML: openpyxl falla con ellos.
_ILEGALES = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def limpio(texto: str) -> str:
    return _ILEGALES.sub("", texto)


def celda(valor: Any) -> Any:
    """Texto seguro para una celda: sin caracteres ilegales y nunca una fórmula."""
    if not isinstance(valor, str):
        return valor
    valor = limpio(valor)
    if valor[:1] in ("=", "+", "-", "@"):
        valor = "’" + valor  # apóstrofo tipográfico: se lee como texto
    return valor


@dataclass(frozen=True)
class Expediente:
    """Encabezado del índice. Lo vacío queda en amarillo para llenarlo."""

    oficina_productora: str
    serie: str
    subserie: str
    identificacion: str = ""
    subfondo: str = "SUBFONDO"
    dependencia: str = "Vicedecanatura Facultad Ciencias Exactas y Naturales"
    fisico: str = "NO"
    carpetas: str = ""
    folios: str = ""


@dataclass
class Fila:
    """Un documento del expediente. Fechas en DD/MM/AAAA."""

    nombre: str
    fecha_creacion: str = ""
    fecha_incorporacion: str = ""
    paginas: int | None = None
    formato: str = ""
    tamano: str = ""
    origen: str = "Electrónico"
    observaciones: str = ""


def tamano_kb(n: int) -> str:
    return f"{max(1, round(n / 1024))} kb"


def libro(expediente: Expediente, filas: list[Fila], leeme: list[str]) -> Workbook:
    """Arma el índice: hoja «Formato» y, si hay líneas, hoja «Léeme»."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Formato"
    borde = Border(*(Side(style="thin"),) * 4)
    negrita = Font(bold=True)
    for col, ancho in zip("ABCDEFGHIJKL", _ANCHOS, strict=True):
        ws.column_dimensions[col].width = ancho

    for n, texto in [
        (3, "FONDO UNIVERSIDAD NACIONAL DE COLOMBIA"),
        (4, expediente.subfondo),
        (5, expediente.dependencia),
    ]:
        ws.merge_cells(f"B{n}:L{n}")
        ws[f"B{n}"] = celda(texto)
        ws[f"B{n}"].font = Font(bold=True, size=13)
        ws[f"B{n}"].alignment = Alignment(horizontal="center")
    datos = [
        ("Oficina Productora", expediente.oficina_productora),
        ("Serie", expediente.serie),
        ("Subserie Documental", expediente.subserie),
        ("Identificación del expediente", expediente.identificacion),
    ]
    fisico: list[tuple[str, str | None]] = [
        ("EXPEDIENTE FÍSICO", None),
        ("El expediente posee documentos físicos:", expediente.fisico),
        ("No. de carpetas", expediente.carpetas),
        ("No. de folios", expediente.folios),
    ]
    for i, ((rotulo, valor), (rot_f, val_f)) in enumerate(
        zip(datos, fisico, strict=True), start=7
    ):
        ws.merge_cells(f"C{i}:G{i}")
        ws[f"B{i}"], ws[f"C{i}"] = rotulo, celda(valor)
        ws[f"B{i}"].font = negrita
        for c in ("B", "C"):
            ws[f"{c}{i}"].border = borde
        if not valor:
            ws[f"C{i}"].fill = AMARILLO
        if val_f is None:
            ws.merge_cells(f"I{i}:L{i}")
            ws[f"I{i}"] = rot_f
            ws[f"I{i}"].font = negrita
        else:
            ws.merge_cells(f"I{i}:J{i}")
            ws.merge_cells(f"K{i}:L{i}")
            ws[f"I{i}"], ws[f"K{i}"] = rot_f, celda(val_f)

    for j, titulo in enumerate(COLUMNAS, start=2):
        c = ws.cell(row=FILA_TITULOS, column=j, value=titulo)
        c.font = negrita
        c.border = borde
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[FILA_TITULOS].height = 45

    for k, f in enumerate(filas):
        n = PRIMERA_FILA + k
        inicio = f'=IF(F{n}=0,"0","1")' if k == 0 else f'=IF(F{n}=0,"0",(1+H{n - 1}))'
        valores: list[Any] = [
            f.nombre,
            f.fecha_creacion,
            f.fecha_incorporacion,
            k + 1,
            f.paginas,
            inicio,
            f"=G{n}+(F{n}-1)" if k else f"=G{n}+(F{n}-G{n})",
            f.formato,
            f.tamano,
            f.origen,
            f.observaciones,
        ]
        for j, v in enumerate(valores, start=2):
            c = ws.cell(row=n, column=j, value=celda(v) if j not in (7, 8) else v)
            c.border = borde
            if j > 2:
                c.alignment = Alignment(horizontal="center")
        # Lo que no se sabe queda en amarillo para que lo llene la oficina.
        for j, v in ((3, f.fecha_creacion), (4, f.fecha_incorporacion), (6, f.paginas)):
            if v in ("", None):
                ws.cell(row=n, column=j).fill = AMARILLO
    fin = PRIMERA_FILA + len(filas) + 1
    ws[f"B{fin}"] = ROTULO_CIERRE
    ws[f"B{fin + 2}"] = ROTULO_FIRMA
    for c in (f"B{fin}", f"B{fin + 2}"):
        ws[c].font = negrita

    if leeme:
        hoja = wb.create_sheet("Léeme")
        hoja.column_dimensions["A"].width = 120
        for linea in leeme:
            hoja.append([linea])
        hoja["A1"].font = Font(bold=True, size=13)
        for fila in hoja.iter_rows(min_row=2):
            fila[0].alignment = Alignment(wrap_text=True)
    return wb


def a_bytes(wb: Workbook) -> bytes:
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def es_formato_oficial(contenido: bytes) -> bool:
    wb = load_workbook(io.BytesIO(contenido), read_only=True)
    try:
        ws = wb.worksheets[0]
        return bool(ws.cell(FILA_TITULOS, 2).value == COLUMNAS[0])
    finally:
        wb.close()


def leer(contenido: bytes, base: Expediente) -> tuple[Expediente, list[Fila]]:
    """Lee un índice en formato oficial para agregarle filas.

    Conserva lo que la oficina haya escrito a mano en el encabezado
    (identificación y expediente físico); las fórmulas y el orden se
    vuelven a generar al escribirlo.
    """
    wb = load_workbook(io.BytesIO(contenido), read_only=True)
    ws = wb.worksheets[0]

    def texto(v: Any) -> str:
        return "" if v is None else str(v)

    encabezado = {
        "identificacion": texto(ws["C10"].value) or base.identificacion,
        "fisico": texto(ws["K8"].value) or base.fisico,
        "carpetas": texto(ws["K9"].value) or base.carpetas,
        "folios": texto(ws["K10"].value) or base.folios,
    }
    filas: list[Fila] = []
    for v in ws.iter_rows(
        min_row=PRIMERA_FILA, min_col=2, max_col=12, values_only=True
    ):
        if v[0] in (None, "") or v[0] in (ROTULO_CIERRE, ROTULO_FIRMA):
            break
        paginas = v[4]
        filas.append(
            Fila(
                nombre=texto(v[0]),
                fecha_creacion=texto(v[1]),
                fecha_incorporacion=texto(v[2]),
                paginas=int(paginas) if isinstance(paginas, int | float) else None,
                formato=texto(v[7]),
                tamano=texto(v[8]),
                origen=texto(v[9]) or "Electrónico",
                observaciones=texto(v[10]),
            )
        )
    wb.close()
    return replace(base, **encabezado), filas
