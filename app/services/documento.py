"""Borrador del oficio al Consejo de Facultad, en .docx, con la plantilla única.

Todo el texto se arma con reglas a partir de los datos ya registrados; aquí no
se llama al modelo. La estructura de cada caso sigue la de las actas de
Ingeniería Física: identificación y cita del correo, ANÁLISIS, pantallazos,
RECOMENDACIÓN, tabla de asignaturas y la norma textual.
"""

from __future__ import annotations

import io
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentoDocx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX, WD_TAB_ALIGNMENT
from docx.shared import Cm, Emu, Pt, RGBColor
from docx.text.paragraph import Paragraph
from lxml import etree
from PIL import Image as PILImage

from app.core.programas import Programa
from app.normativa.base import NormaCitada, normas_para
from app.schemas.caso import TITULOS_TIPO, Caso, ExtraccionCaso, Sentido
from app.services.reglas import Analisis

PLANTILLA = Path(__file__).resolve().parents[1] / "templates" / "oficio_base.docx"

_MESES = (
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre "
    "noviembre diciembre"
).split()

_UNIDADES = (
    "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece "
    "catorce quince dieciséis diecisiete dieciocho diecinueve veinte veintiuno "
    "veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete "
    "veintiocho veintinueve"
).split()
_DECENAS = {
    3: "treinta",
    4: "cuarenta",
    5: "cincuenta",
    6: "sesenta",
    7: "setenta",
    8: "ochenta",
    9: "noventa",
}


def en_letras(n: int) -> str:
    """Número de créditos en letras, como en las actas («trece créditos»)."""
    if 0 <= n < 30:
        palabra = _UNIDADES[n]
        return "un" if palabra == "uno" else palabra.replace("veintiuno", "veintiún")
    if 30 <= n < 100:
        decena, unidad = divmod(n, 10)
        base = _DECENAS[decena]
        if unidad == 0:
            return base
        resto = "un" if unidad == 1 else _UNIDADES[unidad]
        return f"{base} y {resto}"
    return str(n)


def creditos_texto(n: int) -> str:
    unidad = "crédito" if n == 1 else "créditos"
    return f"{en_letras(n)} {unidad} ({n} {unidad})"


def fecha_larga(valor: date | str | None) -> str:
    if valor is None:
        return "____"
    if isinstance(valor, str):
        try:
            dia = date.fromisoformat(valor[:10])
        except ValueError:
            return valor
    else:
        dia = valor
    return f"{dia.day:02d} de {_MESES[dia.month - 1]} de {dia.year}"


_NO_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def limpiar(texto: str) -> str:
    """Quita caracteres que Word no acepta (saltos suaves de Outlook, etc.)."""
    return _NO_XML.sub(" ", texto)


def imagen_reducida(ruta: Path, lado_max: int = 1600) -> io.BytesIO:
    """Pantallazo recomprimido para que el .docx no supere el límite de Telegram."""
    with PILImage.open(ruta) as original:
        im = original.convert("RGB")
    im.thumbnail((lado_max, lado_max))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf


