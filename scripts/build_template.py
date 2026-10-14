"""Genera app/templates/oficio_base.docx a partir de un oficio real.

Uso:
    uv run python scripts/build_template.py "ruta/al/oficio.docx"

Del oficio se conserva el membrete (encabezados, pies, estilos, numeración) y
se elimina todo el cuerpo, las imágenes del cuerpo y las fuentes embebidas.
Los textos propios del programa se reemplazan por marcadores:
{{ENCABEZADO}}, {{CORREO}}, {{EXTENSION}} y {{ELABORO}}.

El oficio original tiene datos de estudiantes; la plantilla resultante no
conserva ningún texto del cuerpo. El script lo comprueba antes de guardar.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W}

REEMPLAZOS = {
    "Programa Curricular de Ciencias de la Computación": "{{ENCABEZADO}}",
    "carcomp_man@unal.edu.co": "{{CORREO}}",
    "ABCJ": "{{ELABORO}}",
    "(+57 6) 8879300 Ext. 55634 ": "(+57 6) 8879300 Ext. {{EXTENSION}} ",
}

DESTINO = Path(__file__).resolve().parents[1] / "app" / "templates" / "oficio_base.docx"


def _limpiar_documento(xml: bytes) -> bytes:
    raiz = etree.fromstring(xml)
    body = raiz.find("w:body", NS)
    assert body is not None
    sect = body.find("w:sectPr", NS)
    for hijo in list(body):
        if hijo is not sect:
            body.remove(hijo)
    # Párrafo vacío inicial: python-docx agrega el contenido después.
    etree.SubElement(body, f"{{{W}}}p")
    if sect is not None:
        body.remove(sect)
        body.append(sect)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _reemplazar_textos(xml: bytes) -> bytes:
    raiz = etree.fromstring(xml)
    for t in raiz.iter(f"{{{W}}}t"):
        if t.text in REEMPLAZOS:
            t.text = REEMPLAZOS[t.text]
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _quitar_rels(xml: bytes, tipos: tuple[str, ...]) -> bytes:
    raiz = etree.fromstring(xml)
    for rel in list(raiz):
        tipo = rel.get("Type", "")
        if any(tipo.endswith("/" + t) for t in tipos):
            raiz.remove(rel)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _sin_fuentes_embebidas(xml: bytes) -> bytes:
    raiz = etree.fromstring(xml)
    for tag in ("embedRegular", "embedBold", "embedItalic", "embedBoldItalic"):
        for nodo in raiz.iter(f"{{{W}}}{tag}"):
            padre = nodo.getparent()
            assert padre is not None
            padre.remove(nodo)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _settings(xml: bytes) -> bytes:
    raiz = etree.fromstring(xml)
    for tag in ("embedTrueTypeFonts", "saveSubsetFonts", "rsids"):
        for nodo in list(raiz.iter(f"{{{W}}}{tag}")):
            padre = nodo.getparent()
            assert padre is not None
            padre.remove(nodo)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _core(xml: bytes) -> bytes:
    texto = xml.decode("utf-8")
    texto = re.sub(
        r"<dc:creator>.*?</dc:creator>", "<dc:creator>fcen_bot</dc:creator>", texto
    )
    texto = re.sub(
        r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>",
        "<cp:lastModifiedBy>fcen_bot</cp:lastModifiedBy>",
        texto,
    )
    texto = re.sub(r"<cp:lastPrinted>.*?</cp:lastPrinted>", "", texto)
    return texto.encode("utf-8")


def construir(origen: Path, destino: Path = DESTINO) -> None:
    with zipfile.ZipFile(origen) as zin:
        partes = {n: zin.read(n) for n in zin.namelist()}

    partes["word/document.xml"] = _limpiar_documento(partes["word/document.xml"])
    partes["word/_rels/document.xml.rels"] = _quitar_rels(
        partes["word/_rels/document.xml.rels"], ("image", "hyperlink")
    )
    for nombre in list(partes):
        if re.fullmatch(r"word/(header|footer)\d+\.xml", nombre):
            partes[nombre] = _reemplazar_textos(partes[nombre])
    partes["word/fontTable.xml"] = _sin_fuentes_embebidas(partes["word/fontTable.xml"])
    partes["word/settings.xml"] = _settings(partes["word/settings.xml"])
    if "docProps/core.xml" in partes:
        partes["docProps/core.xml"] = _core(partes["docProps/core.xml"])
    for nombre in list(partes):
        if (
            nombre.startswith("word/fonts/")
            or nombre == "word/_rels/fontTable.xml.rels"
        ):
            del partes[nombre]

    # Medios: solo los que sigan referenciados desde algún .rels
    referenciados: set[str] = set()
    for nombre, contenido in partes.items():
        if nombre.endswith(".rels"):
            for target in re.findall(rb'Target="media/([^"]+)"', contenido):
                referenciados.add("word/media/" + target.decode())
    for nombre in list(partes):
        if nombre.startswith("word/media/") and nombre not in referenciados:
            del partes[nombre]

    # Comprobación: ningún texto del cuerpo original sobrevive.
    cuerpo = partes["word/document.xml"]
    textos = re.findall(rb"<w:t[^>]*>([^<]+)</w:t>", cuerpo)
    if textos:
        raise SystemExit(f"La plantilla todavía tiene texto en el cuerpo: {textos[:5]}")
    for nombre, contenido in partes.items():
        if nombre.endswith(".xml") and re.search(rb"\b\d{8,10}\b", contenido):
            sospechosos = re.findall(
                rb"<w:t[^>]*>([^<]*\d{8,10}[^<]*)</w:t>", contenido
            )
            if sospechosos:
                raise SystemExit(
                    f"{nombre} tiene números que parecen documentos: {sospechosos}"
                )

    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zout:
        orden = ["[Content_Types].xml"] + [
            n for n in partes if n != "[Content_Types].xml"
        ]
        for nombre in orden:
            zout.writestr(nombre, partes[nombre])
    print(f"Plantilla escrita en {destino} ({destino.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    construir(Path(sys.argv[1]))
