from __future__ import annotations

from datetime import date

import pytest

from app.servicios.calidad.plan import (
    Estado,
    calcular_estado,
    proxima_a_vencer,
    proximo_corte,
)
from app.servicios.calidad.plantilla import Accion, Corte, Objetivo, Plan
from tests.calidad.conftest import ALFA, BETA, HOY, leer


def accion(**campos: object) -> Accion:
    base: dict[str, object] = {"codigo": "1.1", "descripcion": "Acción de prueba"}
    base.update(campos)
    return Accion.model_validate(base)


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"avance": 40, "fecha_fin": date(2026, 10, 27)}, Estado.VENCIDA),
        ({"avance": 99.9, "fecha_fin": date(2026, 1, 1)}, Estado.VENCIDA),
        ({"avance": 40, "fecha_fin": date(2026, 10, 28)}, Estado.EN_CURSO),  # vence hoy
        ({"avance": 100, "fecha_fin": date(2026, 1, 1)}, Estado.CUMPLIDA),
        ({"avance": None, "fecha_fin": None}, Estado.EN_CURSO),
        ({"avance": 0, "fecha_inicio": date(2027, 2, 1)}, Estado.POR_INICIAR),
        # «NO FUNCIONÓ» gana sobre el % y las fechas.
        ({"avance": 100, "marcas": ["NO FUNCIONÓ"]}, Estado.NO_FUNCIONO),
    ],
)
def test_estado_con_fecha_fija(campos: dict[str, object], esperado: Estado) -> None:
    assert calcular_estado(accion(**campos), HOY) == esperado


def test_proxima_a_vencer_en_cuatro_semanas() -> None:
    assert proxima_a_vencer(accion(avance=10, fecha_fin=date(2026, 11, 25)), HOY, 28)
    assert not proxima_a_vencer(
        accion(avance=10, fecha_fin=date(2026, 11, 26)), HOY, 28
    )
    assert not proxima_a_vencer(
        accion(avance=100, fecha_fin=date(2026, 11, 1)), HOY, 28
    )


def test_estados_de_las_plantillas_ficticias() -> None:
    alfa = {a.codigo: calcular_estado(a, HOY) for a in leer(ALFA).acciones}
    assert alfa == {
        "1.1.1": Estado.EN_CURSO, "1.1.2": Estado.VENCIDA, "1.1.3": Estado.EN_CURSO,
        "1.2.1": Estado.CUMPLIDA, "1.2.2": Estado.CUMPLIDA, "2.1.1": Estado.VENCIDA,
        "2.1.2": Estado.POR_INICIAR,
    }  # fmt: skip
    beta = {a.codigo: calcular_estado(a, HOY) for a in leer(BETA).acciones}
    assert beta == {
        "1.1": Estado.NO_FUNCIONO, "1.2": Estado.VENCIDA, "2.1": Estado.EN_CURSO,
        "2.2": Estado.POR_INICIAR, "2.3": Estado.CUMPLIDA,
    }  # fmt: skip


def test_proximo_corte() -> None:
    def plan(*fechas: date) -> Plan:
        cortes = [Corte(rotulo=f.isoformat(), fecha=f) for f in fechas]
        return Plan(
            programa="P",
            objetivos=[
                Objetivo(codigo="1", texto="", acciones=[accion(cortes=cortes)])
            ],
        )

    assert proximo_corte(plan(date(2026, 12, 16)), HOY) == (date(2026, 12, 16), False)
    # Todos pasaron: el último más seis meses, marcado como estimado.
    assert proximo_corte(plan(date(2026, 5, 21)), HOY) == (date(2026, 11, 21), True)
    assert proximo_corte(plan(date(2025, 12, 3)), HOY) == (date(2026, 12, 3), True)
    assert proximo_corte(plan(), HOY) is None
