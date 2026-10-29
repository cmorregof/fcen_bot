"""Salidas para revisión humana: dos hojas de cálculo y un borrador Word."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from app.servicios.calidad.soportes.modelos import (
    Archivo,
    Cruce,
    Descripcion,
    ResumenCierre,
    Veredicto,
)
from app.servicios.calidad.soportes.verificador import PATRON_CITA, PATRON_ID

# Regla del 28-oct: el Comité Asesor no aprueba, recomienda; decide el Consejo.
ENCABEZADO_BORRADOR = (
    "BORRADOR — propuesta sujeta a revisión de la oficina de calidad, a la "
    "recomendación del Comité Asesor y a la decisión del Consejo de Facultad"
)
NOTA_PROPUESTA = (
    "Las columnas marcadas «(propuesta)» las llenó un modelo de lenguaje. Son una "
    "propuesta, no una decisión: la oficina de calidad las revisa y las corrige, el "
    "Comité Asesor recomienda y el Consejo de Facultad decide."
)

# Caracteres de control que no caben en XML: openpyxl y python-docx fallan con
# ellos y la corrida perdería las salidas después de haber pagado las llamadas.
_ILEGALES = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def limpio(texto: str) -> str:
    return _ILEGALES.sub("", texto)


def celda(valor: Any) -> Any:
    """Texto seguro para una celda: sin caracteres ilegales y nunca una fórmula."""
    if not isinstance(valor, str):
        return valor
    valor = limpio(valor)
    if valor[:1] in ("=", "+", "-", "@"):
        valor = "\u2019" + valor  # apóstrofo tipográfico: se lee como texto
    return valor


AMARILLO = PatternFill("solid", fgColor="FFF2CC")
GRIS = PatternFill("solid", fgColor="D9D9D9")


def _hoja(
    ws: Worksheet, encabezado: list[str], anchos: list[int], humanas: int
) -> None:
    ws.append(encabezado)
    for j, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(j)].width = ancho
        celda = ws.cell(row=1, column=j)
        celda.font = Font(bold=True)
        celda.alignment = Alignment(wrap_text=True, vertical="top")
        celda.fill = AMARILLO if j > len(encabezado) - humanas else GRIS
    ws.freeze_panes = "A2"


def _fila(ws: Worksheet, valores: list[Any]) -> None:
    ws.append([celda(v) for v in valores])


def _ajustar(ws: Worksheet) -> None:
    for fila in ws.iter_rows(min_row=2):
        for celda in fila:
            celda.alignment = Alignment(wrap_text=True, vertical="top")
    ws.auto_filter.ref = ws.dimensions


def _leeme(libro: Workbook, titulo: str, lineas: list[str]) -> None:
    ws = libro.create_sheet("Léeme")
    ws.column_dimensions["A"].width = 120
    ws.append([titulo])
    ws["A1"].font = Font(bold=True, size=13)
    for linea in [NOTA_PROPUESTA, *lineas]:
        ws.append([linea])
    for fila in ws.iter_rows(min_row=2):
        fila[0].alignment = Alignment(wrap_text=True)


def inventario_xlsx(
    ruta: Path, archivos: list[Archivo], descripciones: dict[str, Descripcion]
) -> None:
    libro = Workbook()
    ws = libro.active
    assert ws is not None
    ws.title = "Inventario"
    encabezado = [
        "ID", "Acción", "Archivo", "Ruta", "Tipo", "Tamaño (KB)", "Páginas",
        "Fecha (metadatos)", "Dentro de",
        "Qué es (propuesta)", "Fecha del documento (propuesta)",
        "Qué prueba (propuesta)", "¿Ilegible o incompleto? (propuesta)",
        "Observación (propuesta)", "Estado de la descripción",
        "¿Correcto? (Sí/No)", "Corrección",
    ]  # fmt: skip
    anchos = [7, 8, 30, 45, 8, 9, 8, 12, 8, 45, 14, 45, 12, 30, 22, 12, 40]
    _hoja(ws, encabezado, anchos, humanas=2)
    for a in archivos:
        d = descripciones.get(a.id)
        datos = d.datos if d else None
        if d is None:
            estado = "sin procesar"
        elif datos is None:
            estado = f"sin descripción: {d.error}"
        else:
            estado = "desde caché" if d.desde_cache else "descrito"
        _fila(
            ws,
            [
                a.id,
                a.accion or "general",
                a.nombre,
                a.ruta,
                a.tipo,
                round(a.tamano / 1024, 1),
                a.paginas,
                a.fecha or "",
                a.dentro_de_zip or "",
                datos.que_es if datos else "",
                datos.fecha_documento if datos else "",
                datos.que_prueba if datos else "",
                ("Sí" if datos.ilegible_o_incompleto else "No") if datos else "",
                datos.observacion if datos else "",
                estado,
                "",
                "",
            ],
        )
    validacion = DataValidation(type="list", formula1='"Sí,No"', allow_blank=True)
    ws.add_data_validation(validacion)
    validacion.add(f"P2:P{max(2, ws.max_row)}")
    _ajustar(ws)
    _leeme(
        libro,
        "Inventario de soportes — revisión de la oficina de calidad",
        [
            "Una fila por archivo. Los archivos dentro de un zip tienen su propia fila "
            "(«Dentro de» indica el zip).",
            "Acción «general»: archivos fuera de las carpetas ACCION n.n.",
            "Llene «¿Correcto? (Sí/No)» y, si es No, escriba la descripción correcta "
            "en «Corrección».",
        ],
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta)


def _citas_legibles(estados_validos: list[str], estados_invalidos: list[str]) -> str:
    partes = estados_validos[:]
    partes += [f"{c} ⚠ no está en el inventario" for c in estados_invalidos]
    return "; ".join(partes)


def _sugerencia_texto(c: Cruce) -> str:
    if c.sugerencia is None:
        return ""
    return (
        f"Dónde buscar: {c.sugerencia.donde_buscar}\n\n"
        f"Para el próximo plan: {c.sugerencia.accion_proximo_plan}"
    )


def cruce_xlsx(ruta: Path, cruces: list[Cruce]) -> None:
    libro = Workbook()
    ws = libro.active
    assert ws is not None
    ws.title = "Cruce por acción"
    encabezado = [
        "Acción", "Aspecto", "Descripción de la acción", "Indicador (meta)",
        "Veredicto (propuesta)", "% de avance (propuesta)", "Justificación (propuesta)",
        "Lo que falta (propuesta)", "Citas", "Verificación de citas", "Alertas",
        "Sugerencia (no es evidencia)", "Revisado por calidad", "Ajuste",
    ]  # fmt: skip
    anchos = [8, 30, 40, 40, 16, 10, 60, 45, 40, 30, 40, 60, 12, 40]
    _hoja(ws, encabezado, anchos, humanas=2)
    for c in cruces:
        p = c.propuesta
        validas = [
            f"{e.cita} ({e.archivo.nombre}{'; ' + e.nota if e.nota else ''})"
            for e in c.verificacion
            if e.valida and e.archivo
        ]
        invalidas = [e.cita for e in c.verificacion if not e.valida]
        verif = (
            "sin citas"
            if not c.verificacion
            else f"{len(validas)} válidas, {len(invalidas)} no verificadas"
        )
        _fila(
            ws,
            [
                c.accion.codigo,
                c.accion.aspecto,
                c.accion.descripcion,
                c.accion.indicador,
                p.veredicto.value if p else f"sin propuesta: {c.error}",
                p.avance_propuesto if p else "",
                p.justificacion if p else "",
                p.falta if p else "",
                _citas_legibles(validas, invalidas),
                verif,
                "\n".join(c.alertas),
                _sugerencia_texto(c),
                "",
                "",
            ],
        )
    validacion = DataValidation(type="list", formula1='"Sí,No"', allow_blank=True)
    ws.add_data_validation(validacion)
    validacion.add(f"M2:M{max(2, ws.max_row)}")
    _ajustar(ws)
    _leeme(
        libro,
        "Cruce de acciones — propuesta de cierre del plan",
        [
            "Veredictos posibles: «evidencia suficiente», «parcial», «sin evidencia».",
            "«Verificación de citas»: un programa comprueba que cada cita apunte a un "
            "archivo del inventario. Las que no, se marcan con ⚠ y no se borran.",
            "«Sugerencia» solo aparece en las acciones sin evidencia: dice dónde "
            "buscar el soporte y qué acción poner en el próximo plan. No es "
            "evidencia y no cambia el veredicto.",
            "La oficina de calidad llena «Revisado por calidad» (Sí/No) y, si hace "
            "falta, el veredicto o el % correcto en «Ajuste». Después, el Comité "
            "Asesor recomienda y el Consejo de Facultad decide el cierre.",
        ],
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta)


def citas_a_nombres(
    texto: str, inventario: dict[str, Archivo], validas: set[str] | None = None
) -> str:
    """[S012] -> [S012 · nombre.pdf]; [S012, S013] -> una por ID.

    Las que no existen, o no pasaron el verificador (`validas`), quedan marcadas.
    """

    def una(cita: str) -> str:
        archivo = inventario.get(cita)
        if archivo is None or (validas is not None and cita not in validas):
            return f"[{cita} ⚠ cita no verificada]"
        return f"[{cita} · {archivo.nombre}]"

    def reemplazar(m: re.Match[str]) -> str:
        return " ".join(una(c) for c in PATRON_ID.findall(m.group(1)))

    return PATRON_CITA.sub(reemplazar, texto)


PATRON_NEGRITA = re.compile(r"\*\*(.+?)\*\*")


def parrafo_con_formato(doc: Any, texto: str) -> None:
    """Escribe un párrafo del modelo: «- » es viñeta y **x** es negrita.

    El modelo a veces responde con marcas de Markdown; en Word saldrían tal cual.
    """
    texto = limpio(texto).strip()
    estilo = None
    if texto.startswith(("- ", "• ")):
        texto, estilo = texto[2:].strip(), "List Bullet"
    parrafo = doc.add_paragraph(style=estilo)
    inicio = 0
    for m in PATRON_NEGRITA.finditer(texto):
        if m.start() > inicio:
            parrafo.add_run(texto[inicio : m.start()])
        parrafo.add_run(m.group(1)).bold = True
        inicio = m.end()
    if inicio < len(texto):
        parrafo.add_run(texto[inicio:])


def borrador_docx(
    ruta: Path,
    programa: str,
    cruces: list[Cruce],
    resumen: ResumenCierre | None,
    alertas_resumen: list[str],
    inventario: dict[str, Archivo],
) -> None:
    validas_plan = set().union(*(c.citas_validas for c in cruces))
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(11)

    aviso = doc.add_paragraph()
    corrida = aviso.add_run(ENCABEZADO_BORRADOR)
    corrida.bold = True
    corrida.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    doc.sections[0].header.paragraphs[0].text = ENCABEZADO_BORRADOR

    doc.add_heading(limpio(f"Cierre del plan de mejoramiento — {programa}"), level=1)
    doc.add_paragraph(
        f"Borrador generado el {date.today().isoformat()}. Los veredictos, los "
        "porcentajes y los párrafos son propuestas de un modelo de lenguaje a partir "
        "de los soportes de cada acción; no son decisiones. La oficina de calidad "
        "los revisa, el Comité Asesor recomienda aprobar o no aprobar el cierre y "
        "el Consejo de Facultad decide. Las citas [ID · archivo] remiten a "
        "inventario_soportes.xlsx; las marcadas con ⚠ no pasaron el verificador y "
        "no cuentan como evidencia."
    )

    conteo = {v: 0 for v in Veredicto}
    for c in cruces:
        if c.propuesta:
            conteo[c.propuesta.veredicto] += 1
    sin = sum(1 for c in cruces if c.propuesta is None)
    doc.add_heading("Resumen general (propuesta)", level=2)
    doc.add_paragraph(
        f"Acciones: {len(cruces)}. Evidencia suficiente: "
        f"{conteo[Veredicto.SUFICIENTE]}; parcial: {conteo[Veredicto.PARCIAL]}; "
        f"sin evidencia: {conteo[Veredicto.SIN_EVIDENCIA]}"
        + (f"; sin propuesta: {sin}." if sin else ".")
    )
    if resumen:
        for parrafo in resumen.resumen.split("\n"):
            if parrafo.strip():
                parrafo_con_formato(
                    doc, citas_a_nombres(parrafo, inventario, validas_plan)
                )
    else:
        doc.add_paragraph("No se pudo generar el resumen general.")
    for alerta in alertas_resumen:
        doc.add_paragraph(f"⚠ {alerta}")

    doc.add_heading("Cierre por acción (propuesta)", level=2)
    for c in cruces:
        a = c.accion
        doc.add_heading(limpio(f"Acción {a.codigo}. {a.descripcion}"), level=3)
        meta = doc.add_paragraph()
        meta.add_run("Indicador: ").bold = True
        meta.add_run(limpio(a.indicador))
        if c.propuesta is None:
            doc.add_paragraph(f"Sin propuesta: {c.error}")
            continue
        p = c.propuesta
        linea = doc.add_paragraph()
        linea.add_run("Veredicto propuesto: ").bold = True
        linea.add_run(f"{p.veredicto.value} · avance propuesto {p.avance_propuesto} %")
        for parrafo in p.parrafo_cierre.split("\n"):
            if parrafo.strip():
                parrafo_con_formato(
                    doc, citas_a_nombres(parrafo, inventario, c.citas_validas)
                )
        if p.falta:
            doc.add_paragraph().add_run("Lo que falta:").italic = True
            for parrafo in p.falta.split("\n"):
                if parrafo.strip():
                    parrafo_con_formato(
                        doc, citas_a_nombres(parrafo, inventario, c.citas_validas)
                    )
        for alerta in c.alertas:
            doc.add_paragraph(f"⚠ {alerta}")

    con_sugerencia = [c for c in cruces if c.sugerencia]
    if con_sugerencia:
        doc.add_heading("Sugerencias para las acciones sin evidencia", level=2)
        doc.add_paragraph(
            "No son evidencia ni forman parte del cierre. Indican dónde buscar "
            "soportes de la época y qué acción podría ir en el próximo plan."
        )
        for c in con_sugerencia:
            s = c.sugerencia
            assert s is not None
            doc.add_heading(f"Acción {c.accion.codigo}", level=3)
            buscar = doc.add_paragraph()
            buscar.add_run("Dónde buscar: ").bold = True
            buscar.add_run(limpio(s.donde_buscar))
            plan = doc.add_paragraph()
            plan.add_run("Para el próximo plan: ").bold = True
            plan.add_run(limpio(s.accion_proximo_plan))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(ruta))
