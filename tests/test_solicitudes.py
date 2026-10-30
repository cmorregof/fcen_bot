"""Rutas de decisión y umbrales (config/solicitudes.yaml). Datos ficticios."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from fastapi.testclient import TestClient

from app.api.web.actas import _ruta
from app.core import solicitudes
from app.core.config import RAIZ, settings
from app.core.programas import PROGRAMAS
from app.schemas.caso import Caso, EstadoCaso, Sentido, TipoSolicitud
from app.services.documento import construir_oficio
from app.services.ficha import ficha
from app.services.reglas import analizar, disciplinares_aprobados
from tests.conftest import extraccion_ejemplo
from tests.test_documento import _datos

REAL = RAIZ / "config" / "solicitudes.yaml"


def _base() -> dict[str, Any]:
    datos: dict[str, Any] = yaml.safe_load(REAL.read_text(encoding="utf-8"))
    return datos


def _usar(
    datos: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escribe una variante del YAML y la deja en uso."""
    ruta = tmp_path / "solicitudes.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(settings, "solicitudes_path", ruta)
    solicitudes.recargar()


def _alertas(e: Any = None, **kw: Any) -> list[str]:
    e = e or extraccion_ejemplo()
    a = analizar(
        e,
        PROGRAMAS["ing_fisica"],
        periodo_inicio=kw.pop("periodo_inicio", None),
        hay_imagenes=True,
        **kw,
    )
    return [x.mensaje for x in a.alertas]


def _caso(tipos: list[TipoSolicitud]) -> Caso:
    return Caso(
        id=7,
        chat_id=1,
        direccion="ciencias_naturales",
        programa="ing_fisica",
        estado=EstadoCaso.LISTO,
        sentido=Sentido.PENDIENTE,
        extraccion=extraccion_ejemplo(tipos=tipos),
    )


# --- El archivo real ---------------------------------------------------------


def test_todo_tipo_de_solicitud_tiene_ruta() -> None:
    config = solicitudes.cargar(REAL)
    assert set(config.solicitudes) == set(TipoSolicitud)
    for tipo, ruta in config.solicitudes.items():
        assert ruta.recomienda == "comite_asesor", tipo
        if ruta.por_confirmar:
            assert "Vicedecanatura Académica" in (ruta.nota or ""), tipo


def test_umbrales_conservan_los_valores_que_tenia_el_codigo() -> None:
    u = solicitudes.cargar(REAL).umbrales
    assert u.carga_minima.valor == 10
    assert u.semana_limite_asignaturas.valor == 10
    assert u.semana_limite_tdg_actividades.valor == 13
    assert u.semana_limite_traslado.valor == 7
    assert u.jurados_minimo.valor == 6
    assert {k: v.valor for k, v in u.tdg_creditos_disciplinares.items()} == {
        "ing_fisica": 46
    }


def test_solo_las_rutas_que_dicen_las_normas_estan_confirmadas() -> None:
    config = solicitudes.cargar(REAL)
    confirmadas = {t for t, r in config.solicitudes.items() if not r.por_confirmar}
    # Acuerdo 008 art. 10, Acuerdo 350 arts. 1 y 2, procedimiento PAE.
    assert confirmadas == {
        TipoSolicitud.CARGA_MINIMA,
        TipoSolicitud.INSCRIPCION_EXTEMPORANEA,
        TipoSolicitud.PAE,
    }
    assert all(config.ruta(t).decide == "consejo_facultad" for t in confirmadas)


# --- Los umbrales salen del YAML --------------------------------------------


def test_cambiar_la_carga_minima_cambia_la_alerta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # El caso ficticio queda con 9 créditos (13 inscritos − 4 cancelados).
    assert any("carga mínima de 10" in m for m in _alertas())
    datos = _base()
    datos["umbrales"]["carga_minima"]["valor"] = 9
    _usar(datos, tmp_path, monkeypatch)
    assert not any("carga mínima" in m for m in _alertas())


