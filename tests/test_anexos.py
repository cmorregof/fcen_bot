"""Anexos del estudiante: dos zonas, resumen con el modelo, acta y borrado.

El modelo es falso (sin red). Todos los datos son ficticios.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

import pytest
from docx import Document as DocxDocument
from pypdf import PdfReader, PdfWriter

from app.core.config import settings
from app.core.programas import DIRECCIONES, PROGRAMAS
from app.db import repo
from app.db.session import connect
from app.integrations.claude import ClaudeEstructurador, Resultado
from app.schemas.anexo import (
    VERIFICAR_ANEXO,
    AnexoLeido,
    LecturaAnexo,
    ResumenAnexo,
)
from app.services import anexos, borrador, formatos
from app.services.documento import DatosOficio, construir_acta
from tests.conftest import png_bytes
from tests.test_bot import EstructuradorFalso, estructurador  # noqa: F401
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

DIR = next(iter(DIRECCIONES))

CITA = "presenta incapacidad médica por siete (7) días"
CERTIFICADO = (
    "CLÍNICA FICTICIA DEL CAFÉ\n"
    "Manizales, 3 de septiembre de 2026\n"
    "Se certifica que Persona Ficticia Uno presenta incapacidad médica por "
    "siete (7) días, del 1 al 7 de septiembre de 2026.\n"
)


def _docx(texto: str) -> bytes:
    doc = DocxDocument()
    for linea in texto.splitlines():
        doc.add_paragraph(linea)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _pdf(paginas: int) -> bytes:
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    escritor.write(buf)
    return buf.getvalue()


def _resumen(**cambios: Any) -> ResumenAnexo:
    base: dict[str, Any] = {
        "tipo_documento": "certificado médico",
        "fecha": "3 de septiembre de 2026",
        "emisor": "Clínica Ficticia del Café",
        "acredita": "incapacidad médica entre el 1 y el 7 de septiembre de 2026",
        "datos_relevantes": ["siete días de incapacidad"],
        "citas": [CITA, "texto que no está en el documento"],
    }
    base.update(cambios)
    return ResumenAnexo(**base)


class LectorFalso:
    def __init__(self, resumen: ResumenAnexo | None = None) -> None:
        self.resumen = resumen or _resumen()
        self.llamadas: list[dict[str, Any]] = []
        self.error: str | None = None

    async def leer_documento(self, **kw: Any) -> Resultado:
        self.llamadas.append(kw)
        if self.error:
            return Resultado(None, 100, 0, error=self.error)
        return Resultado(self.resumen, 1500, 300)


@pytest.fixture
def lector() -> Any:
    falso = LectorFalso()
    anexos.set_lector(falso)  # type: ignore[arg-type]
    yield falso
    anexos.set_lector(None)


@pytest.fixture
def pdf_sin_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin poppler en la máquina de pruebas: el PDF no tiene texto (escaneado)."""

    async def texto_pdf(datos: bytes) -> str:
        return ""

    monkeypatch.setattr(formatos, "texto_pdf", texto_pdf)


async def _uso(caso: int) -> list[dict[str, Any]]:
    db = await connect()
    cur = await db.execute(
        "SELECT operacion, modelo, input_tokens, output_tokens FROM uso_modelo "
        "WHERE caso_id = ? ORDER BY id",
        (caso,),
    )
    filas = [dict(r) for r in await cur.fetchall()]
    await db.close()
    return filas


