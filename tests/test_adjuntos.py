"""Adjuntos del caso: PDF, Word e imágenes; borrar los equivocados.

Todos los datos son ficticios.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from docx import Document as DocxDocument

from app.core.config import settings
from app.core.programas import DIRECCIONES
from app.db import repo
from app.db.session import connect
from app.integrations import telegram
from app.services import adjuntos, bot, formatos
from tests.conftest import TelegramFalso, png_bytes
from tests.test_bot import (  # noqa: F401
    EstructuradorFalso,
    _callback,
    _registrar,
    _update,
    estructurador,
)
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

DIR = next(iter(DIRECCIONES))

PDF = b"%PDF-1.4\n% documento ficticio\n%%EOF\n"


def _docx(*parrafos: str) -> bytes:
    doc = DocxDocument()
    for p in parrafos:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


FORMATO = _docx(
    "FORMATO DE CANCELACIÓN DE ASIGNATURAS",
    "Nombre completo: Persona Ficticia Dos",
)


@pytest.fixture
def pdf_con_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin poppler en la máquina de pruebas: el PDF «tiene» texto de soporte."""

    async def texto_pdf(datos: bytes) -> str:
        return "Certificado ficticio de asistencia a evento"

    monkeypatch.setattr(formatos, "texto_pdf", texto_pdf)


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------


def test_detecta_por_contenido_no_por_nombre() -> None:
    assert adjuntos.detectar(PDF) == ".pdf"
    assert adjuntos.detectar(FORMATO) == ".docx"
    assert adjuntos.detectar(png_bytes()) == ".png"
    assert adjuntos.detectar(b"\xff\xd8\xff\xe0 jpg") == ".jpg"
    assert adjuntos.detectar(b"MZ\x90\x00 ejecutable") is None
    assert adjuntos.detectar(b"texto plano") is None
    # Un zip que no es Word (p. ej. un .xlsx) no pasa.
    buf = io.BytesIO()
    import zipfile

    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    assert adjuntos.detectar(buf.getvalue()) is None
    with pytest.raises(adjuntos.AdjuntoInvalido, match="solo se aceptan"):
        adjuntos.validar(b"MZ", "programa.pdf")
    with pytest.raises(adjuntos.AdjuntoInvalido, match="más de 20 MB"):
        adjuntos.validar(PDF + b"0" * adjuntos.MAX_DOCUMENTO, "grande.pdf")


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


def _archivos_del_caso(caso: int) -> list[Path]:
    carpeta = settings.media_dir / str(caso)
    return sorted(carpeta.iterdir()) if carpeta.exists() else []


@pytest.mark.usefixtures("pdf_con_texto")
async def test_web_sube_pdf_word_e_imagen(cliente: Cliente) -> None:  # noqa: F811
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    r = c.post(
        "/api/web/actas/casos",
        data={"texto": "Correo ficticio"},
        files=[
            ("archivos", ("sia.png", png_bytes(), "image/png")),
            ("archivos", ("certificado.pdf", PDF, "application/pdf")),
            ("archivos", ("solicitud.docx", FORMATO, "application/octet-stream")),
        ],
        headers=adm,
    )
    assert r.status_code == 200, r.text
    caso = r.json()["id"]
    ficha = c.get(f"/api/web/actas/casos/{caso}", headers=adm).json()
    tipos = {a["nombre"]: a["tipo"] for a in ficha["adjuntos"]}
    assert tipos == {
        "sia.png": "imagen",
        "certificado.pdf": "anexo",
        "solicitud.docx": "formato",
    }
    assert ficha["imagenes"] == 1
    assert ficha["anexos"] == ["certificado.pdf"]
    assert len(_archivos_del_caso(caso)) == 3
    # El anexo se descarga tal cual.
    anexo = next(a for a in ficha["adjuntos"] if a["tipo"] == "anexo")
    r = c.get(f"/api/web/actas/casos/{caso}/archivos/{anexo['id']}", headers=adm)
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf"

    db = await connect()
    actual = await repo.get_caso(db, caso)
    await db.close()
    assert actual and "Persona Ficticia Dos" in actual.texto


async def test_web_rechaza_tipos_no_permitidos(cliente: Cliente) -> None:  # noqa: F811
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    for nombre, datos in (
        ("planilla.xlsx", b"PK\x03\x04 no es word"),
        ("virus.pdf", b"MZ\x90\x00"),
        ("notas.txt", b"hola"),
    ):
        r = c.post(
            "/api/web/actas/casos",
            data={"texto": "Correo ficticio"},
            files=[("archivos", (nombre, datos, "application/pdf"))],
            headers=adm,
        )
        assert r.status_code == 400, nombre
        assert "solo se aceptan" in r.json()["detail"]
    # No se creó ningún caso a medias.
    assert c.get("/api/web/actas/casos", headers=adm).json()["casos"] == []


