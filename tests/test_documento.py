from __future__ import annotations

import io
import zipfile
from datetime import date

from docx import Document

from app.core.programas import PROGRAMAS
from app.schemas.caso import Caso, EstadoCaso, Sentido
from app.services.documento import (
    CasoDocumento,
    DatosOficio,
    construir_oficio,
    creditos_texto,
    en_letras,
    fecha_larga,
    titulo_seccion,
)
from app.services.reglas import analizar
from tests.conftest import extraccion_ejemplo


def _oficio(sentido: Sentido) -> bytes:
    programa = PROGRAMAS["ing_fisica"]
    e = extraccion_ejemplo()
    caso = Caso(
        id=1,
        chat_id=1,
        direccion="ciencias_naturales",
        programa="ing_fisica",
        estado=EstadoCaso.LISTO,
        sentido=sentido,
        texto="x",
        extraccion=e,
    )
    item = CasoDocumento(
        caso,
        e,
        analizar(e, programa, periodo_inicio=None, hay_imagenes=False),
        "Buenos días,\n\nSolicito la cancelación.\n\nPersona Ficticia Uno",
    )
    datos = DatosOficio(
        programa=programa, fecha=date(2026, 10, 13), casos=[item], elaboro="AB"
    )
    return construir_oficio(datos, "2026-2S")


def _texto_completo(docx: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        return " ".join(
            z.read(n).decode("utf-8")
            for n in z.namelist()
            if n.startswith("word/") and n.endswith(".xml")
        )


def test_marcadores_reemplazados() -> None:
    xml = _texto_completo(_oficio(Sentido.APROBAR))
    assert "{{" not in xml
    assert "Programa Curricular de Ingeniería Física" in xml
    assert "caringfis_man@unal.edu.co" in xml


def test_cuerpo_del_oficio() -> None:
    doc = Document(io.BytesIO(_oficio(Sentido.APROBAR)))
    texto = "\n".join(p.text for p in doc.paragraphs)
    assert "CONSEJO DE FACULTAD" in texto
    assert "SOLICITUD DE CARGA MÍNIMA Y CANCELACIÓN DE ASIGNATURAS" in texto
    assert "2.1 PERSONA FICTICIA UNO identificada con DNI No. 1000000001" in texto
    assert "RECOMENDACIÓN: El Comité Asesor recomienda APROBAR la solicitud" in texto
    assert "tiene inscritos trece créditos (13 créditos)" in texto
    assert "Acuerdo 008 de 2008" in texto
    assert "Cancelación: Termodinámica código 4100849 (4 créditos)" in texto
    estilos = {p.style.name for p in doc.paragraphs if p.style is not None}
    assert {"FCEN Caso", "FCEN Cita", "FCEN Titulo", "FCEN Fecha"} <= estilos


def test_sentido_pendiente_queda_marcado() -> None:
    doc = Document(io.BytesIO(_oficio(Sentido.PENDIENTE)))
    texto = "\n".join(p.text for p in doc.paragraphs)
    assert "[APROBAR / NO APROBAR]" in texto


def test_numeros_en_letras() -> None:
    assert en_letras(1) == "un"
    assert en_letras(13) == "trece"
    assert en_letras(21) == "veintiún"
    assert en_letras(31) == "treinta y un"
    assert en_letras(47) == "cuarenta y siete"
    assert creditos_texto(1) == "un crédito (1 crédito)"


def test_fecha_larga() -> None:
    assert fecha_larga("2026-09-02") == "02 de septiembre de 2026"
    assert fecha_larga(None) == "____"


def test_titulo_seccion() -> None:
    assert (
        titulo_seccion(extraccion_ejemplo())
        == "SOLICITUD DE CARGA MÍNIMA Y CANCELACIÓN DE ASIGNATURAS"
    )


def test_plantilla_sin_datos_personales() -> None:
    from app.services.documento import PLANTILLA

    xml = _texto_completo(PLANTILLA.read_bytes())
    import re

    cuerpo = re.findall(r"<w:t[^>]*>([^<]+)</w:t>", xml)
    assert not any(re.search(r"\d{8,10}", t) for t in cuerpo)
    with zipfile.ZipFile(PLANTILLA) as z:
        assert not any(n.startswith("word/fonts/") for n in z.namelist())
