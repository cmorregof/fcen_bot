"""La lista de chequeo sigue la lista oficial de admitidos de pregrado 2027-1S."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.servicios import admision
from app.servicios.admision import chequeo, fuentes
from app.servicios.admision.modelo import _contexto_documento
from tests.admision.test_archivo_fuentes import pdf

RAIZ = Path(__file__).resolve().parents[2]

SECCIONES = [
    "DOCUMENTOS DE IDENTIFICACIÓN (OBLIGATORIOS)",
    "DOCUMENTOS PERSONALES (OBLIGATORIOS)",
    "DOCUMENTOS PARA ESTABLECER EL NIVEL SOCIOECONÓMICO DEL ADMITIDO (OBLIGATORIOS)",
    "DOCUMENTOS PARA LA APLICACIÓN DE DESCUENTOS (OPCIONALES)",
]


def lista() -> chequeo.ListaChequeo:
    return chequeo.cargar()


def test_secciones_literales_y_en_orden() -> None:
    assert [s for s, _ in lista().secciones()] == SECCIONES


def test_cuenta_por_seccion_como_la_lista_oficial() -> None:
    cuenta = {s: len(docs) for s, docs in lista().secciones()}
    assert cuenta == {
        SECCIONES[0]: 2,
        SECCIONES[1]: 5,
        # La constancia del colegio va dos veces: todos y PEAMA o PAET.
        SECCIONES[2]: 8,
        # Sin el ítem de Medellín, que no aplica a la Sede Manizales.
        SECCIONES[3]: 5,
    }


def test_tipo_sigue_la_seccion() -> None:
    for seccion, docs in lista().secciones():
        for d in docs:
            if "(OPCIONALES)" in seccion:
                assert d.tipo == "opcional", d.clave
            else:
                assert d.tipo in ("obligatorio", "condicional"), d.clave


def test_condicionales_con_el_texto_de_la_lista() -> None:
    condicionales = {
        d.clave: d.condicion for d in lista().documentos if d.tipo == "condicional"
    }
    assert condicionales == {
        "certificado_paes": "Solo admitidos PAES",
        "certificado_residencia": "Solo para admitidos PEAMA o PAET",
        "constancia_colegio_peama_paet": "Solo para admitidos PEAMA o PAET",
    }


def test_claves_anteriores_se_conservan() -> None:
    claves = {d.clave for d in lista().documentos}
    assert {
        "documento_identidad",
        "registro_civil",
        "icfes",
        "acta_grado",
        "formato_matricula",
    } <= claves


def test_item_de_medellin_queda_fuera() -> None:
    texto = RAIZ.joinpath("config/admision/chequeo.yaml").read_text(encoding="utf-8")
    for d in lista().documentos:
        assert "Universidad de Antioquia" not in " ".join([d.nombre, *d.chequeo])
    assert "Universidad de Antioquia" in texto  # el comentario explica por qué


@pytest.mark.parametrize(
    ("clave", "frase"),
    [
        ("documento_identidad", "documento de identidad vigente"),
        ("registro_civil", "nombre de los padres"),
        ("formato_matricula", "diligenciado"),
        ("certificado_paes", "Ministerio del Interior"),
        ("certificado_residencia", "Junta de Acción Comunal"),
        ("certificado_residencia", "ha residido en la zona de influencia"),
        ("certificado_eps", "Sistema General Seguridad Social en Salud EPS"),
        ("constancia_colegio_peama_paet", "DOS últimos años de bachillerato"),
        ("facturas_servicios", "estrato"),
        ("certificado_electoral", "No es válido el certificado electoral"),
        ("registro_matrimonio", "unión marital de hecho"),
    ],
)
def test_puntos_con_texto_oficial(clave: str, frase: str) -> None:
    doc = lista().buscar(clave)
    assert doc is not None
    assert any(frase in p for p in doc.chequeo)


def test_ningun_boton_supera_los_limites_de_telegram() -> None:
    for d in lista().documentos:
        assert len(d.nombre) <= 64
        assert len(f"adm:doc:{d.clave}".encode()) <= 64


def test_condicional_sin_condicion_no_carga() -> None:
    with pytest.raises(ValidationError):
        chequeo.Documento(
            clave="x", nombre="X", seccion="S", tipo="condicional", chequeo=["a"]
        )
    with pytest.raises(ValidationError):
        chequeo.Documento(
            clave="x", nombre="X", seccion="S", condicion="Solo PAES", chequeo=["a"]
        )


def test_claves_repetidas_no_cargan(tmp_path: Path) -> None:
    ruta = tmp_path / "chequeo.yaml"
    doc = "  - {clave: a, nombre: A, seccion: S, chequeo: [x]}\n"
    ruta.write_text("documentos:\n" + doc + doc, encoding="utf-8")
    with pytest.raises(ValidationError):
        chequeo.cargar(ruta)


def test_leyenda_elige_el_documento_mas_especifico() -> None:
    assert (
        admision._tipo_por_texto("Constancia del colegio (PEAMA o PAET)")
        == "constancia_colegio_peama_paet"
    )
    assert admision._tipo_por_texto("constancia del colegio") == "constancia_colegio"


def test_el_modelo_recibe_condicion_y_nota() -> None:
    doc = lista().buscar("certificado_paes")
    assert doc is not None
    texto = _contexto_documento(doc)
    assert "Solo admitidos PAES" in texto
    assert "Población Negra, Afrocolombiana, Palenquera y Raizal" in texto
    assert "DOCUMENTOS PERSONALES (OBLIGATORIOS)" in texto


# ---------------------------------------------------------------------------
# Insumos
# ---------------------------------------------------------------------------


def _con_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simula PDF con capa de texto (los PDF ficticios están en blanco)."""

    def falso(ruta: Path) -> list[str]:
        return [f"Texto de {ruta.name}. " + "x" * 400]

    monkeypatch.setattr(fuentes, "_texto_pdf", falso)


