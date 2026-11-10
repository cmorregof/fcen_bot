"""Carpetas «Soportes de acciones» tal como salen de Drive.

Reproduce los patrones de las descargas reales de los programas con nombres
inventados: acciones con punto o espacio final, carpetas vacías, subcarpetas
de más, exportados de Google sin propiedades y descargas divididas.
"""

from __future__ import annotations

import io
import unicodedata
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.servicios.calidad.soportes.carga import extraer, grupo_de_parte
from app.servicios.calidad.soportes.inventario import (
    accion_de_ruta,
    carpetas,
    inventariar,
)
from app.servicios.calidad.soportes.organizacion import revisar, tipo_subcarpeta
from app.servicios.calidad.soportes.salidas import indice_electronico_xlsx

RAIZ = "Soportes de acciones"
LIMITES = {"max_bytes": 10**8, "max_archivos": 1000}


def _zip(ruta: Path, entradas: dict[str, bytes | None]) -> Path:
    """None es una carpeta (entrada que termina en «/»), como las pone Drive."""
    with zipfile.ZipFile(ruta, "w") as zf:
        for nombre, datos in entradas.items():
            if datos is None:
                zf.writestr(zipfile.ZipInfo(nombre.rstrip("/") + "/"), b"")
            else:
                zf.writestr(nombre, datos)
    return ruta


def _como_google(crudo: bytes) -> bytes:
    """Sin docProps/core.xml ni app.xml, como exporta Google Docs y Hojas."""
    salida = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(crudo)) as origen,
        zipfile.ZipFile(salida, "w") as destino,
    ):
        for info in origen.infolist():
            if not info.filename.startswith("docProps/"):
                destino.writestr(info, origen.read(info))
    return salida.getvalue()


def _xlsx_de_google() -> bytes:
    libro = Workbook()
    libro.active["A1"] = "dato ficticio"  # type: ignore[index]
    crudo = io.BytesIO()
    libro.save(crudo)
    return _como_google(crudo.getvalue())


def _docx_de_google() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph("texto ficticio")
    crudo = io.BytesIO()
    doc.save(crudo)
    return _como_google(crudo.getvalue())


def _pptx(diapositivas: int) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for i in range(1, diapositivas + 1):
            zf.writestr(f"ppt/slides/slide{i}.xml", "<p:sld/>")
    return salida.getvalue()


@pytest.mark.parametrize(
    ("carpeta", "codigo"),
    [
        ("Acción 6.1.", "6.1"),
        ("Acción 2.1 ", "2.1"),
        ("ACCIÓN 1.2.1", "1.2.1"),
        ("accion_3.1", "3.1"),
        ("Acción-4.2.", "4.2"),
        (unicodedata.normalize("NFD", "Acción 5.3"), "5.3"),
    ],
)
def test_codigo_de_la_accion_con_variantes_de_drive(carpeta: str, codigo: str) -> None:
    assert accion_de_ruta(f"{RAIZ}/{carpeta}/Producto final/x.pdf") == codigo


def test_no_es_accion_sin_codigo() -> None:
    assert accion_de_ruta(f"{RAIZ}/Plan de accion 2016/x.pdf") == ""
    assert accion_de_ruta(f"{RAIZ}/Acciones generales/x.pdf") == ""


@pytest.mark.parametrize(
    ("nombre", "tipo"),
    [
        ("Producto final", "producto final"),
        ("PRODUCTO FINAL ", "producto final"),
        ("Productos finales", "producto final"),
        ("Soportes de producto final", "soportes"),
        ("SOPORTES DE PRODUCTO FINAL", "soportes"),
        ("Soporte", "soportes"),
        ("Fotos", ""),
    ],
)
def test_subcarpetas_con_mayusculas_y_plurales(nombre: str, tipo: str) -> None:
    assert tipo_subcarpeta(nombre) == tipo


def test_acciones_y_carpetas_vacias_no_desaparecen(tmp_path: Path) -> None:
    origen = _zip(
        tmp_path / "plan.zip",
        {
            f"{RAIZ}/Acción 1.1/Producto final/": None,
            f"{RAIZ}/Acción 1.1/Soportes de producto final/01 Acta 20250301.pdf": b"%PDF-1.4",
            f"{RAIZ}/Acción 2.1./Producto final/": None,
            f"{RAIZ}/Acción 2.1./Soportes de producto final/": None,
            f"{RAIZ}/Acción 3.1/Soportes de producto final/01 Lista 20250405.pdf": b"%PDF-1.4 b",
            f"{RAIZ}/Acción 3.1/Soportes de producto final/desktop.ini": b"[x]",
        },
    )
    destino = tmp_path / "soportes"
    assert extraer(origen, destino, **LIMITES) == 2
    assert (destino / RAIZ / "Acción 2.1." / "Producto final").is_dir()
    org = revisar(inventariar(destino), carpetas(destino))
    assert org.acciones["1.1"] == ["la carpeta «Producto final» está vacía"]
    assert org.acciones["2.1"] == [
        "la carpeta de la acción está vacía: no tiene archivos"
    ]
    assert org.acciones["3.1"] == ["no tiene carpeta «Producto final»"]
    # Sin las carpetas (como antes), la acción vacía no aparecía.
    assert "2.1" not in revisar(inventariar(destino)).acciones