def _crear(c: Any, adm: dict[str, str], files: list[Any]) -> int:
    r = c.post(
        "/api/web/actas/casos",
        data={"texto": "Correo ficticio: solicito cancelación por incapacidad."},
        files=files,
        headers=adm,
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


# ---------------------------------------------------------------------------
# Dos zonas
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("pdf_sin_texto")
async def test_dos_zonas_pantallazos_y_anexos(cliente: Cliente) -> None:  # noqa: F811
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = _crear(
        c,
        adm,
        [
            ("pantallazos", ("historia.png", png_bytes(), "image/png")),
            ("anexos", ("foto_certificado.png", png_bytes() + b"x", "image/png")),
            ("anexos", ("escaneado.pdf", _pdf(1), "application/pdf")),
            ("anexos", ("carta.docx", _docx(CERTIFICADO), "application/octet-stream")),
        ],
    )
    ficha = c.get(f"/api/web/actas/casos/{caso}", headers=adm).json()
    por_nombre = {a["nombre"]: a for a in ficha["adjuntos"]}
    assert {n: a["tipo"] for n, a in por_nombre.items()} == {
        "historia.png": "imagen",
        # Una imagen en «Otros anexos» no es un pantallazo del SIA.
        "foto_certificado.png": "anexo",
        # Un PDF escaneado en «Otros anexos» no se pregunta: es un anexo.
        "escaneado.pdf": "anexo",
        "carta.docx": "anexo",
    }
    assert {n: a["zona"] for n, a in por_nombre.items()} == {
        "historia.png": "sia",
        "foto_certificado.png": "anexos",
        "escaneado.pdf": "anexos",
        "carta.docx": "anexos",
    }
    assert ficha["imagenes"] == 1  # solo el pantallazo va a la extracción del SIA
    assert all(a["resumen"] is None for a in ficha["adjuntos"])

    # La zona del SIA solo acepta imágenes.
    r = c.post(
        f"/api/web/actas/casos/{caso}/archivos",
        data={"zona": "sia"},
        files=[("archivos", ("historia.pdf", _pdf(1), "application/pdf"))],
        headers=adm,
    )
    assert r.status_code == 400
    assert "Otros anexos del estudiante" in r.json()["detail"]
    r = c.post(
        f"/api/web/actas/casos/{caso}/archivos",
        data={"zona": "otra"},
        files=[("archivos", ("x.png", png_bytes(), "image/png"))],
        headers=adm,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Leer con el modelo
# ---------------------------------------------------------------------------


async def test_procesar_resume_los_anexos_una_vez(
    cliente: Cliente,  # noqa: F811
    estructurador: EstructuradorFalso,  # noqa: F811
    lector: LectorFalso,
) -> None:
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = _crear(
        c,
        adm,
        [
            ("pantallazos", ("historia.png", png_bytes(), "image/png")),
            ("anexos", ("certificado.docx", _docx(CERTIFICADO), "application/pdf")),
        ],
    )
    r = c.post(f"/api/web/actas/casos/{caso}/procesar", headers=adm)
    assert r.status_code == 200, r.text
    assert r.json()["aviso"] is None

    # Una sola llamada: el Word va como texto, con el modelo y el esfuerzo
    # de la configuración. El pantallazo no se le manda a la lectura de anexos.
    [llamada] = lector.llamadas
    assert llamada["modelo"] == settings.anexos_modelo == "claude-sonnet-5-5"
    assert llamada["esfuerzo"] == settings.anexos_esfuerzo == "medium"
    assert llamada["pdf"] is None and llamada["imagenes"] == []
    assert "Clínica Ficticia del Café".upper() in llamada["texto"]
    assert "solicito cancelación" in llamada["texto"]  # contexto de la solicitud

    [anexo] = [a for a in r.json()["adjuntos"] if a["zona"] == "anexos"]
    resumen = anexo["resumen"]
    assert resumen["tipo_documento"] == "certificado médico"
    # La cita que está en el Word se verifica; la que no, no.
    assert [x["verificada"] for x in resumen["citas"]] == [True, False]
    assert resumen["frase_acta"].startswith(
        "Se adjunta certificado médico de Clínica Ficticia del Café del 3 de "
        "septiembre de 2026, que acredita incapacidad médica"
    )
    assert f"“{CITA}”." in resumen["frase_acta"]
    assert (
        f"“texto que no está en el documento” {VERIFICAR_ANEXO}."
        in (resumen["frase_acta"])
    )

    # El uso queda registrado aparte de la extracción.
    uso = await _uso(caso)
    assert {
        "operacion": "anexo",
        "modelo": "claude-sonnet-5-5",
        "input_tokens": 1500,
        "output_tokens": 300,
    } in uso
    assert any(u["operacion"] == "extraccion" for u in uso)

    # Volver a leer el caso no vuelve a pagar el anexo.
    r = c.post(f"/api/web/actas/casos/{caso}/releer", headers=adm)
    assert r.status_code == 200, r.text
    assert len(lector.llamadas) == 1
    # Leerlo a propósito sí.
    r = c.post(f"/api/web/actas/casos/{caso}/archivos/{anexo['id']}/leer", headers=adm)
    assert r.status_code == 200, r.text
    assert len(lector.llamadas) == 2
    # El pantallazo no es un anexo que se lea así.
    [sia] = [a for a in r.json()["adjuntos"] if a["zona"] == "sia"]
    r = c.post(f"/api/web/actas/casos/{caso}/archivos/{sia['id']}/leer", headers=adm)
    assert r.status_code == 404
    # El comité no lo pide.
    comite = await _token("dir@unal.edu.co", "comite", DIR)
    r = c.post(
        f"/api/web/actas/casos/{caso}/archivos/{anexo['id']}/leer", headers=comite
    )
    assert r.status_code == 403


async def test_agregar_anexo_lo_resume_y_avisa_si_falla(
    cliente: Cliente,  # noqa: F811
    lector: LectorFalso,
) -> None:
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = _crear(c, adm, [("pantallazos", ("h.png", png_bytes(), "image/png"))])
    lector.error = "no quedan créditos en la Console de Anthropic."
    r = c.post(
        f"/api/web/actas/casos/{caso}/archivos",
        data={"zona": "anexos"},
        files=[("archivos", ("foto.png", png_bytes() + b"y", "image/png"))],
        headers=adm,
    )
    assert r.status_code == 200, r.text
    assert "No pude resumir" in r.json()["aviso"]
    assert "foto.png" in r.json()["aviso"]
    [anexo] = [a for a in r.json()["adjuntos"] if a["zona"] == "anexos"]
    assert anexo["resumen"] is None and anexo["se_lee"] is True
    # La imagen va al modelo como imagen.
    assert len(lector.llamadas[0]["imagenes"]) == 1
    # El uso se registra aunque falle.
    assert [u["operacion"] for u in await _uso(caso)] == ["anexo"]

    # Reintento manual: falla con 502, luego funciona.
    ruta = f"/api/web/actas/casos/{caso}/archivos/{anexo['id']}/leer"
    assert c.post(ruta, headers=adm).status_code == 502
    lector.error = None
    r = c.post(ruta, headers=adm)
    assert r.status_code == 200
    [anexo] = [a for a in r.json()["adjuntos"] if a["zona"] == "anexos"]
    # Sin texto con qué comprobar (imagen): ninguna cita queda verificada.
    assert [x["verificada"] for x in anexo["resumen"]["citas"]] == [False, False]


@pytest.mark.usefixtures("pdf_sin_texto")
async def test_pdf_sin_texto_va_como_documento_con_tope_de_paginas(
    cliente: Cliente,  # noqa: F811
    lector: LectorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "anexos_max_paginas", 3)
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = _crear(c, adm, [("anexos", ("escaneado.pdf", _pdf(5), "application/pdf"))])
    r = c.post(
        f"/api/web/actas/casos/{caso}/archivos",
        data={"zona": "anexos"},
        files=[("archivos", ("corto.pdf", _pdf(2), "application/pdf"))],
        headers=adm,
    )
    assert r.status_code == 200, r.text
    # Se leyeron los dos anexos pendientes: cada PDF como documento.
    assert len(lector.llamadas) == 2
    paginas = sorted(
        len(PdfReader(io.BytesIO(x["pdf"])).pages) for x in lector.llamadas
    )
    assert paginas == [2, 3]  # el de 5 páginas se recortó a 3
    assert all("va adjunto" in x["texto"] for x in lector.llamadas)
    por_nombre = {a["nombre"]: a["resumen"] for a in r.json()["adjuntos"]}
    assert por_nombre["escaneado.pdf"]["parcial"] is True
    assert por_nombre["corto.pdf"]["parcial"] is False
    assert "Solo se leyó la primera parte" in por_nombre["escaneado.pdf"]["frase_acta"]
    # Sin texto, las citas no se pueden comprobar.
    assert VERIFICAR_ANEXO in por_nombre["corto.pdf"]["frase_acta"]


# ---------------------------------------------------------------------------
# Acta y borrado
# ---------------------------------------------------------------------------


def _acta(caso: Any) -> DatosOficio:
    programa = PROGRAMAS["ing_fisica"]
    item = borrador.caso_documento(caso, programa)
    assert item is not None
    return DatosOficio(
        programa=programa,
        fecha=date(2026, 10, 13),
        casos=[item],
        elaboro="AB",
        miembros=programa.miembros,
    )


def _parrafos(docx: bytes) -> list[str]:
    return [p.text for p in DocxDocument(io.BytesIO(docx)).paragraphs]


async def test_resumen_en_el_acta_y_se_va_al_borrar(
    cliente: Cliente,  # noqa: F811
    estructurador: EstructuradorFalso,  # noqa: F811
    lector: LectorFalso,
) -> None:
    lector.resumen = _resumen(fecha=None, citas=[CITA])
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso_id = _crear(
        c,
        adm,
        [
            ("pantallazos", ("historia.png", png_bytes(), "image/png")),
            ("anexos", ("certificado.docx", _docx(CERTIFICADO), "application/pdf")),
        ],
    )
    r = c.post(f"/api/web/actas/casos/{caso_id}/procesar", headers=adm)
    assert r.status_code == 200, r.text

    db = await connect()
    caso = await repo.get_caso(db, caso_id)
    await db.close()
    assert caso is not None and len(caso.anexos_leidos) == 1
    docx = construir_acta(_acta(caso), "2026-2S")
    [vineta] = [p for p in _parrafos(docx) if "Se adjunta certificado médico" in p]
    assert vineta == (
        "•\tSe adjunta certificado médico de Clínica Ficticia del Café del "
        f"{VERIFICAR_ANEXO}, que acredita incapacidad médica entre el 1 y el 7 de "
        "septiembre de 2026. Siete días de incapacidad. "
        f"Cita del anexo: “{CITA}”."
    )
    # Lo que falta verificar va resaltado en amarillo.
    doc = DocxDocument(io.BytesIO(docx))
    marcas = [
        run
        for p in doc.paragraphs
        if "Se adjunta" in p.text
        for run in p.runs
        if run.text == VERIFICAR_ANEXO
    ]
    assert marcas and all(run.font.highlight_color is not None for run in marcas)

    # Se borra el anexo: su resumen sale del caso y del acta.
    [anexo] = [a for a in r.json()["adjuntos"] if a["zona"] == "anexos"]
    r = c.delete(f"/api/web/actas/casos/{caso_id}/archivos/{anexo['id']}", headers=adm)
    assert r.status_code == 200, r.text
    assert "resumen también se quitó" in r.json()["aviso"]
    db = await connect()
    caso = await repo.get_caso(db, caso_id)
    await db.close()
    assert caso is not None and caso.anexos_leidos == []
    docx = construir_acta(_acta(caso), "2026-2S")
    assert not any("Se adjunta" in p for p in _parrafos(docx))


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------


def test_frase_sin_datos_marca_verificar() -> None:
    lectura = LecturaAnexo(
        resumen=ResumenAnexo(tipo_documento="constancia", legible=False),
        citas_verificadas=None,
    )
    texto = anexos.frase(AnexoLeido(archivo_id=1, nombre="x.png", lectura=lectura))
    assert texto == (
        f"Se adjunta constancia de {VERIFICAR_ANEXO} del {VERIFICAR_ANEXO}, que "
        f"acredita {VERIFICAR_ANEXO}. Hay partes del documento que no se leen "
        f"{VERIFICAR_ANEXO}."
    )


def test_verificar_citas_tolera_espacios_de_pdftotext() -> None:
    texto = "Se certifica   que presenta\nincapacidad    médica"
    assert anexos.verificar_citas(
        ["que presenta incapacidad médica", "inventado"], texto
    ) == [True, False]
    assert anexos.verificar_citas(["algo"], None) is None


async def test_cliente_real_envia_pdf_y_esfuerzo() -> None:
    """La forma de la petición a la API, con un cliente HTTP falso."""
    enviado: dict[str, Any] = {}

    class Uso:
        input_tokens = 10
        output_tokens = 5

    class Bloque:
        type = "tool_use"
        input = _resumen().model_dump()

    class Respuesta:
        usage = Uso()
        stop_reason = "tool_use"
        content = [Bloque()]

    class Mensajes:
        async def create(self, **kw: Any) -> Respuesta:
            enviado.update(kw)
            return Respuesta()

    lector = ClaudeEstructurador("clave-ficticia", 5)
    lector._client = type("C", (), {"messages": Mensajes()})()  # type: ignore[assignment]
    resultado = await lector.leer_documento(
        sistema="s",
        texto="t",
        imagenes=[],
        pdf=b"%PDF-1.4",
        modelo_salida=ResumenAnexo,
        nombre_herramienta="registrar_anexo",
        modelo="claude-sonnet-5-5",
        max_tokens=8000,
        esfuerzo="medium",
    )
    assert isinstance(resultado.objeto, ResumenAnexo)
    assert enviado["model"] == "claude-sonnet-5-5"
    assert enviado["output_config"] == {"effort": "medium"}
    assert enviado["tool_choice"] == {"type": "auto"}
    [documento, texto] = enviado["messages"][0]["content"]
    assert documento["type"] == "document"
    assert documento["source"]["media_type"] == "application/pdf"
    assert texto == {"type": "text", "text": "t"}

    # Un rechazo del modelo no se toma como resumen.
    Respuesta.stop_reason = "refusal"
    resultado = await lector.leer_documento(
        sistema="s",
        texto="t",
        imagenes=[],
        pdf=None,
        modelo_salida=ResumenAnexo,
        nombre_herramienta="registrar_anexo",
        modelo="claude-sonnet-5-5",
        max_tokens=8000,
        esfuerzo="medium",
    )
    assert resultado.objeto is None and resultado.error


def test_la_frase_no_repite_los_datos_ya_dichos() -> None:
    resumen = ResumenAnexo(
        tipo_documento="certificado médico",
        emisor="Clínica Ficticia",
        fecha="3 de septiembre de 2026",
        acredita="incapacidad médica entre el 1 y el 7 de septiembre de 2026",
        datos_relevantes=["3 de septiembre de 2026", "Siete días de incapacidad"],
    )
    lectura = LecturaAnexo(resumen=resumen)
    texto = anexos.frase(AnexoLeido(archivo_id=1, nombre="c.pdf", lectura=lectura))
    assert texto.count("3 de septiembre de 2026") == 1
    assert "Siete días de incapacidad." in texto
