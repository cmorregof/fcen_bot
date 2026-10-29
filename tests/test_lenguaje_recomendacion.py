"""El comité asesor recomienda; quien aprueba o niega es el Consejo (§5.2)."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from docx import Document

from app.prompts.extraccion import SISTEMA_CORRECCION, SISTEMA_EXTRACCION
from app.schemas.caso import Sentido
from app.services import bot, ficha
from app.services.documento import construir_acta, construir_oficio
from tests.test_documento import _datos

RAIZ = Path(__file__).resolve().parents[1]

# El comité (o el «comité asesor») como sujeto de aprobar, negar o decidir.
_PROHIBIDO = re.compile(
    r"(comit[ée]\s+(asesor\s+)?(aprueba|aprobar[áa]|aprob[óo]|niega|neg[óo]|decide|decidi[óo]))"
    r"|((aprobado|negado|decidido)\s+por\s+el\s+comit[ée])"
    r"|(el\s+comit[ée]\s+decide)",
    re.IGNORECASE,
)


def _textos_docx(contenido: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        partes = [
            re.sub(r"<[^>]+>", "", z.read(n).decode("utf-8"))
            for n in z.namelist()
            if n.startswith("word/") and n.endswith(".xml")
        ]
    return " ".join(partes)


def _sin_prohibidos(texto: str) -> None:
    assert not _PROHIBIDO.search(texto), _PROHIBIDO.search(texto)


def test_documentos_generados_no_dicen_que_el_comite_aprueba() -> None:
    for sentido in Sentido:
        datos = _datos(sentido)
        for contenido in (
            construir_oficio(datos, "2026-2S"),
            construir_acta(datos, "2026-2S"),
        ):
            _sin_prohibidos(_textos_docx(contenido))


def test_plantilla_no_dice_que_el_comite_aprueba() -> None:
    plantilla = RAIZ / "app" / "templates" / "oficio_base.docx"
    _sin_prohibidos(" ".join(p.text for p in Document(str(plantilla)).paragraphs))
    _sin_prohibidos(_textos_docx(plantilla.read_bytes()))


def test_textos_del_bot_no_dicen_que_el_comite_aprueba() -> None:
    _sin_prohibidos(bot.AYUDA)
    _sin_prohibidos(SISTEMA_EXTRACCION)
    _sin_prohibidos(SISTEMA_CORRECCION)
    # Fuente de los demás mensajes del bot y de los botones.
    for archivo in ("app/services/bot.py", "app/services/ficha.py"):
        _sin_prohibidos((RAIZ / archivo).read_text(encoding="utf-8"))


def test_botones_recomiendan() -> None:
    textos = [b["text"] for fila in ficha.botones_ficha(1) for b in fila]
    assert any("Recomendar aprobar" in t for t in textos)
    assert any("Recomendar no aprobar" in t for t in textos)
    assert not any(t.strip("✅❌ ") in ("Aprobar", "No aprobar") for t in textos)


def test_el_oficio_si_dice_que_el_comite_recomienda() -> None:
    texto = _textos_docx(construir_oficio(_datos(Sentido.APROBAR), "2026-2S"))
    assert "El Comité Asesor recomienda al Consejo de Facultad" in texto