def _num(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


@dataclass
class CasoDocumento:
    caso: Caso
    extraccion: ExtraccionCaso
    analisis: Analisis
    cuerpo_correo: str
    imagenes: list[Path] = field(default_factory=list)


@dataclass
class DatosOficio:
    programa: Programa
    fecha: date
    casos: list[CasoDocumento]
    radicado: str | None = None
    numero_acta: str | None = None
    fecha_sesion: str | None = None
    elaboro: str = ""
    borrador: bool = True


# ---------------------------------------------------------------------------
# Utilidades de formato
# ---------------------------------------------------------------------------


def _parrafo(
    doc: DocumentoDocx,
    texto: str = "",
    *,
    negrita: bool = False,
    cursiva: bool = False,
    tam: float = 10,
    alinear: WD_ALIGN_PARAGRAPH | None = WD_ALIGN_PARAGRAPH.JUSTIFY,
    sangria_cm: float = 0,
    despues: float = 6,
    subrayado: bool = False,
) -> Paragraph:
    p = doc.add_paragraph()
    if alinear is not None:
        p.alignment = alinear
    fmt = p.paragraph_format
    fmt.space_after = Pt(despues)
    fmt.space_before = Pt(0)
    if sangria_cm:
        fmt.left_indent = Cm(sangria_cm)
    if texto:
        r = p.add_run(limpiar(texto))
        r.bold = negrita
        r.italic = cursiva
        r.underline = subrayado
        r.font.size = Pt(tam)
    return p


def _run(
    p: Paragraph,
    texto: str,
    *,
    negrita: bool = False,
    cursiva: bool = False,
    tam: float = 10,
) -> None:
    r = p.add_run(limpiar(texto))
    r.bold = negrita
    r.italic = cursiva
    r.font.size = Pt(tam)


def _vineta(doc: DocumentoDocx, texto: str) -> None:
    p = _parrafo(doc, despues=2, sangria_cm=1.0)
    p.paragraph_format.first_line_indent = Cm(-0.5)
    _run(p, "•  " + texto)


def _reemplazar_marcadores(doc: DocumentoDocx, valores: dict[str, str]) -> None:
    """Reemplaza {{MARCADOR}} en encabezados y pies (incluidos cuadros de texto)."""
    w_t = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    vistos: set[int] = set()
    for seccion in doc.sections:
        for parte in (
            seccion.header,
            seccion.footer,
            seccion.first_page_header,
            seccion.first_page_footer,
        ):
            elemento = parte._element
            if id(elemento) in vistos:
                continue
            vistos.add(id(elemento))
            for t in elemento.iter(w_t):
                if t.text and "{{" in t.text:
                    for clave, valor in valores.items():
                        t.text = t.text.replace("{{" + clave + "}}", valor)


def _sombrear(celda: object, color: str) -> None:
    tc_pr = celda._tc.get_or_add_tcPr()  # type: ignore[attr-defined]
    shd = etree.SubElement(
        tc_pr, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd"
    )
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    shd.set(f"{w}val", "clear")
    shd.set(f"{w}color", "auto")
    shd.set(f"{w}fill", color)


# ---------------------------------------------------------------------------
# Bloques del oficio
# ---------------------------------------------------------------------------


def _encabezado_oficio(doc: DocumentoDocx, datos: DatosOficio) -> None:
    if datos.borrador:
        p = _parrafo(doc, alinear=WD_ALIGN_PARAGRAPH.CENTER, despues=10)
        r = p.add_run("BORRADOR · pendiente de revisión del Comité Asesor")
        r.bold = True
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0xB0, 0x00, 0x20)

    p = _parrafo(doc, alinear=WD_ALIGN_PARAGRAPH.LEFT, despues=14)
    seccion = doc.sections[0]
    ancho = Emu(
        int(seccion.page_width or 0)
        - int(seccion.left_margin or 0)
        - int(seccion.right_margin or 0)
    )
    p.paragraph_format.tab_stops.add_tab_stop(ancho, WD_TAB_ALIGNMENT.RIGHT)
    _run(p, f"Manizales, {fecha_larga(datos.fecha)}")
    radicado = (
        datos.radicado
        or f"{datos.programa.radicado_prefijo or 'Mz.FCEN.1.0__'}-___-{datos.fecha:%y}"
    )
    _run(p, f"\t[{radicado}]", negrita=True)

    for i, linea in enumerate(
        (
            "Señores",
            "CONSEJO DE FACULTAD",
            "Facultad de Ciencias Exactas y Naturales",
            "Universidad Nacional de Colombia",
            "Sede Manizales",
        )
    ):
        _parrafo(
            doc,
            linea,
            negrita=(i == 1),
            alinear=WD_ALIGN_PARAGRAPH.LEFT,
            despues=0 if i < 4 else 14,
        )

    acta = datos.numero_acta or "____"
    _parrafo(
        doc,
        f"Asunto: {datos.programa.comite} — Acta {acta} de {datos.fecha.year}",
        alinear=WD_ALIGN_PARAGRAPH.LEFT,
        despues=10,
    )
    _parrafo(doc, "Reciban un cordial y respetuoso saludo.", despues=10)
    fecha_sesion = datos.fecha_sesion or "____"
    _parrafo(
        doc,
        f"El {datos.programa.comite}, en sesión realizada el día {fecha_sesion}, "
        f"según consta en el Acta No. {acta}, llevó a cabo el estudio, análisis y "
        "revisión de los casos relacionados a continuación. Luego de la "
        "correspondiente deliberación y de acuerdo con las disposiciones académicas "
        "y normativas vigentes, el Comité emitió las recomendaciones que se "
        "presentan en el presente documento:",
        despues=12,
    )
    _parrafo(
        doc,
        "CASOS ESTUDIANTILES",
        negrita=True,
        subrayado=True,
        alinear=WD_ALIGN_PARAGRAPH.LEFT,
        despues=10,
    )


