from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.servicios.admision import archivo, fuentes
from app.servicios.admision.config import config
from tests.admision.conftest import imagen_legible


def pdf(paginas: int) -> bytes:
    w = PdfWriter()
    for _ in range(paginas):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_pdf_correcto() -> None:
    a = archivo.revisar(pdf(2))
    assert a.es_pdf and a.paginas == 2 and not a.problemas


def test_pdf_con_demasiadas_paginas() -> None:
    a = archivo.revisar(pdf(config.max_paginas + 1))
    assert [p.tipo for p in a.problemas] == ["paginas"]


def test_pdf_danado() -> None:
    a = archivo.revisar(b"%PDF-1.4 roto")
    assert [p.tipo for p in a.problemas] == ["formato"]


def test_tipo_no_admitido() -> None:
    a = archivo.revisar(b"PK\x03\x04 un zip")
    assert [p.tipo for p in a.problemas] == ["formato"]


def test_peso(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "max_bytes", 100)
    a = archivo.revisar(b"%PDF-" + b"0" * 200)
    assert [p.tipo for p in a.problemas] == ["peso"]


def test_imagen_legible_se_acepta_y_pierde_exif() -> None:
    a = archivo.revisar(imagen_legible())
    assert not a.problemas and a.media_type == "image/jpeg"
    assert Image.open(io.BytesIO(a.datos)).getexif() == Image.Exif()


def test_imagen_pequena_y_en_blanco() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    a = archivo.revisar(buf.getvalue())
    assert {p.tipo for p in a.problemas} == {"ilegible"}
    assert len(a.problemas) == 2


def test_pdf_escaneado_usa_ocr_y_lo_guarda_en_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "ESCANEADO.pdf").write_bytes(pdf(2))
    llamadas: list[str] = []

    def falso_ocr(ruta: Path) -> list[str]:
        llamadas.append(ruta.name)
        return ["texto uno", "texto dos"]

    monkeypatch.setattr(fuentes, "_ocr", falso_ocr)
    texto = fuentes.texto_fuentes(tmp_path)
    assert "[ESCANEADO.pdf, página 2]\ntexto dos" in texto
    fuentes.texto_fuentes(tmp_path)  # segunda lectura: sale de la caché
    assert llamadas == ["ESCANEADO.pdf"]
    assert (tmp_path / "ESCANEADO.ocr.txt").exists()


def test_con_cache_ocr_presente_no_se_llama_al_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    ruta = tmp_path / "LISTADO.pdf"
    ruta.write_bytes(pdf(1))
    cache = tmp_path / "LISTADO.ocr.txt"
    cache.write_text("texto ya extraído", encoding="utf-8")
    # El PDF es más reciente que la caché (pasa al subir ambos a un volumen).
    os.utime(cache, (1, 1))

    def no_debe_llamarse(_: Path) -> list[str]:
        raise AssertionError("no debe hacer OCR")

    monkeypatch.setattr(fuentes, "_ocr", no_debe_llamarse)
    monkeypatch.setattr(fuentes.shutil, "which", lambda _: None)
    assert "texto ya extraído" in fuentes.texto_fuentes(tmp_path)
