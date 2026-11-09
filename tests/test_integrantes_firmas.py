"""Representación estudiantil y firmas: se configuran fuera del repositorio."""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_COLOR_INDEX

from app.core.config import Settings, settings
from app.core.programas import PROGRAMAS, integrantes, integrantes_con_nombre
from app.schemas.caso import Caso, EstadoCaso, Sentido
from app.services import firmas
from app.services.casos import tratamiento_de
from app.services.documento import (
    CasoDocumento,
    DatosOficio,
    construir_acta,
    construir_oficio,
)
from app.services.reglas import analizar
from tests.conftest import extraccion_ejemplo

CARGO = "Representante Estudiantil (suplente)"


def _png() -> bytes:
    """PNG de 4×1 píxeles, hecho a mano."""

    def bloque(tipo: bytes, datos: bytes) -> bytes:
        cuerpo = tipo + datos
        return (
            struct.pack(">I", len(datos))
            + cuerpo
            + struct.pack(">I", zlib.crc32(cuerpo))
        )

    cabecera = struct.pack(">IIBBBBB", 4, 1, 8, 0, 0, 0, 0)
    filas = zlib.compress(b"\x00" + b"\x00" * 4)
    return (
        b"\x89PNG\r\n\x1a\n"
        + bloque(b"IHDR", cabecera)
        + bloque(b"IDAT", filas)
        + bloque(b"IEND", b"")
    )


def _datos(clave: str, *, borrador: bool = True) -> DatosOficio:
    programa = PROGRAMAS[clave]
    e = extraccion_ejemplo()
    caso = Caso(
        id=1,
        chat_id=1,
        direccion=programa.direccion,
        programa=clave,
        estado=EstadoCaso.LISTO,
        sentido=Sentido.APROBAR,
        texto="x",
        extraccion=e,
    )
    item = CasoDocumento(
        caso,
        e,
        analizar(e, programa, periodo_inicio=None, hay_imagenes=False),
        "Buenos días,\n\nSolicito la cancelación.\n\nPersona Ficticia Uno",
    )
    return DatosOficio(
        programa=programa,
        fecha=date(2026, 11, 9),
        casos=[item],
        elaboro="AB",
        borrador=borrador,
        miembros=integrantes(programa),
    )


def _parrafos(docx: bytes) -> list:
    return list(Document(io.BytesIO(docx)).paragraphs)


def _imagenes(docx: bytes) -> int:
    return len(Document(io.BytesIO(docx)).inline_shapes)


@pytest.fixture
def sin_representante(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "representantes_estudiantiles", "")


def test_lectura_de_representantes() -> None:
    s = Settings(
        representantes_estudiantiles=" matematicas = Persona  Ficticia ;estadistica=; ;x"
    )
    assert s.representantes_por_programa == {"matematicas": "Persona Ficticia"}


def test_representante_sin_configurar_sale_en_amarillo(sin_representante: None) -> None:
    ultimo = integrantes(PROGRAMAS["matematicas"])[-1]
    assert (ultimo.nombre, ultimo.cargo) == ("", CARGO)
    # No se le puede atribuir un concepto a alguien sin nombre.
    assert all(m.nombre for m in integrantes_con_nombre(PROGRAMAS["matematicas"]))

    parrafo = next(
        p
        for p in _parrafos(construir_acta(_datos("matematicas"), "2026-2S"))
        if CARGO in p.text
    )
    assert parrafo.text == f"•\t[nombre], {CARGO}."
    marca = next(r for r in parrafo.runs if r.text == "[nombre]")
    assert marca.font.highlight_color == WD_COLOR_INDEX.YELLOW


def test_representante_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "representantes_estudiantiles", "matematicas=Persona Ficticia Dos"
    )
    textos = [
        p.text for p in _parrafos(construir_acta(_datos("matematicas"), "2026-2S"))
    ]
    assert f"•\tPersona Ficticia Dos, {CARGO}." in textos

    nombres = [m.nombre for m in integrantes_con_nombre(PROGRAMAS["matematicas"])]
    assert nombres[-1] == "Persona Ficticia Dos"
    caso = _datos("matematicas").casos[0].caso
    # Sin tratamiento: el concepto dice «Persona Ficticia Dos expresa…».
    assert tratamiento_de(caso, "Persona Ficticia Dos") is None


def test_programa_sin_representacion_estudiantil() -> None:
    programa = PROGRAMAS["estadistica"]
    assert programa.representante_estudiantil is None
    assert integrantes(programa) == programa.miembros


def test_guardar_y_encontrar_firma(tmp_path: Path) -> None:
    assert firmas.ruta_firma("estadistica", tmp_path) is None
    with pytest.raises(ValueError, match="PNG o JPG"):
        firmas.guardar_firma("estadistica", b"no es imagen", tmp_path)
    with pytest.raises(ValueError, match="programa"):
        firmas.guardar_firma("no_existe", _png(), tmp_path)

    (tmp_path / "estadistica.jpg").write_bytes(b"\xff\xd8\xff vieja")
    destino = firmas.guardar_firma("estadistica", _png(), tmp_path)
    assert destino == tmp_path / "estadistica.png"
    assert not (tmp_path / "estadistica.jpg").exists()  # se reemplaza la anterior
    assert firmas.ruta_firma("estadistica", tmp_path) == destino
    assert any("✓ estadistica.png" in linea for linea in firmas.estado(tmp_path))


def test_firma_solo_en_el_documento_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "firmas_dir", tmp_path)
    firmas.guardar_firma("estadistica", _png(), tmp_path)

    borrador = _datos("estadistica")
    final = replace(borrador, borrador=False)
    for construir in (construir_oficio, construir_acta):
        assert _imagenes(construir(borrador, "2026-2S")) == 0
        docx = construir(final, "2026-2S")
        assert _imagenes(docx) == 1
        # Firma el primer integrante del comité.
        firmante = PROGRAMAS["estadistica"].miembros[0]
        assert firmante.nombre.upper() in [p.text for p in _parrafos(docx)]


def test_final_sin_imagen_de_firma_queda_en_amarillo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "firmas_dir", tmp_path)
    docx = construir_oficio(_datos("estadistica", borrador=False), "2026-2S")
    assert _imagenes(docx) == 0
    assert "[falta la imagen de la firma]" in [p.text for p in _parrafos(docx)]
