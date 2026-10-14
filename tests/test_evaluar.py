"""scripts/evaluar.py con un caso ficticio y un estructurador falso."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.integrations.claude import Resultado
from app.schemas.caso import ExtraccionCaso
from app.services import extraccion
from tests.conftest import extraccion_ejemplo, png_bytes

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "evaluar", RAIZ / "scripts" / "evaluar.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["evaluar"] = modulo  # lo necesitan las dataclasses
    spec.loader.exec_module(modulo)
    return modulo


class Falso:
    def __init__(self, salida: ExtraccionCaso) -> None:
        self.salida = salida

    async def extraer(self, **_: Any) -> Resultado:
        return Resultado(self.salida, 3000, 500)


ESPERADO = {
    "nombre_estudiante": "PERSONA FICTICIA UNO",
    "documento": "1000000001",
    "tratamiento": "La estudiante",
    "fecha_solicitud": "2026-09-02",
    "programa": "ing_fisica",
    "tipos_incluye": ["carga_minima"],
    "creditos_inscritos": 13,
    "creditos_tras_solicitud": 9,
    "disciplinares_aprobados": 17,
    "papa": 4.5,
    "porcentaje_avance": 56.5,
    "codigos_asignaturas": ["4100849"],
    "no_debe_contener": ["diagnóstico"],
}


def _caso(raiz: Path, nombre: str, esperado: dict[str, Any]) -> None:
    d = raiz / nombre
    d.mkdir(parents=True)
    (d / "correo.txt").write_text(
        "Persona Ficticia Uno\nBuenas tardes, solicito la cancelación.\nGracias.\n",
        encoding="utf-8",
    )
    (d / "pantallazo_1.png").write_bytes(png_bytes())
    (d / "esperado.json").write_text(
        json.dumps(
            {"id": nombre, "direccion": "ciencias_naturales", "esperado": esperado}
        ),
        encoding="utf-8",
    )


@pytest.fixture
def falso() -> Any:
    f = Falso(extraccion_ejemplo())
    extraccion.set_estructurador(f)  # type: ignore[arg-type]
    yield f
    extraccion.set_estructurador(None)


async def test_todo_coincide(tmp_path: Path, falso: Falso) -> None:
    _caso(tmp_path, "caso_01", ESPERADO)
    evaluar = _modulo()
    [r] = await evaluar.main([str(tmp_path)])
    assert r.error is None
    assert r.campos == {c: True for c in r.campos}
    assert set(r.campos) >= {"nombre", "programa", "inscritos", "tras_solic", "codigos"}
    assert (r.input_tokens, r.output_tokens) == (3000, 500)
    assert (tmp_path / "caso_01" / "_extraccion.json").exists()
    guardado = json.loads((tmp_path / "_resultados.json").read_text(encoding="utf-8"))
    assert guardado[0]["id"] == "caso_01"


async def test_fallos_y_campos_no_evaluados(tmp_path: Path, falso: Falso) -> None:
    falso.salida = extraccion_ejemplo(
        documento="100000000",
        fecha_solicitud="2025-09-02",
        justificacion_breve="Presenta un diagnóstico médico.",
    )
    esperado = dict(ESPERADO, fecha_sin_anio=True, papa=None)
    _caso(tmp_path, "caso_02", esperado)
    evaluar = _modulo()
    [r] = await evaluar.main([str(tmp_path), "--solo", "caso_02"])
    assert r.campos["documento"] is False
    assert r.campos["fecha"] is True  # Gmail no mostraba el año
    assert "papa" not in r.campos
    assert r.campos["privacidad"] is False
    assert "documento" in r.detalles


async def test_fecha_vacia_si_el_acta_no_la_trae(tmp_path: Path, falso: Falso) -> None:
    _caso(tmp_path, "caso_03", dict(ESPERADO, fecha_solicitud=None))
    evaluar = _modulo()
    [r] = await evaluar.main([str(tmp_path)])
    assert r.campos["fecha"] is False  # el modelo puso una fecha que no estaba


def test_tabla_resume_aciertos() -> None:
    evaluar = _modulo()
    a = evaluar.ResultadoCaso("a", campos={"nombre": True, "documento": False})
    b = evaluar.ResultadoCaso("b", error="sin resultado")
    texto = evaluar.tabla([a, b])
    assert "nombre: 1/1" in texto and "documento: 0/1" in texto
    assert "ERROR: sin resultado" in texto
