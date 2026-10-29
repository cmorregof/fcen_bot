"""La cita del oficio es una subcadena exacta de lo que escribió el estudiante.
Datos ficticios."""

from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_COLOR_INDEX

from app.core.programas import PROGRAMAS
from app.schemas.caso import Sentido
from app.services.documento import construir_acta, construir_oficio
from app.services.extraccion import cita_del_caso
from app.services.reglas import analizar, cita_literal
from tests.conftest import extraccion_ejemplo
from tests.test_documento import _datos

CORREO = (
    "De: Persona Ficticia Uno\n"
    "Buenos días,\n"
    "Solicito la cancelación de Termodinámica porque no alcanzo\n"
    "a cumplir con la carga del semestre.\n"
    "Persona Ficticia Uno\n"
)
CITA_BUENA = "porque no alcanzo\na cumplir con la carga del semestre."
CITA_MALA = "porque no alcanzo a cumplir con la carga académica del semestre."


def _alertas(cita: str | None, texto: str | None = CORREO, **cambios: object):
    e = extraccion_ejemplo(cita_textual=cita, **cambios)
    return analizar(
        e,
        PROGRAMAS["ing_fisica"],
        periodo_inicio=None,
        hay_imagenes=True,
        texto_original=texto,
    ).alertas


def test_subcadena_exacta() -> None:
    assert cita_literal(CITA_BUENA, CORREO)
    assert cita_literal("  " + CITA_BUENA + "\n", CORREO)  # extremos
    assert cita_literal(CITA_BUENA, CORREO.replace("\n", "\r\n"))  # Windows
    assert not cita_literal(CITA_MALA, CORREO)
    # Un solo carácter distinto basta: no se normaliza nada más.
    assert not cita_literal(CITA_BUENA.replace("semestre", "Semestre"), CORREO)
    assert not cita_literal(CITA_BUENA.replace("\n", " "), CORREO)
    # Con los números de línea que ve el modelo, tampoco.
    assert not cita_literal("004| a cumplir con la carga del semestre.", CORREO)


def test_cita_desde_la_transcripcion_del_correo_en_imagen() -> None:
    transcrito = "Solicito el permiso porque viajo a un congreso ficticio."
    assert cita_literal("viajo a un congreso ficticio.", "", transcrito)
    assert not cita_literal("viajo a un congreso.", "", transcrito)


def test_cita_inexacta_es_error() -> None:
    errores = [a for a in _alertas(CITA_MALA) if a.nivel == "error"]
    assert len(errores) == 1
    assert "no aparece tal cual" in errores[0].mensaje
    assert "amarillo" in errores[0].mensaje


def test_cita_exacta_no_alerta() -> None:
    assert not any("cita" in a.mensaje for a in _alertas(CITA_BUENA))


def test_sin_texto_original_no_se_verifica() -> None:
    assert not any("cita" in a.mensaje for a in _alertas(CITA_MALA, texto=None))


def test_cita_del_caso() -> None:
    e = extraccion_ejemplo(cita_textual=CITA_BUENA)
    assert cita_del_caso(CORREO, e) == (CITA_BUENA, True)
    e = extraccion_ejemplo(cita_textual=CITA_MALA)
    # No se arregla en silencio: la cita sale tal como vino, marcada.
    assert cita_del_caso(CORREO, e) == (CITA_MALA, False)
    # Sin fragmento, el cuerpo recortado del texto pegado (líneas 2 a 3).
    e = extraccion_ejemplo(cita_textual=None)
    assert cita_del_caso(CORREO, e) == (
        "Buenos días,\nSolicito la cancelación de Termodinámica porque no alcanzo",
        True,
    )


def _runs_de_la_cita(contenido: bytes, cita: str):
    doc = Document(io.BytesIO(contenido))
    return [r for p in doc.paragraphs for r in p.runs if r.text and r.text in cita]


def _datos_con_cita(cita: str, verificada: bool):
    datos = _datos(Sentido.APROBAR)
    item = datos.casos[0]
    item.cuerpo_correo = cita
    item.cita_verificada = verificada
    return datos


def test_cita_no_verificada_sale_en_amarillo() -> None:
    datos = _datos_con_cita(CITA_MALA, verificada=False)
    for contenido in (
        construir_oficio(datos, "2026-2S"),
        construir_acta(datos, "2026-2S"),
    ):
        runs = _runs_de_la_cita(contenido, CITA_MALA + "”.")
        assert runs
        assert all(r.font.highlight_color == WD_COLOR_INDEX.YELLOW for r in runs)


def test_cita_verificada_no_se_resalta() -> None:
    datos = _datos_con_cita(CITA_BUENA, verificada=True)
    runs = _runs_de_la_cita(construir_oficio(datos, "2026-2S"), CITA_BUENA + "”.")
    assert runs
    assert not any(r.font.highlight_color == WD_COLOR_INDEX.YELLOW for r in runs)