async def test_web_agrega_y_clasifica_pdf_escaneado(cliente: Cliente) -> None:  # noqa: F811
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = c.post(
        "/api/web/actas/casos", data={"texto": "Correo ficticio"}, headers=adm
    ).json()["id"]
    ruta = f"/api/web/actas/casos/{caso}"
    r = c.post(
        f"{ruta}/archivos",
        files=[("archivos", ("escaneado.pdf", PDF, "application/pdf"))],
        headers=adm,
    )
    assert r.status_code == 200
    assert "escaneado" in r.json()["aviso"]
    [pendiente] = r.json()["adjuntos"]
    assert pendiente["tipo"] == "pendiente"
    r = c.post(
        f"{ruta}/archivos/{pendiente['id']}/clasificar",
        json={"es_formato": False},
        headers=adm,
    )
    assert r.status_code == 200
    assert r.json()["adjuntos"][0]["tipo"] == "anexo"
    assert [p.name.startswith("_pendiente_") for p in _archivos_del_caso(caso)] == [
        False
    ]
    # El comité ve los adjuntos pero no agrega.
    comite = await _token("dir@unal.edu.co", "comite", DIR)
    r = c.post(
        f"{ruta}/archivos",
        files=[("archivos", ("x.pdf", PDF, "application/pdf"))],
        headers=comite,
    )
    assert r.status_code == 403


@pytest.mark.usefixtures("pdf_con_texto")
async def test_web_borra_con_permiso_y_elimina_el_archivo(
    cliente: Cliente,  # noqa: F811
) -> None:
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = c.post(
        "/api/web/actas/casos",
        data={"texto": "Correo ficticio"},
        files=[
            ("archivos", ("otro_estudiante.pdf", PDF, "application/pdf")),
            ("archivos", ("solicitud.docx", FORMATO, "application/octet-stream")),
        ],
        headers=adm,
    ).json()["id"]
    ruta = f"/api/web/actas/casos/{caso}"
    adjuntos_ = c.get(ruta, headers=adm).json()["adjuntos"]
    anexo = next(a for a in adjuntos_ if a["tipo"] == "anexo")
    formato = next(a for a in adjuntos_ if a["tipo"] == "formato")
    assert len(_archivos_del_caso(caso)) == 2

    # Sin permiso: el comité no borra; otra área no ve el caso.
    comite = await _token("dir@unal.edu.co", "comite", DIR)
    assert c.delete(f"{ruta}/archivos/{anexo['id']}", headers=comite).status_code == 403
    otra = next((d for d in DIRECCIONES if d != DIR), None)
    if otra:
        ajena = await _token("otra@unal.edu.co", "administrativa", otra)
        r = c.delete(f"{ruta}/archivos/{anexo['id']}", headers=ajena)
        assert r.status_code == 404
    assert len(_archivos_del_caso(caso)) == 2

    # Con permiso: se borra del disco y de la base.
    r = c.delete(f"{ruta}/archivos/{anexo['id']}", headers=adm)
    assert r.status_code == 200, r.text
    assert r.json()["aviso"] is None  # el caso no se había leído
    assert [a["id"] for a in r.json()["adjuntos"]] == [formato["id"]]
    assert len(_archivos_del_caso(caso)) == 1
    assert r.json()["anexos"] == []
    assert c.delete(f"{ruta}/archivos/{anexo['id']}", headers=adm).status_code == 404

    # Admin también puede; al borrar el formato sale su texto del caso.
    admin = await _token("admin@unal.edu.co", "admin")
    r = c.delete(f"{ruta}/archivos/{formato['id']}", headers=admin)
    assert r.status_code == 200, r.text
    assert _archivos_del_caso(caso) == []

    db = await connect()
    actual = await repo.get_caso(db, caso)
    cur = await db.execute(
        "SELECT accion, detalle, persona, rol FROM caso_eventos WHERE caso_id = ? "
        "AND accion = 'quitar_adjunto' ORDER BY id",
        (caso,),
    )
    eventos = [dict(r) for r in await cur.fetchall()]
    await db.close()
    assert actual and "Persona Ficticia Dos" not in actual.texto
    assert "Correo ficticio" in actual.texto
    assert [e["rol"] for e in eventos] == ["administrativa", "admin"]
    # El registro no guarda el nombre ni el contenido del archivo.
    for e in eventos:
        assert "otro_estudiante" not in e["detalle"]
        assert "solicitud.docx" not in e["detalle"]
        assert "Ficticia" not in e["detalle"]
    linea = c.get(ruta, headers=adm).json()["linea"]
    assert any(e["texto"] == "Se quitó un adjunto" for e in linea)