def test_subcarpetas_de_mas_dentro_de_producto_final(tmp_path: Path) -> None:
    accion = tmp_path / RAIZ / "Acción 5.1"
    (accion / "Producto final" / "Volumen 1" / "Anexos").mkdir(parents=True)
    (accion / "Producto final" / "Volumen 1" / "Informe.pdf").write_bytes(b"%PDF-1")
    (accion / "Producto final" / "Volumen 1" / "Anexos" / "Tabla.pdf").write_bytes(
        b"%PDF-2"
    )
    (accion / "Soportes de producto final").mkdir()
    (accion / "Soportes de producto final" / "01 Acta 20250101.pdf").write_bytes(
        b"%PDF-3"
    )
    org = revisar(inventariar(tmp_path), carpetas(tmp_path))
    assert any("2 archivos dentro de subcarpetas" in o for o in org.acciones["5.1"])
    por_nombre = {r.archivo.nombre: r for r in org.archivos}
    assert "está en una subcarpeta de «Producto final»" in (
        por_nombre["Tabla.pdf"].observaciones
    )
    assert por_nombre["01 Acta 20250101.pdf"].observaciones == []


def test_descarga_dividida_de_drive(tmp_path: Path) -> None:
    uno = _zip(
        tmp_path / "Soportes de acciones-20260101T000000Z-1-001.zip",
        {f"{RAIZ}/Acción 1.1/Producto final/Informe.pdf": b"%PDF-1"},
    )
    dos = _zip(
        tmp_path / "Soportes de acciones-20260101T000000Z-2-001.zip",
        {
            f"{RAIZ}/Acción 1.1/Soportes de producto final/01 Acta 20250101.pdf": b"%PDF-2"
        },
    )
    assert grupo_de_parte(uno.name) == grupo_de_parte(dos.name)
    assert grupo_de_parte("Programa.zip") == "Programa"
    destino = tmp_path / "soportes"
    assert extraer([uno, dos], destino, **LIMITES) == 2
    org = revisar(inventariar(destino), carpetas(destino))
    assert org.acciones == {"1.1": []}
    # Los límites cuentan para todas las partes juntas.
    from app.servicios.calidad.soportes.carga import ZipNoValido

    with pytest.raises(ZipNoValido):
        extraer([uno, dos], tmp_path / "otro", max_bytes=10**8, max_archivos=1)


def test_exportados_de_google_y_formatos_en_el_indice(tmp_path: Path) -> None:
    soportes = tmp_path / RAIZ / "Acción 1.1" / "Soportes de producto final"
    soportes.mkdir(parents=True)
    (tmp_path / RAIZ / "Acción 1.1" / "Producto final").mkdir()
    (tmp_path / RAIZ / "Acción 1.1" / "Producto final" / "Informe.pdf").write_bytes(
        b"%PDF-1.4"
    )
    (soportes / "01 Hoja de Google 20250101.xlsx").write_bytes(_xlsx_de_google())
    (soportes / "02 Presentacion 20250102.pptx").write_bytes(_pptx(3))
    (soportes / "03 Listado antiguo 20250103.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    (soportes / "04 Documento de Google 20250104.docx").write_bytes(_docx_de_google())
    archivos = inventariar(tmp_path)
    por_nombre = {a.nombre: a for a in archivos}
    hoja = por_nombre["01 Hoja de Google 20250101.xlsx"]
    # Sin propiedades no hay fecha; antes salía la fecha de hoy.
    assert hoja.tipo == "xlsx" and hoja.fecha is None
    assert por_nombre["04 Documento de Google 20250104.docx"].fecha is None
    assert por_nombre["02 Presentacion 20250102.pptx"].paginas == 3

    salida = tmp_path / "indice.xlsx"
    indice_electronico_xlsx(salida, revisar(archivos, carpetas(tmp_path)))
    ws = load_workbook(salida)["Formato"]
    filas = {
        ws[f"B{n}"].value: (ws[f"F{n}"].value, ws[f"I{n}"].value) for n in range(13, 18)
    }
    assert filas["01 Hoja de Google 20250101"] == (None, "excel")
    assert filas["02 Presentacion 20250102"] == (3, "powerpoint")
    assert filas["03 Listado antiguo 20250103"] == (None, "excel")
    assert filas["04 Documento de Google 20250104"] == (None, "word")
    # Sin fecha en los metadatos: la celda queda en amarillo.
    fila = next(n for n in range(13, 18) if ws[f"B{n}"].value.startswith("01 Hoja"))
    assert ws[f"C{fila}"].fill.fgColor.rgb.endswith("FFFF00")