def test_cambiar_la_semana_limite_cambia_la_alerta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.INSCRIPCION_EXTEMPORANEA], fecha_solicitud="2026-10-20"
    )
    inicio = date(2026, 8, 10)  # el 20 de octubre cae en la semana 11
    assert any("hasta la semana 10" in m for m in _alertas(e, periodo_inicio=inicio))
    datos = _base()
    datos["umbrales"]["semana_limite_asignaturas"]["valor"] = 12
    _usar(datos, tmp_path, monkeypatch)
    assert not any("semana" in m for m in _alertas(e, periodo_inicio=inicio))


def test_cambiar_los_creditos_disciplinares_cambia_la_alerta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = extraccion_ejemplo(tipos=[TipoSolicitud.TRABAJO_GRADO])
    assert e.sia is not None
    aprobados = disciplinares_aprobados(e.sia)
    assert aprobados is not None
    datos = _base()
    datos["umbrales"]["tdg_creditos_disciplinares"]["ing_fisica"]["valor"] = (
        aprobados + 1
    )
    _usar(datos, tmp_path, monkeypatch)
    assert any(f"de los {aprobados + 1} créditos" in m for m in _alertas(e))
    datos["umbrales"]["tdg_creditos_disciplinares"] = {}
    _usar(datos, tmp_path, monkeypatch)
    assert not any("créditos disciplinares" in m for m in _alertas(e))


def test_minimo_de_jurados_del_yaml_y_la_variable_gana(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.caso import Jurado

    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.DESIGNACION_JURADOS],
        jurados=[Jurado(nombre=f"Profesor Ficticio {i}") for i in range(4)],
    )
    datos = _base()
    datos["umbrales"]["jurados_minimo"]["valor"] = 3
    _usar(datos, tmp_path, monkeypatch)
    assert not any("jurados" in m for m in _alertas(e))
    monkeypatch.setattr(settings, "jurados_minimo", 8)
    assert any("mínimo 8" in m for m in _alertas(e))


# --- Se ve en la ficha, la web y el oficio ----------------------------------


def test_ficha_dice_quien_recomienda_y_quien_decide() -> None:
    caso = _caso([TipoSolicitud.CARGA_MINIMA])
    texto = ficha(
        caso, analizar(caso.extraccion, None, periodo_inicio=None, hay_imagenes=True)
    )  # type: ignore[arg-type]
    assert "Recomienda: comité asesor · Decide: Consejo de Facultad" in texto
    assert "Vicedecanatura" not in texto


def test_instancia_por_confirmar_visible_en_ficha_y_web() -> None:
    caso = _caso([TipoSolicitud.CANCELACION])
    assert caso.extraccion is not None
    texto = ficha(
        caso, analizar(caso.extraccion, None, periodo_inicio=None, hay_imagenes=True)
    )
    assert "Recomienda: comité asesor · Decide: por confirmar" in texto
    assert "lo confirma la Vicedecanatura Académica" in texto

    web = _ruta(caso)
    assert web["recomienda"] == "Comité asesor"
    assert web["decide"] == "por confirmar"
    assert web["por_confirmar"] is True
    assert web["tramites"] == [
        {
            "tipo": "cancelacion",
            "titulo": "cancelación de asignaturas",
            "decide": "por confirmar",
            "por_confirmar": True,
            "acto": "por confirmar",
            "nota": "Lo confirma la Vicedecanatura Académica.",
        }
    ]


def test_varios_tramites_con_instancias_distintas() -> None:
    texto = solicitudes.texto_decide(
        [TipoSolicitud.CARGA_MINIMA, TipoSolicitud.CANCELACION]
    )
    assert texto == (
        "Consejo de Facultad (carga mínima); por confirmar (cancelación de asignaturas)"
    )


def _parrafos_oficio() -> list[Any]:
    doc = Document(io.BytesIO(construir_oficio(_datos(Sentido.APROBAR), "2026-2S")))
    return list(doc.paragraphs)


def test_oficio_sin_nota_si_decide_el_consejo_de_facultad() -> None:
    texto = "\n".join(p.text for p in _parrafos_oficio())
    assert "revise el destinatario" not in texto