def titulo_seccion(extraccion: ExtraccionCaso) -> str:
    if not extraccion.tipos:
        return "OTRAS SOLICITUDES"
    titulos = [TITULOS_TIPO[t] for t in extraccion.tipos]
    if len(titulos) == 1:
        return f"SOLICITUD DE {titulos[0]}".upper()
    return ("SOLICITUD DE " + ", ".join(titulos[:-1]) + " Y " + titulos[-1]).upper()


def _cita(doc: DocumentoDocx, cuerpo: str) -> None:
    bloques = [b.strip() for b in cuerpo.replace("\r", "").split("\n\n") if b.strip()]
    if not bloques:
        return
    for i, bloque in enumerate(bloques):
        # Con saltos de línea (firmas, listas) el justificado estira las palabras.
        alinear = (
            WD_ALIGN_PARAGRAPH.LEFT if "\n" in bloque else WD_ALIGN_PARAGRAPH.JUSTIFY
        )
        p = _parrafo(doc, sangria_cm=1.25, despues=4, alinear=alinear)
        texto = bloque
        if i == 0:
            texto = "“" + texto
        if i == len(bloques) - 1:
            texto = texto + "”"
        lineas = texto.split("\n")
        for j, linea in enumerate(lineas):
            r = p.add_run(limpiar(linea.strip()))
            r.italic = True
            r.font.size = Pt(10)
            if j < len(lineas) - 1:
                r.add_break()


def _bullets_analisis(item: CasoDocumento, periodo: str) -> list[str]:
    e, a = item.extraccion, item.analisis
    vinetas: list[str] = []
    sia = e.sia
    if sia and sia.plan_codigo:
        nombre = (sia.plan_nombre or "").strip().title()
        vinetas.append(f"Plan de estudios [{sia.plan_codigo}] {nombre}".strip())
    if a.creditos_inscritos is not None:
        vinetas.append(
            f"En el periodo académico {sia.periodo if sia and sia.periodo else periodo} "
            f"tiene inscritos {creditos_texto(a.creditos_inscritos)}"
        )
    if (
        a.creditos_tras_solicitud is not None
        and a.creditos_tras_solicitud != a.creditos_inscritos
    ):
        vinetas.append(
            f"Con la solicitud quedaría con {creditos_texto(a.creditos_tras_solicitud)}"
        )
    if a.disciplinares_aprobados is not None:
        if a.disciplinares_exigidos_tdg:
            vinetas.append(
                f"En el componente disciplinar tiene aprobados {a.disciplinares_aprobados} "
                f"créditos de los {a.disciplinares_exigidos_tdg} que se requieren para "
                "inscribir Trabajo de Grado"
            )
        else:
            vinetas.append(
                f"Tiene aprobados {a.disciplinares_aprobados} créditos del componente "
                "disciplinar"
            )
    metricas = []
    if a.papa is not None:
        metricas.append(f"P.A.P.A. {_num(a.papa)}")
    if a.porcentaje_avance is not None:
        metricas.append(f"porcentaje de avance {_num(a.porcentaje_avance)} %")
    if metricas:
        texto = "; ".join(metricas)
        vinetas.append(texto[0].upper() + texto[1:])
    if a.semana is not None:
        vinetas.append(
            f"La solicitud se presentó en la semana {a.semana} del periodo académico"
        )
    if e.modalidad_trabajo_grado:
        vinetas.append(
            f"Modalidad de Trabajo de Grado solicitada: {e.modalidad_trabajo_grado}"
        )
    estudiante = (
        "del estudiante" if e.tratamiento == "El estudiante" else "de la estudiante"
    )
    vinetas.append(f"Se anexa la solicitud {estudiante}")
    for anexo in e.anexos:
        vinetas.append(f"Se anexa {anexo}")
    return vinetas