async def test_web_avisa_si_el_adjunto_ya_se_leyo(cliente: Cliente) -> None:  # noqa: F811
    from tests.conftest import extraccion_ejemplo

    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = c.post(
        "/api/web/actas/casos",
        data={"texto": "Correo ficticio"},
        files=[("archivos", ("sia.png", png_bytes(), "image/png"))],
        headers=adm,
    ).json()["id"]
    db = await connect()
    await repo.guardar_extraccion(db, caso, extraccion_ejemplo(), None)
    await repo.marcar_leidos(db, caso)
    await db.close()
    ruta = f"/api/web/actas/casos/{caso}"
    [imagen] = c.get(ruta, headers=adm).json()["adjuntos"]
    assert imagen["leido"] is True
    r = c.delete(f"{ruta}/archivos/{imagen['id']}", headers=adm)
    assert r.status_code == 200
    assert "vuelva a leer" in r.json()["aviso"]
    assert r.json()["borrado_leido"] is True
    assert _archivos_del_caso(caso) == []


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------


def _doc(nombre: str, unico: str, tamano: int | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"file_id": unico, "file_unique_id": unico, "file_name": nombre}
    if tamano is not None:
        d["file_size"] = tamano
    return d


@pytest.mark.usefixtures("pdf_con_texto")
async def test_bot_guarda_anexo_y_lo_quita_con_confirmacion(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)

    async def descargar(file_id: str, **_: Any) -> bytes:
        return PDF

    monkeypatch.setattr(telegram, "descargar_archivo", descargar)
    await bot.manejar_update(db, _update(text="Correo ficticio"))
    await bot.manejar_update(db, _update(document=_doc("cert.pdf", "u9")))
    assert any("como anexo del caso #1" in t for t in tg.textos())
    [archivo] = await repo.archivos_de(db, 1)
    assert archivo.ruta and Path(archivo.ruta).exists()

    await bot.manejar_update(db, _update(text="/adjuntos 1"))
    lista = tg.mensajes[-1]
    assert "cert.pdf" in lista["texto"]
    assert lista["botones"][0][0]["callback_data"] == f"aq:1:{archivo.id}"

    # Primero pide confirmación; con «No» no se borra nada.
    await bot.manejar_update(db, _callback(f"aq:1:{archivo.id}"))
    confirmar = tg.mensajes[-1]
    assert "no se puede recuperar" in confirmar["texto"]
    assert confirmar["botones"][0][0]["callback_data"] == f"aqs:1:{archivo.id}"
    await bot.manejar_update(db, _callback("aqn:1"))
    assert Path(archivo.ruta).exists()

    await bot.manejar_update(db, _callback(f"aqs:1:{archivo.id}"))
    assert "Quité el adjunto" in tg.textos()[-1]
    assert not Path(archivo.ruta).exists()
    assert await repo.archivos_de(db, 1) == []


async def test_bot_rechaza_tipos_no_permitidos(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo ficticio"))
    await bot.manejar_update(db, _update(document=_doc("planilla.xlsx", "x1")))
    assert "solo recibo PDF" in tg.textos()[-1]
    await bot.manejar_update(
        db, _update(document=_doc("grande.pdf", "x2", tamano=30 * 1024 * 1024))
    )
    assert "más de 20 MB" in tg.textos()[-1]

    async def descargar(file_id: str, **_: Any) -> bytes:
        return b"MZ\x90\x00 no es un pdf"

    monkeypatch.setattr(telegram, "descargar_archivo", descargar)
    await bot.manejar_update(db, _update(document=_doc("falso.pdf", "x3")))
    assert "solo se aceptan" in tg.textos()[-1]
    assert await repo.archivos_de(db, 1) == []


async def test_bot_otra_area_no_borra(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo ficticio"))
    await bot.manejar_update(
        db,
        _update(
            photo=[{"file_id": "f1", "file_unique_id": "u1", "width": 40, "height": 20}]
        ),
    )
    [archivo] = await repo.archivos_de(db, 1)
    await db.execute("UPDATE casos SET direccion = 'otra_area' WHERE id = 1")
    await db.commit()
    await bot.manejar_update(db, _callback(f"aqs:1:{archivo.id}"))
    assert archivo.ruta and Path(archivo.ruta).exists()
    assert len(await repo.archivos_de(db, 1)) == 1


async def test_web_vuelve_a_leer_sin_tocar_la_recomendacion(
    cliente: Cliente,  # noqa: F811
    estructurador: EstructuradorFalso,  # noqa: F811
) -> None:
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    caso = c.post(
        "/api/web/actas/casos", data={"texto": "Correo ficticio"}, headers=adm
    ).json()["id"]
    ruta = f"/api/web/actas/casos/{caso}"
    assert c.post(f"{ruta}/procesar", headers=adm).json()["estado"] == "listo"
    c.post(f"{ruta}/recomendacion", json={"sentido": "aprobar"}, headers=adm)
    llamadas = len(estructurador.llamadas)
    r = c.post(f"{ruta}/releer", headers=adm)
    assert r.status_code == 200, r.text
    assert len(estructurador.llamadas) == llamadas + 1
    assert r.json()["estado"] == "listo" and r.json()["sentido"] == "aprobar"
    comite = await _token("dir@unal.edu.co", "comite", DIR)
    assert c.post(f"{ruta}/releer", headers=comite).status_code == 403
