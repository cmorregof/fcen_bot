"""Encabezado de la plantilla: el logo arriba a la derecha y, debajo, el nombre.

El logo estaba anclado con ajuste de texto «cuadrado», así que el nombre del
programa y de la facultad se corría a su izquierda en vez de quedar debajo.
Este script pone el logo en línea, alineado a la derecha, y el nombre en los
párrafos siguientes. Se aplica sobre app/templates/oficio_base.docx.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from lxml import etree

PLANTILLA = (
    Path(__file__).resolve().parents[1] / "app" / "templates" / "oficio_base.docx"
)
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
W = f"{{{NS['w']}}}"
ANCHO, ALTO = 1400000, 735700  # EMU; la proporción del recorte del logo (1,906)

INLINE = f"""<w:drawing xmlns:w="{NS["w"]}" xmlns:wp="{NS["wp"]}" xmlns:a="{NS["a"]}"
 xmlns:pic="{NS["pic"]}" xmlns:r="{NS["r"]}"><wp:inline distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="{ANCHO}" cy="{ALTO}"/><wp:docPr id="22" name="Logo" descr="Universidad Nacional de Colombia"/>
<wp:cNvGraphicFramePr/><a:graphic><a:graphicData uri="{NS["pic"]}"><pic:pic>
<pic:nvPicPr><pic:cNvPr id="0" name="logo.jpg"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="rId1"/><a:srcRect l="21765"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{ANCHO}" cy="{ALTO}"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>
</wp:inline></w:drawing>"""


def arreglar(xml: bytes) -> bytes:
    raiz = etree.fromstring(xml)
    if raiz.find(".//wp:inline", NS) is not None:
        return xml  # ya está arreglado
    for p in raiz.iter(f"{W}p"):
        if "{{ENCABEZADO}}" not in "".join(p.itertext()):
            continue
        # Párrafo del logo, antes del texto.
        logo = etree.Element(f"{W}p")
        ppr = etree.SubElement(logo, f"{W}pPr")
        sp = etree.SubElement(ppr, f"{W}spacing")
        sp.set(f"{W}after", "0")
        etree.SubElement(ppr, f"{W}jc").set(f"{W}val", "right")
        etree.SubElement(logo, f"{W}r").append(etree.fromstring(INLINE))
        p.addprevious(logo)
        # El texto sin tabuladores ni el ancla vieja.
        for r in list(p.findall(f"{W}r")):
            if r.find(f"{W}drawing") is not None or (
                r.find(f"{W}tab") is not None and r.find(f"{W}t") is None
            ):
                p.remove(r)
            elif r.find(f"{W}tab") is not None:
                r.remove(r.find(f"{W}tab"))
        break
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def main(ruta: Path = PLANTILLA) -> None:
    with zipfile.ZipFile(ruta) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    partes["word/header2.xml"] = arreglar(partes["word/header2.xml"])
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for n, c in partes.items():
            z.writestr(n, c)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else PLANTILLA)