def texto_recomendacion(
    programa: Programa, item: CasoDocumento
) -> tuple[str, str, str]:
    """(antes, sentido, después) para poder resaltar el sentido si está pendiente."""
    e = item.extraccion
    al = "al estudiante" if e.tratamiento == "El estudiante" else "a la estudiante"
    sentido = {
        Sentido.APROBAR: "aprobar",
        Sentido.NO_APROBAR: "no aprobar",
        Sentido.PENDIENTE: "[APROBAR / NO APROBAR]",
    }[item.caso.sentido]
    objeto = e.objeto_solicitud.strip().rstrip(".") or "lo solicitado"
    nombre = (e.nombre_estudiante or "____").strip()
    antes = (
        f"El {programa.comite} recomienda al Consejo de Facultad de Ciencias Exactas "
        "y Naturales "
    )
    despues = f" la solicitud de {objeto} {al} {nombre}."
    return antes, sentido, despues


def _tabla_asignaturas(doc: DocumentoDocx, item: CasoDocumento) -> None:
    asignaturas = item.extraccion.asignaturas
    if not asignaturas:
        return
    tabla = doc.add_table(rows=1, cols=4)
    tabla.style = "Table Grid" if "Table Grid" in [s.name for s in doc.styles] else None
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    for celda, titulo in zip(
        tabla.rows[0].cells,
        ("Trámite", "Código", "Asignatura", "Créditos"),
        strict=True,
    ):
        celda.text = ""
        r = celda.paragraphs[0].add_run(titulo)
        r.bold = True
        r.font.size = Pt(9)
        _sombrear(celda, "E7E6E6")
    etiquetas = {
        "inscribir": "Inscripción",
        "cancelar": "Cancelación",
        "apertura": "Apertura",
    }
    for asig in asignaturas:
        fila = tabla.add_row().cells
        valores = (
            etiquetas[asig.accion],
            asig.codigo or "",
            asig.nombre,
            str(asig.creditos) if asig.creditos is not None else "",
        )
        for celda, valor in zip(fila, valores, strict=True):
            celda.text = ""
            r = celda.paragraphs[0].add_run(limpiar(valor))
            r.font.size = Pt(9)
    _bordes_tabla(tabla)
    _parrafo(doc, despues=4)


def _bordes_tabla(tabla: object) -> None:
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    tbl_pr = tabla._tbl.tblPr  # type: ignore[attr-defined]
    bordes = etree.SubElement(tbl_pr, f"{w}tblBorders")
    for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = etree.SubElement(bordes, f"{w}{lado}")
        b.set(f"{w}val", "single")
        b.set(f"{w}sz", "4")
        b.set(f"{w}color", "808080")


def _normas(doc: DocumentoDocx, normas: list[NormaCitada], borrador: bool) -> None:
    if not normas:
        return
    _parrafo(doc, "Basados en la normativa:", despues=4)
    for norma in normas:
        p = _parrafo(doc, sangria_cm=1.25, despues=2)
        _run(p, f"{norma.norma}, {norma.articulo}", negrita=True, cursiva=True, tam=9.5)
        for k, linea in enumerate(norma.texto.split("\n")):
            texto = linea
            if k == 0:
                texto = "“" + texto
            if k == len(norma.texto.split("\n")) - 1:
                texto += "”"
            _parrafo(doc, texto, cursiva=True, tam=9.5, sangria_cm=1.25, despues=2)
        if borrador and not norma.verificada:
            p = _parrafo(doc, sangria_cm=1.25, despues=4)
            r = p.add_run(
                "(Texto transcrito de un acta anterior; verificar contra la norma.)"
            )
            r.font.size = Pt(8)
            r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    _parrafo(doc, despues=6)


