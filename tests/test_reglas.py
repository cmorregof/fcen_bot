from __future__ import annotations

from datetime import date

from app.core.programas import PROGRAMAS, identificar_programa
from app.schemas.caso import (
    AsignaturaSolicitada,
    CursoInscrito,
    DatosSIA,
    FilaCreditos,
    TipoSolicitud,
)
from app.services.reglas import (
    analizar,
    completar_tipos,
    creditos_inscritos,
    creditos_tras_solicitud,
    disciplinares_aprobados,
    semana_del_periodo,
    verificar_tabla_sia,
)
from tests.conftest import extraccion_ejemplo, filas_sia

FISICA = PROGRAMAS["ing_fisica"]


def _mensajes(extraccion, **kw) -> list[str]:  # type: ignore[no-untyped-def]
    a = analizar(extraccion, FISICA, periodo_inicio=kw.get("inicio"), hay_imagenes=True)
    return [x.mensaje for x in a.alertas]


def test_tabla_sia_correcta_no_tiene_problemas() -> None:
    sia = DatosSIA(resumen_creditos=filas_sia())
    assert verificar_tabla_sia(sia) == []
    assert creditos_inscritos(sia) == 13
    assert disciplinares_aprobados(sia) == 17


def test_tabla_sia_mal_leida_se_detecta() -> None:
    filas = filas_sia()
    filas[1] = FilaCreditos(
        tipologia="FUND. OBLIGATORIA",
        exigidos=66,
        aprobados=68,
        pendientes=3,
        inscritos=4,
        cursados=63,
    )
    problemas = verificar_tabla_sia(DatosSIA(resumen_creditos=filas))
    assert any("aprobados" in p for p in problemas)


def test_carga_minima_pedida_es_informativa() -> None:
    e = extraccion_ejemplo()
    a = analizar(e, FISICA, periodo_inicio=None, hay_imagenes=True)
    assert a.creditos_tras_solicitud == 9
    assert any(x.nivel == "info" and "carga mínima" in x.mensaje for x in a.alertas)


def test_carga_minima_no_pedida_avisa() -> None:
    e = extraccion_ejemplo(tipos=[TipoSolicitud.CANCELACION])
    a = analizar(e, FISICA, periodo_inicio=None, hay_imagenes=True)
    assert any(
        x.nivel == "aviso" and "no pide carga mínima" in x.mensaje for x in a.alertas
    )


def test_documento_de_nueve_digitos_avisa() -> None:
    assert any(
        "9 dígitos" in m for m in _mensajes(extraccion_ejemplo(documento="105385285"))
    )


def test_documento_faltante_es_error() -> None:
    a = analizar(
        extraccion_ejemplo(documento=None),
        FISICA,
        periodo_inicio=None,
        hay_imagenes=True,
    )
    assert any(x.nivel == "error" for x in a.alertas)


def test_semana_del_periodo() -> None:
    inicio = date(2026, 8, 3)
    assert semana_del_periodo("2026-08-03", inicio) == 1
    assert semana_del_periodo("2026-08-10", inicio) == 2
    assert semana_del_periodo("2026-10-12", inicio) == 11
    assert semana_del_periodo(None, inicio) is None


def test_inscripcion_extemporanea_fuera_de_semana_10() -> None:
    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.INSCRIPCION_EXTEMPORANEA],
        fecha_solicitud="2026-10-12",
        asignaturas=[AsignaturaSolicitada(codigo="4201468", nombre="X", creditos=3)],
    )
    mensajes = _mensajes(e, inicio=date(2026, 8, 3))
    assert any("semana 11" in m and "semana 10" in m for m in mensajes)


def test_trabajo_de_grado_tiene_hasta_semana_13() -> None:
    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.TRABAJO_GRADO],
        fecha_solicitud="2026-10-12",
        asignaturas=[],
    )
    mensajes = _mensajes(e, inicio=date(2026, 8, 3))
    assert not any("semana" in m for m in mensajes)


def test_tdg_con_otras_asignaturas_en_semana_11_avisa() -> None:
    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.TRABAJO_GRADO, TipoSolicitud.INSCRIPCION_EXTEMPORANEA],
        fecha_solicitud="2026-10-12",
        asignaturas=[],
    )
    mensajes = _mensajes(e, inicio=date(2026, 8, 3))
    assert any("demás asignaturas" in m for m in mensajes)


def test_fecha_ilegible_avisa() -> None:
    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.INSCRIPCION_EXTEMPORANEA],
        fecha_solicitud="2 de septiembre",
    )
    mensajes = _mensajes(e, inicio=date(2026, 8, 3))
    assert any("No entendí la fecha" in m for m in mensajes)