def test_carga_todos_los_pdf_esperados(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _con_texto(monkeypatch)
    for nombre in fuentes.INSUMOS_ESPERADOS:
        (tmp_path / nombre).write_bytes(pdf(1))
    (tmp_path / ".subiendo-abc").write_bytes(b"a medias")
    texto = fuentes.texto_fuentes(tmp_path)
    for nombre in fuentes.INSUMOS_ESPERADOS:
        assert f'<fuente nombre="{nombre}">' in texto
    assert "a medias" not in texto


def test_diagnostico_de_insumos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fuentes.shutil, "which", lambda _: None)
    real = fuentes._texto_pdf

    def texto(ruta: Path) -> list[str]:
        if ruta.name.startswith("CON_TEXTO"):
            return ["x" * 400]
        return real(ruta)

    monkeypatch.setattr(fuentes, "_texto_pdf", texto)
    (tmp_path / "CON_TEXTO.pdf").write_bytes(pdf(1))
    (tmp_path / "ESCANEADO.pdf").write_bytes(pdf(2))
    (tmp_path / "CACHE.pdf").write_bytes(pdf(1))
    (tmp_path / "CACHE.ocr.txt").write_text("uno\fdos", encoding="utf-8")
    (tmp_path / "DANADO.pdf").write_bytes(b"%PDF-roto")
    (tmp_path / "GUIA.md").write_text("Guía ficticia", encoding="utf-8")
    estados = {d.nombre: (d.estado, d.paginas) for d in fuentes.diagnosticar(tmp_path)}
    assert estados == {
        "CACHE.pdf": ("ocr_en_cache", 2),
        "CON_TEXTO.pdf": ("ok", 1),
        "DANADO.pdf": ("ilegible", 0),
        "ESCANEADO.pdf": ("falta_ocr", 2),
        "GUIA.md": ("ok", 1),
    }


def test_diagnostico_sin_carpeta_es_vacio(tmp_path: Path) -> None:
    assert fuentes.diagnosticar(tmp_path / "no-existe") == []


async def test_precarga_no_rompe_el_arranque_sin_insumos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.servicios.admision.config import config

    monkeypatch.setattr(config, "insumos_dir", tmp_path / "no-existe")
    await fuentes.precargar()
    assert "no disponibles" in caplog.text


async def test_precarga_avisa_los_que_faltan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from app.servicios.admision.config import config

    caplog.set_level(logging.INFO)
    _con_texto(monkeypatch)
    (tmp_path / fuentes.INSUMOS_ESPERADOS[0]).write_bytes(pdf(1))
    monkeypatch.setattr(config, "insumos_dir", tmp_path)
    await fuentes.precargar()
    assert "Insumos de admisión listos" in caplog.text
    assert fuentes.INSUMOS_ESPERADOS[3] in caplog.text


# ---------------------------------------------------------------------------
# Imagen de producción
# ---------------------------------------------------------------------------


def test_la_imagen_lleva_la_lista_y_el_aviso() -> None:
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY config/ ./config/" in dockerfile
    assert "COPY docs/admision/aviso_datos.md" in dockerfile
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8").split()
    assert not {"config/", "docs/", "config", "docs"} & set(ignorados)


def test_los_insumos_no_estan_en_el_repo() -> None:
    for raiz, _, archivos in os.walk(RAIZ):
        if any(p in raiz for p in (".git", "node_modules", ".venv", "/web/.next")):
            continue
        for nombre in archivos:
            assert nombre not in fuentes.INSUMOS_ESPERADOS, Path(raiz) / nombre