def _caso(
    doc: DocumentoDocx,
    datos: DatosOficio,
    item: CasoDocumento,
    numero: str,
    periodo: str,
) -> None:
    e = item.extraccion
    identificado = (
        "identificado" if e.tratamiento == "El estudiante" else "identificada"
    )
    p = _parrafo(doc, despues=6)
    _run(p, f"{numero} ", negrita=True)
    _run(p, f"{e.tratamiento} ")
    _run(p, (e.nombre_estudiante or "____").upper(), negrita=True)
    _run(p, f" {identificado} con DNI ")
    _run(p, e.documento or "____", negrita=True)
    _run(
        p,
        f" efectúa la siguiente solicitud a través del correo electrónico el día "
        f"{fecha_larga(e.fecha_solicitud)}, así:",
    )
    _cita(doc, item.cuerpo_correo)

    _parrafo(doc, "ANÁLISIS:", negrita=True, despues=2, alinear=WD_ALIGN_PARAGRAPH.LEFT)
    for vineta in _bullets_analisis(item, periodo):
        _vineta(doc, vineta)
    _parrafo(doc, despues=4)

    for ruta in item.imagenes:
        try:
            doc.add_picture(imagen_reducida(ruta), width=Cm(14))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception:
            _parrafo(doc, f"[No se pudo insertar la imagen {ruta.name}]", cursiva=True)

    antes, sentido, despues = texto_recomendacion(datos.programa, item)
    p = _parrafo(doc, despues=8)
    _run(p, "RECOMENDACIÓN: ", negrita=True)
    _run(p, antes)
    r = p.add_run(sentido.upper())
    r.bold = True
    r.font.size = Pt(10)
    if item.caso.sentido == Sentido.PENDIENTE:
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    _run(p, despues)

    _tabla_asignaturas(doc, item)
    _normas(doc, normas_para(e.tipos, item.caso.programa), datos.borrador)


def _cierre(doc: DocumentoDocx, datos: DatosOficio) -> None:
    _parrafo(doc, "Agradecemos su valiosa gestión.", despues=10)
    _parrafo(doc, "Atentamente,", despues=36)
    p = _parrafo(doc, alinear=WD_ALIGN_PARAGRAPH.LEFT, despues=0)
    r = p.add_run("[FIRMA — se agrega al firmar]" if datos.borrador else "")
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    _parrafo(
        doc,
        "NOMBRE DEL FIRMANTE",
        negrita=True,
        alinear=WD_ALIGN_PARAGRAPH.LEFT,
        despues=0,
    )
    _parrafo(doc, "Cargo", alinear=WD_ALIGN_PARAGRAPH.LEFT, despues=0)
    if datos.programa.correo:
        _parrafo(doc, datos.programa.correo, alinear=WD_ALIGN_PARAGRAPH.LEFT, despues=0)


def construir_oficio(datos: DatosOficio, periodo: str) -> bytes:
    doc = Document(str(PLANTILLA))
    _reemplazar_marcadores(
        doc,
        {
            "ENCABEZADO": datos.programa.encabezado,
            "CORREO": datos.programa.correo or "",
            "EXTENSION": datos.programa.extension or "",
            "ELABORO": datos.elaboro,
        },
    )
    # El párrafo vacío que trae la plantilla se elimina.
    if doc.paragraphs and not doc.paragraphs[0].text:
        primero = doc.paragraphs[0]._element
        primero.getparent().remove(primero)

    _encabezado_oficio(doc, datos)
    secciones: OrderedDict[str, list[CasoDocumento]] = OrderedDict()
    for item in datos.casos:
        secciones.setdefault(titulo_seccion(item.extraccion), []).append(item)
    for n, (titulo, items) in enumerate(secciones.items(), start=1):
        _parrafo(
            doc,
            f"{n}. {titulo}",
            negrita=True,
            subrayado=True,
            alinear=WD_ALIGN_PARAGRAPH.LEFT,
            despues=8,
        )
        for m, item in enumerate(items, start=1):
            _caso(doc, datos, item, f"{n}.{m}", periodo)
    _cierre(doc, datos)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
