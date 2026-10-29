"""En el oficio la recomendación de cada caso se lee primero (pedido del
Consejo de Facultad, 28-oct-2026). El acta conserva el orden de la sesión."""

from __future__ import annotations

import io

from docx import Document

from app.schemas.caso import Concepto, Sentido
from app.services.documento import construir_acta, construir_oficio
from tests.test_documento import _datos


def _parrafos(contenido: bytes) -> list[str]:
    return [p.text for p in Document(io.BytesIO(contenido)).paragraphs]


def _indice(parrafos: list[str], inicio: str) -> int:
    return next(i for i, p in enumerate(parrafos) if p.startswith(inicio))


def test_oficio_empieza_cada_caso_por_la_recomendacion() -> None:
    parrafos = _parrafos(construir_oficio(_datos(Sentido.APROBAR), "2026-2S"))
    titulo = _indice(parrafos, "SOLICITUD DE CARGA MÍNIMA")
    recomendacion = _indice(parrafos, "2.1 RECOMENDACIÓN:")
    solicitud = _indice(parrafos, "PERSONA FICTICIA UNO identificada")
    analisis = _indice(parrafos, "ANÁLISIS:")
    normas = _indice(parrafos, "Basados en la normativa:")
    assert titulo < recomendacion < solicitud < analisis < normas
    # Entre el título de la sección y la recomendación no hay otro texto.
    assert all(not p.strip() for p in parrafos[titulo + 1 : recomendacion])


def test_oficio_pone_el_cuadro_de_asignaturas_junto_a_la_recomendacion() -> None:
    parrafos = _parrafos(construir_oficio(_datos(Sentido.APROBAR), "2026-2S"))
    recomendacion = _indice(parrafos, "2.1 RECOMENDACIÓN:")
    cuadro = _indice(parrafos, "Cancelar las siguientes asignaturas:")
    solicitud = _indice(parrafos, "PERSONA FICTICIA UNO identificada")
    assert recomendacion < cuadro < solicitud


def test_acta_conserva_el_orden_de_la_sesion() -> None:
    conceptos = [
        Concepto(
            miembro="Profesor Ficticio A", tratamiento="El profesor", texto="Bien."
        )
    ]
    parrafos = _parrafos(construir_acta(_datos(Sentido.APROBAR, conceptos), "2026-2S"))
    solicitud = _indice(parrafos, "2.1 PERSONA FICTICIA UNO identificada")
    analisis = _indice(parrafos, "ANÁLISIS:")
    concepto = _indice(parrafos, "El profesor Profesor Ficticio A expresa")
    recomendacion = _indice(parrafos, "RECOMENDACIÓN:")
    assert solicitud < analisis < concepto < recomendacion


def test_pendiente_sigue_resaltado_al_inicio() -> None:
    parrafos = _parrafos(construir_oficio(_datos(Sentido.PENDIENTE), "2026-2S"))
    assert any(
        p.startswith("2.1 RECOMENDACIÓN:") and "[APROBAR / NO APROBAR]" in p
        for p in parrafos
    )
