"""Historia académica en el análisis del caso: créditos por tipología como en el
SIA, P.A.P.A. (y P.A.) y estado de la historia. Datos inventados."""

from __future__ import annotations

import io
from datetime import date
from types import SimpleNamespace
from typing import Any

from docx import Document
from docx.enum.text import WD_COLOR_INDEX

from app.core.programas import PROGRAMAS
from app.integrations.claude import ClaudeEstructurador, esquema_plano
from app.schemas.caso import (
    Caso,
    DatosSIA,
    EstadoCaso,
    ExtraccionCaso,
    FilaCreditos,
    Sentido,
)
from app.services.documento import (
    VERIFICAR_SIA,
    CasoDocumento,
    DatosOficio,
    construir_acta,
    construir_oficio,
)
from app.services.reglas import analizar
from tests.conftest import extraccion_ejemplo, filas_sia


def _datos(e: ExtraccionCaso, programa: str = "ing_fisica") -> DatosOficio:
    prog = PROGRAMAS[programa]
    caso = Caso(
        id=1,
        chat_id=1,
        direccion=prog.direccion,
        programa=programa,
        estado=EstadoCaso.LISTO,
        sentido=Sentido.APROBAR,
        texto="x",
        extraccion=e,
    )
    item = CasoDocumento(
        caso,
        e,
        analizar(e, prog, periodo_inicio=None, hay_imagenes=True),
        "Buenos días,\n\nSolicito la cancelación.\n\nPersona Ficticia Uno",
    )
    return DatosOficio(
        programa=prog,
        fecha=date(2026, 11, 10),
        casos=[item],
        elaboro="AB",
        miembros=prog.miembros,
    )


def _con_sia(**cambios: Any) -> ExtraccionCaso:
    e = extraccion_ejemplo()
    assert e.sia is not None
    return e.model_copy(update={"sia": e.sia.model_copy(update=cambios)})


def _doc(contenido: bytes) -> Any:
    return Document(io.BytesIO(contenido))


def _tabla_creditos(doc: Any) -> Any:
    [tabla] = [t for t in doc.tables if t.rows[0].cells[0].text == "Tipología"]
    return tabla


def _vinetas(doc: Any) -> list[Any]:
    return [p for p in doc.paragraphs if p.text.startswith("•\t")]


def _amarillos(parrafo: Any) -> list[str]:
    return [
        r.text for r in parrafo.runs if r.font.highlight_color == WD_COLOR_INDEX.YELLOW
    ]


def test_acta_trae_el_desglose_el_papa_y_el_estado() -> None:
    e = _con_sia(estado_historia="ACTIVA", papa=4.5, promedio_academico=4.25)
    doc = _doc(construir_acta(_datos(e), "2026-2S"))
    textos = [p.text for p in doc.paragraphs]

    assert "•\tEstado de la historia académica: ACTIVA" in textos
    assert "•\tP.A.P.A. 4,5; P.A. 4,25; porcentaje de avance 56,5 %" in textos
    assert "Créditos por tipología (resumen de créditos del SIA):" in textos

    tabla = _tabla_creditos(doc)
    assert [c.text for c in tabla.rows[0].cells] == [
        "Tipología",
        "Exigidos",
        "Aprobados",
        "Pendientes",
        "Inscritos",
        "Cursados",
    ]
    # Mismas filas, nombres y orden que el SIA, incluidas las de totales.
    assert [f.cells[0].text for f in tabla.rows[1:]] == [
        f.tipologia for f in filas_sia()
    ]
    fund = tabla.rows[2].cells
    assert [c.text for c in fund] == ["FUND. OBLIGATORIA", "66", "63", "3", "4", "63"]
    # El análisis va antes de la tabla y la tabla antes de los conceptos.
    assert textos.index("ANÁLISIS:") < textos.index(
        "Créditos por tipología (resumen de créditos del SIA):"
    )


def test_el_oficio_no_lleva_la_tabla_pero_si_el_estado() -> None:
    e = _con_sia(estado_historia="BLOQUEADA")
    doc = _doc(construir_oficio(_datos(e), "2026-2S"))
    textos = [p.text for p in doc.paragraphs]
    assert "•\tEstado de la historia académica: BLOQUEADA" in textos
    assert not [t for t in doc.tables if t.rows[0].cells[0].text == "Tipología"]


def test_lo_que_no_se_leyo_queda_en_amarillo() -> None:
    filas = filas_sia()
    # Se leyó la columna de aprobados salvo en LIBRE ELECCIÓN; no hay cursados.
    filas = [f.model_copy(update={"cursados": None}) for f in filas]
    filas[4] = filas[4].model_copy(update={"aprobados": None})
    e = _con_sia(estado_historia=None, papa=None, resumen_creditos=filas)
    doc = _doc(construir_acta(_datos(e), "2026-2S"))

    vinetas = {p.text: p for p in _vinetas(doc)}
    estado = vinetas[f"•\tEstado de la historia académica: {VERIFICAR_SIA}"]
    assert _amarillos(estado) == [VERIFICAR_SIA]
    papa = next(p for t, p in vinetas.items() if t.startswith("•\tP.A.P.A."))
    assert papa.text == f"•\tP.A.P.A. {VERIFICAR_SIA}; porcentaje de avance 56,5 %"
    assert _amarillos(papa) == [VERIFICAR_SIA]

    tabla = _tabla_creditos(doc)
    # La columna que no trae el pantallazo no sale.
    assert "Cursados" not in [c.text for c in tabla.rows[0].cells]
    libre = tabla.rows[5].cells
    assert libre[0].text == "LIBRE ELECCIÓN"
    assert libre[2].text == VERIFICAR_SIA
    assert _amarillos(libre[2].paragraphs[0]) == [VERIFICAR_SIA]
    assert 'w:fill="FFFF00"' in libre[2]._tc.xml