def test_tdg_fisica_exige_46_disciplinares() -> None:
    e = extraccion_ejemplo(tipos=[TipoSolicitud.TRABAJO_GRADO], asignaturas=[])
    a = analizar(e, FISICA, periodo_inicio=None, hay_imagenes=True)
    assert a.disciplinares_exigidos_tdg == 46
    assert any("17 de los 46" in x.mensaje and x.nivel == "aviso" for x in a.alertas)


def test_tdg_con_excepcion_pedida_es_info() -> None:
    e = extraccion_ejemplo(
        tipos=[TipoSolicitud.TRABAJO_GRADO, TipoSolicitud.EXCEPCION_NORMA],
        asignaturas=[],
    )
    a = analizar(e, FISICA, periodo_inicio=None, hay_imagenes=True)
    assert any("17 de los 46" in x.mensaje and x.nivel == "info" for x in a.alertas)


def test_sin_pantallazos_avisa() -> None:
    e = extraccion_ejemplo(sia=None)
    a = analizar(e, FISICA, periodo_inicio=None, hay_imagenes=False)
    assert any("No hay pantallazos" in x.mensaje for x in a.alertas)


def test_identificar_programa() -> None:
    assert identificar_programa("4030", None) is FISICA
    assert (
        identificar_programa(None, "CIENCIAS DE LA COMPUTACIÓN")
        is PROGRAMAS["ciencias_computacion"]
    )
    assert identificar_programa("9999", None) is None


def test_dudas_repetidas_se_omiten() -> None:
    e = extraccion_ejemplo(
        documento=None,
        dudas=[
            "El documento de identidad no aparece",
            "Los créditos podrían ser horas",
        ],
    )
    mensajes = _mensajes(e)
    assert sum("documento" in m.lower() for m in mensajes) == 1
    assert any("horas" in m for m in mensajes)


def test_no_suma_lo_que_ya_esta_inscrito() -> None:
    # Pide "ver" dos materias que ya tiene inscritas y cancelar una: 13 - 4 = 9.
    base = extraccion_ejemplo()
    assert base.sia is not None
    sia = base.sia.model_copy(
        update={
            "cursos_inscritos": [
                CursoInscrito(
                    codigo="4100577", nombre="Matemáticas Especiales", creditos=4
                ),
                CursoInscrito(codigo="4100849", nombre="Termodinámica", creditos=4),
            ]
        }
    )
    e = base.model_copy(
        update={
            "sia": sia,
            "asignaturas": [
                AsignaturaSolicitada(
                    codigo="4100577", nombre="Matemáticas Especiales", creditos=4
                ),
                AsignaturaSolicitada(
                    codigo="4100849",
                    nombre="Termodinámica",
                    creditos=4,
                    accion="cancelar",
                ),
            ],
        }
    )
    assert creditos_tras_solicitud(e, 13) == 9


def test_no_suma_trabajo_de_grado_sin_codigo_ya_inscrito() -> None:
    # El SIA ya muestra el Trabajo de Grado inscrito y el correo lo pide sin código.
    base = extraccion_ejemplo()
    assert base.sia is not None
    sia = base.sia.model_copy(
        update={
            "cursos_inscritos": [
                CursoInscrito(
                    codigo="4100870",
                    nombre="Cursos en posgrado",
                    tipologia="TRABAJO DE GRADO",
                    creditos=6,
                ),
            ]
        }
    )
    e = base.model_copy(
        update={
            "sia": sia,
            "tipos": [TipoSolicitud.TRABAJO_GRADO],
            "asignaturas": [
                AsignaturaSolicitada(nombre="Trabajo de Grado", creditos=6),
            ],
        }
    )
    assert creditos_tras_solicitud(e, 9) == 9


def test_completar_tipos_agrega_carga_minima() -> None:
    # Solo pide Trabajo de Grado y quedaría con 13 - 4 = 9 créditos.
    e = extraccion_ejemplo(tipos=[TipoSolicitud.TRABAJO_GRADO])
    assert completar_tipos(e).tipos == [
        TipoSolicitud.TRABAJO_GRADO,
        TipoSolicitud.CARGA_MINIMA,
    ]


def test_completar_tipos_no_toca_si_queda_sobre_el_minimo() -> None:
    e = extraccion_ejemplo(tipos=[TipoSolicitud.PAE], asignaturas=[])
    assert completar_tipos(e).tipos == [TipoSolicitud.PAE]
    sin_sia = extraccion_ejemplo(tipos=[TipoSolicitud.PAE], sia=None)
    assert completar_tipos(sin_sia).tipos == [TipoSolicitud.PAE]