def test_oficio_avisa_en_amarillo_si_decide_otra_instancia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    antes = [p.text for p in _parrafos_oficio()]
    datos = _base()
    datos["solicitudes"]["carga_minima"]["decide"] = "consejo_sede"
    _usar(datos, tmp_path, monkeypatch)
    parrafos = _parrafos_oficio()
    [nota] = [p for p in parrafos if "revise el destinatario" in p.text]
    assert (
        nota.text
        == "Este trámite lo decide el Consejo de Sede: revise el destinatario."
    )
    assert all(r.font.highlight_color == WD_COLOR_INDEX.YELLOW for r in nota.runs)
    # El resto del oficio no cambia de redacción.
    despues = [p.text for p in parrafos if p is not nota]
    assert [t for t in despues if t] == [t for t in antes if t]


# --- YAML inválido -----------------------------------------------------------


def test_yaml_que_falta(tmp_path: Path) -> None:
    with pytest.raises(solicitudes.ConfigSolicitudesError, match="No encuentro"):
        solicitudes.cargar(tmp_path / "no-existe.yaml")


def test_yaml_mal_escrito(tmp_path: Path) -> None:
    ruta = tmp_path / "s.yaml"
    ruta.write_text("umbrales: [sin cerrar\n", encoding="utf-8")
    with pytest.raises(
        solicitudes.ConfigSolicitudesError, match="no es un YAML válido"
    ):
        solicitudes.cargar(ruta)


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        (lambda d: d["solicitudes"].pop("reingreso"), "reingreso"),
        (
            lambda d: d["solicitudes"]["pae"].update(decide="comite_asesor"),
            "solicitudes.pae.decide",
        ),
        (
            lambda d: d["solicitudes"]["pae"].update(normas=["ACUERDO_INVENTADO"]),
            "ACUERDO_INVENTADO",
        ),
        (
            lambda d: d["umbrales"]["carga_minima"].update(valor="diez"),
            "umbrales.carga_minima.valor",
        ),
        (
            lambda d: d["umbrales"]["tdg_creditos_disciplinares"].update(
                programa_ficticio={"valor": 1, "fuente": "x"}
            ),
            "programa_ficticio",
        ),
        (lambda d: d["solicitudes"]["pae"].update(decid="x"), "decid"),
        (lambda d: d["umbrales"]["jurados_minimo"].pop("fuente"), "norma» o «fuente"),
    ],
)
def test_yaml_invalido_da_error_claro(
    cambio: Any, mensaje: str, tmp_path: Path
) -> None:
    datos = _base()
    cambio(datos)
    ruta = tmp_path / "s.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    with pytest.raises(solicitudes.ConfigSolicitudesError) as error:
        solicitudes.cargar(ruta)
    assert mensaje in str(error.value)
    assert str(ruta) in str(error.value)


def test_el_servicio_no_arranca_sin_yaml_valido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app

    monkeypatch.setattr(settings, "bot_servicio", "actas")
    monkeypatch.setattr(settings, "solicitudes_path", tmp_path / "no-existe.yaml")
    with pytest.raises(solicitudes.ConfigSolicitudesError), TestClient(app):
        pass


def test_alertas_citan_norma_y_articulo() -> None:
    [carga] = [m for m in _alertas() if "carga mínima de 10" in m]
    assert (
        "(Acuerdo 008 de 2008 del Consejo Superior Universitario, "
        "Artículo 10 y parágrafo)" in carga
    )
    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.INSCRIPCION_EXTEMPORANEA], fecha_solicitud="2026-10-20"
    )
    [semana] = [
        m for m in _alertas(e, periodo_inicio=date(2026, 8, 10)) if "semana 10" in m
    ]
    assert (
        "Acuerdo 027 de 2024 del Consejo Superior Universitario, Artículo 1" in semana
    )


def test_alerta_de_jurados_dice_si_viene_del_entorno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.caso import Jurado

    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.DESIGNACION_JURADOS],
        jurados=[Jurado(nombre="Profesor Ficticio")],
    )
    [yaml_] = [m for m in _alertas(e) if "jurado" in m]
    assert "instrucción del Consejo de Facultad, 28-oct-2026; no es norma" in yaml_
    monkeypatch.setattr(settings, "jurados_minimo", 8)
    [entorno] = [m for m in _alertas(e) if "jurado" in m]
    assert "mínimo 8 (variable de entorno JURADOS_MINIMO; no es norma)" in entorno