def test_sin_resumen_de_creditos_lo_pide_en_amarillo() -> None:
    e = _con_sia(resumen_creditos=[])
    doc = _doc(construir_acta(_datos(e), "2026-2S"))
    [vineta] = [p for p in _vinetas(doc) if p.text.startswith("•\tCréditos por")]
    assert _amarillos(vineta) == [VERIFICAR_SIA]
    assert not [t for t in doc.tables if t.rows[0].cells[0].text == "Tipología"]


def test_posgrado_conserva_sus_tipologias() -> None:
    filas = [
        FilaCreditos(tipologia="ACTIVIDAD ACADÉMICA", exigidos=10, aprobados=4),
        FilaCreditos(tipologia="TESIS DE MAESTRÍA", exigidos=40, aprobados=0),
        FilaCreditos(tipologia="TOTAL", exigidos=50, aprobados=4),
    ]
    e = _con_sia(resumen_creditos=filas, estado_historia="ACTIVA")
    doc = _doc(construir_acta(_datos(e), "2026-2S"))
    tabla = _tabla_creditos(doc)
    assert [c.text for c in tabla.rows[0].cells] == [
        "Tipología",
        "Exigidos",
        "Aprobados",
    ]
    assert [f.cells[0].text for f in tabla.rows[1:]] == [
        "ACTIVIDAD ACADÉMICA",
        "TESIS DE MAESTRÍA",
        "TOTAL",
    ]


def test_caso_extraido_antes_sigue_saliendo() -> None:
    """Un caso guardado sin los campos nuevos se lee y se arma igual."""
    viejo = extraccion_ejemplo().model_dump(mode="json")
    assert viejo["sia"] is not None
    del viejo["sia"]["estado_historia"]
    del viejo["sia"]["promedio_academico"]
    e = ExtraccionCaso.model_validate(viejo)
    doc = _doc(construir_acta(_datos(e), "2026-2S"))
    textos = [p.text for p in doc.paragraphs]
    assert "•\tP.A.P.A. 4,5; porcentaje de avance 56,5 %" in textos
    assert _tabla_creditos(doc) is not None


def test_sin_pantallazos_no_hay_marcadores_del_sia() -> None:
    e = extraccion_ejemplo(sia=None)
    doc = _doc(construir_acta(_datos(e), "2026-2S"))
    assert VERIFICAR_SIA not in "\n".join(p.text for p in doc.paragraphs)


def test_el_esquema_de_la_herramienta_pide_los_campos() -> None:
    sia = esquema_plano(ExtraccionCaso)["properties"]["sia"]
    props = sia.get("properties") or next(
        o["properties"] for o in sia["anyOf"] if "properties" in o
    )
    assert {"estado_historia", "papa", "promedio_academico", "resumen_creditos"} <= set(
        props
    )


async def test_extraccion_con_json_simulado_del_modelo() -> None:
    """El modelo devuelve lo que ve; el acta copia los números sin cambiarlos."""
    entrada = {
        "nombre_estudiante": "Persona Ficticia Dos",
        "documento": "1000000002",
        "tipos": ["cancelacion"],
        "objeto_solicitud": "cancelación de la asignatura 1000001 Cálculo",
        "sia": {
            "plan_codigo": "4030",
            "plan_nombre": "INGENIERIA FISICA",
            "periodo": "2026-2S",
            "papa": 3.87,
            "promedio_academico": 3.9,
            "estado_historia": "Activa",
            "resumen_creditos": [
                {"tipologia": "FUND. OBLIGATORIA", "exigidos": 60, "aprobados": 30},
                {"tipologia": "FUND. OPTATIVA", "exigidos": 10, "aprobados": 5},
                {"tipologia": "TOTAL", "exigidos": 70, "aprobados": 35},
            ],
        },
    }
    est = ClaudeEstructurador("x", 1)

    async def crear(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            content=[SimpleNamespace(type="tool_use", input=entrada)],
        )

    est._client.messages.create = crear  # type: ignore[method-assign]
    r = await est.extraer(
        sistema="s",
        texto="t",
        imagenes=[],
        modelo_salida=ExtraccionCaso,
        nombre_herramienta="registrar_caso",
        modelo="m",
        max_tokens=10,
    )
    e = r.objeto
    assert isinstance(e, ExtraccionCaso) and isinstance(e.sia, DatosSIA)
    assert e.sia.estado_historia == "Activa"

    doc = _doc(construir_acta(_datos(e), "2026-2S"))
    textos = [p.text for p in doc.paragraphs]
    assert "•\tEstado de la historia académica: Activa" in textos
    assert "•\tP.A.P.A. 3,87; P.A. 3,9" in textos
    tabla = _tabla_creditos(doc)
    assert [c.text for c in tabla.rows[2].cells] == ["FUND. OPTATIVA", "10", "5"]
