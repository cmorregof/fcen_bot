from __future__ import annotations

from datetime import date

import pytest

from app.servicios.calidad.plan import Estado, calcular_estado

HOY = date(2026, 10, 28)


@pytest.mark.parametrize(
    ("limite", "cumplida", "esperado"),
    [
        (date(2026, 10, 27), False, Estado.VENCIDA),
        (date(2026, 1, 1), False, Estado.VENCIDA),
        (date(2026, 10, 28), False, Estado.PROXIMA),  # vence hoy: aún no vencida
        (date(2026, 11, 25), False, Estado.PROXIMA),  # exactamente 28 días
        (date(2026, 11, 26), False, Estado.PENDIENTE),  # 29 días
        (date(2027, 6, 1), False, Estado.PENDIENTE),
        (date(2026, 1, 1), True, Estado.CUMPLIDA),  # la evidencia gana sobre el atraso
        (date(2027, 6, 1), True, Estado.CUMPLIDA),
    ],
)
def test_estados_con_fecha_fija(limite: date, cumplida: bool, esperado: Estado) -> None:
    assert calcular_estado(limite, cumplida, HOY, dias_proxima=28) == esperado
