from __future__ import annotations

import json

from app.integrations.claude import esquema_plano
from app.prompts.extraccion import texto_numerado
from app.schemas.caso import ExtraccionCaso
from app.services.extraccion import cuerpo_del_correo
from tests.conftest import extraccion_ejemplo


def test_esquema_sin_referencias() -> None:
    esquema = esquema_plano(ExtraccionCaso)
    assert "$ref" not in json.dumps(esquema)
    assert "$defs" not in esquema
    assert esquema["properties"]["sia"]


def test_texto_numerado() -> None:
    assert texto_numerado("a\nb") == "001| a\n002| b"


def test_cuerpo_por_lineas() -> None:
    texto = "Juan <correo>\nBuenos días,\nSolicito X.\nAdjuntos"
    e = extraccion_ejemplo(cuerpo_desde_linea=2, cuerpo_hasta_linea=3)
    assert cuerpo_del_correo(texto, e) == "Buenos días,\nSolicito X."


def test_cuerpo_salta_encabezado_de_gmail() -> None:
    texto = "Asunto\nPersona <correo>\npara mí\nBuenos días,\nSolicito X."
    e = extraccion_ejemplo(cuerpo_desde_linea=1, cuerpo_hasta_linea=5)
    assert cuerpo_del_correo(texto, e) == "Buenos días,\nSolicito X."


def test_cuerpo_con_lineas_invalidas_usa_todo() -> None:
    e = extraccion_ejemplo(cuerpo_desde_linea=8, cuerpo_hasta_linea=3)
    assert cuerpo_del_correo("hola", e) == "hola"


def test_cuerpo_transcrito_si_no_hay_texto() -> None:
    e = extraccion_ejemplo(cuerpo_transcrito="Texto de la imagen")
    assert cuerpo_del_correo("", e) == "Texto de la imagen"


async def test_salida_cortada_es_error() -> None:
    from types import SimpleNamespace

    from app.integrations.claude import ClaudeEstructurador

    est = ClaudeEstructurador("x", 1)

    async def crear(**kw: object) -> SimpleNamespace:
        bloque = SimpleNamespace(type="tool_use", input={})
        return SimpleNamespace(
            stop_reason="max_tokens",
            usage=SimpleNamespace(input_tokens=10, output_tokens=4000),
            content=[bloque],
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
    assert r.objeto is None and r.error and "incompleta" in r.error


def test_corte_html_no_parte_entidades() -> None:
    from app.integrations.telegram import trozos_html

    texto = "a" * 50 + "&amp;" + "b" * 50
    trozos = trozos_html(texto, limite=52)
    assert all(t.count("&") == t.count(";") for t in trozos)
    assert "".join(trozos) == texto


def test_limpiar_caracteres_de_control() -> None:
    from app.services.documento import limpiar

    assert limpiar("hola\x0bmundo\tok\n") == "hola mundo\tok\n"


def test_errores_de_configuracion_se_explican() -> None:
    from app.integrations.claude import explicar_error

    assert "workspace" in explicar_error(RuntimeError("not scoped to a workspace"))
    assert "créditos" in explicar_error(RuntimeError("Your credit balance is too low"))


async def _respuesta(contenido: list[object], stop: str = "end_turn") -> object:
    from types import SimpleNamespace

    from app.integrations.claude import ClaudeEstructurador

    est = ClaudeEstructurador("x", 1)
    llamadas: list[dict[str, object]] = []

    async def crear(**kw: object) -> SimpleNamespace:
        llamadas.append(kw)
        return SimpleNamespace(
            stop_reason=stop,
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
            content=contenido,
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
    assert llamadas[0]["tool_choice"] == {"type": "auto"}
    return r


async def test_lee_la_herramienta() -> None:
    from types import SimpleNamespace

    bloque = SimpleNamespace(type="tool_use", input={"documento": "1000000001"})
    r = await _respuesta([SimpleNamespace(type="thinking"), bloque])
    assert r.objeto is not None and r.objeto.documento == "1000000001"  # type: ignore[attr-defined]


async def test_si_responde_con_texto_lee_el_json() -> None:
    from types import SimpleNamespace

    texto = 'Aquí está:\n```json\n{"documento": "1000000002"}\n```'
    r = await _respuesta([SimpleNamespace(type="text", text=texto)])
    assert r.objeto is not None and r.objeto.documento == "1000000002"  # type: ignore[attr-defined]


async def test_sin_herramienta_ni_json_es_error() -> None:
    from types import SimpleNamespace

    r = await _respuesta([SimpleNamespace(type="text", text="No puedo.")])
    assert r.objeto is None  # type: ignore[attr-defined]
