from __future__ import annotations

from typing import Any

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db import repo
from app.integrations.claude import Imagen, Resultado
from app.main import app
from app.schemas.caso import EstadoCaso, ExtraccionCaso, Sentido
from app.schemas.telegram import Update
from app.services import bot, extraccion
from tests.conftest import TelegramFalso, extraccion_ejemplo

USUARIO = 555


class EstructuradorFalso:
    def __init__(self, salida: ExtraccionCaso) -> None:
        self.salida = salida
        self.llamadas: list[dict[str, Any]] = []

    async def extraer(self, **kw: Any) -> Resultado:
        self.llamadas.append(kw)
        return Resultado(self.salida, 1000, 200)


_n = 0


def _texto_docx(contenido: bytes) -> str:
    import io

    from docx import Document

    return "\n".join(p.text for p in Document(io.BytesIO(contenido)).paragraphs)


def _update(**mensaje: Any) -> Update:
    global _n
    _n += 1
    base = {
        "message_id": _n,
        "chat": {"id": USUARIO, "type": "private"},
        "from": {"id": USUARIO, "first_name": "Ana", "last_name": "Prueba"},
    }
    base.update(mensaje)
    return Update.model_validate({"update_id": _n, "message": base})


def _callback(data: str) -> Update:
    global _n
    _n += 1
    return Update.model_validate(
        {
            "update_id": _n,
            "callback_query": {
                "id": str(_n),
                "from": {"id": USUARIO, "first_name": "Ana"},
                "message": {
                    "message_id": 1,
                    "chat": {"id": USUARIO, "type": "private"},
                },
                "data": data,
            },
        }
    )


@pytest.fixture
def estructurador(monkeypatch: pytest.MonkeyPatch) -> EstructuradorFalso:
    falso = EstructuradorFalso(extraccion_ejemplo())
    extraccion.set_estructurador(falso)  # type: ignore[arg-type]
    yield falso  # type: ignore[misc]
    extraccion.set_estructurador(None)


async def _registrar(db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invite_code", "CLAVE")
    await bot.manejar_update(db, _update(text="/start CLAVE"))
    await bot.manejar_update(db, _callback("dir:ciencias_naturales"))


async def test_desconocido_no_entra(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    await bot.manejar_update(db, _update(text="hola"))
    assert "uso interno" in tg.textos()[-1]
    assert await repo.get_usuario(db, USUARIO) is None


async def test_codigo_incorrecto_no_registra(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "invite_code", "CLAVE")
    await bot.manejar_update(db, _update(text="/start OTRA"))
    assert await repo.get_usuario(db, USUARIO) is None


async def test_flujo_completo(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    usuario = await repo.get_usuario(db, USUARIO)
    assert usuario and usuario.direccion == "ciencias_naturales"

    await bot.manejar_update(
        db, _update(text="Asunto\nBuenos días,\nSolicito cancelar.")
    )
    assert any("Abrí el caso #1" in t for t in tg.textos())
    await bot.manejar_update(
        db,
        _update(
            photo=[{"file_id": "f1", "file_unique_id": "u1", "width": 40, "height": 20}]
        ),
    )
    await bot.manejar_update(
        db,
        _update(
            document={
                "file_id": "f2",
                "file_unique_id": "u2",
                "file_name": "soporte.pdf",
                "mime_type": "application/pdf",
            }
        ),
    )
    caso = await repo.get_caso(db, 1)
    assert caso and len(caso.imagenes) == 1 and caso.anexos_archivos == ["soporte.pdf"]

    await bot.manejar_update(db, _update(text="/listo"))
    llamada = estructurador.llamadas[-1]
    assert len(llamada["imagenes"]) == 1 and isinstance(llamada["imagenes"][0], Imagen)
    assert "soporte.pdf" in llamada["texto"]
    caso = await repo.get_caso(db, 1)
    assert caso and caso.estado == EstadoCaso.LISTO and caso.programa == "ing_fisica"
    ficha = tg.textos()[-1]
    assert "Caso #1" in ficha and "Persona Ficticia Uno" in ficha

    # Siguiente texto abre un caso nuevo
    await bot.manejar_update(db, _update(text="Otro correo"))
    assert any("Abrí el caso #2" in t for t in tg.textos())

    # Decisión del comité
    await bot.manejar_update(db, _callback("s:1:aprobar"))
    caso = await repo.get_caso(db, 1)
    assert caso and caso.sentido == Sentido.APROBAR

    # Corrección respondiendo a la ficha
    estructurador.salida = extraccion_ejemplo(documento="1000000009")
    await bot.manejar_update(
        db,
        _update(
            text="el documento es 1000000009",
            reply_to_message={
                "message_id": 1,
                "chat": {"id": USUARIO, "type": "private"},
                "text": ficha,
            },
        ),
    )
    caso = await repo.get_caso(db, 1)
    assert caso and caso.extraccion and caso.extraccion.documento == "1000000009"
    assert estructurador.llamadas[-1]["imagenes"] == []

    # Concepto de un miembro del comité: botón, elegir el miembro, responder.
    await bot.manejar_update(db, _callback("c:1"))
    botones = tg.mensajes[-1]["botones"]
    assert botones[0][0]["callback_data"] == "k:1:0"
    await bot.manejar_update(db, _callback("k:1:2"))
    pedido = tg.mensajes[-1]["texto"]
    assert pedido.startswith("Concepto de Elisabeth Restrepo Parra · caso #1")
    await bot.manejar_update(
        db,
        _update(
            text="Recomiendo aprobar.\n\nCumple los requisitos.",
            reply_to_message={
                "message_id": 2,
                "chat": {"id": USUARIO, "type": "private"},
                "text": pedido,
            },
        ),
    )
    caso = await repo.get_caso(db, 1)
    assert caso and [c.miembro for c in caso.conceptos] == ["Elisabeth Restrepo Parra"]
    assert caso.conceptos[0].tratamiento == "La profesora"

    # Borrador a pedido: oficio y acta (sin LibreOffice en las pruebas: solo .docx)
    await bot.manejar_update(db, _update(text="/acta"))
    nombres = [d["nombre"] for d in tg.documentos]
    assert len(nombres) == 2
    assert nombres[0].startswith("Oficio_") and nombres[1].startswith("Acta_")
    oficio = _texto_docx(tg.documentos[0]["contenido"])
    acta = _texto_docx(tg.documentos[1]["contenido"])
    assert "Cumple los requisitos" in acta and "Cumple los requisitos" not in oficio
    assert "La profesora Elisabeth Restrepo Parra expresa:" in acta

    # Cierre
    await bot.manejar_update(db, _callback("cerrar:ing_fisica"))
    caso = await repo.get_caso(db, 1)
    assert caso and caso.estado == EstadoCaso.CERRADO

    # Costo
    await bot.manejar_update(db, _update(text="/costo"))
    assert "USD" in tg.textos()[-1]


async def test_update_repetido_se_ignora(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    u = _update(text="hola")
    await bot.manejar_update(db, u)
    await bot.manejar_update(db, u)
    assert len(tg.mensajes) == 1


async def test_entrega_diaria_solo_con_cambios(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import borrador

    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo"))
    await bot.manejar_update(db, _update(text="/listo"))
    primero = await borrador.entrega_diaria(db)
    assert primero == {"ciencias_naturales": 1}
    segundo = await borrador.entrega_diaria(db)
    assert segundo == {"ciencias_naturales": 0}


def test_webhook_exige_secreto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")
    with TestClient(app) as client:
        assert client.post("/webhook", json={"update_id": 1}).status_code == 403
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s3cr3t")
    with TestClient(app) as client:
        r = client.post("/webhook", json={"update_id": 1})
        assert r.status_code == 403
        r = client.get("/health")
        assert r.json()["ok"] is True
        r = client.post("/internal/borrador-diario")
        assert r.status_code == 403


async def test_nota_solo_como_respuesta(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo uno"))
    await bot.manejar_update(db, _update(text="/listo"))
    await bot.manejar_update(db, _callback("n:1"))
    pedido = tg.mensajes[-1]
    assert pedido.get("forzar_respuesta") is True
    # Un texto suelto NO se toma como nota: abre un caso nuevo.
    await bot.manejar_update(db, _update(text="Correo dos"))
    caso1 = await repo.get_caso(db, 1)
    assert caso1 and caso1.nota_comite is None
    assert any("Abrí el caso #2" in t for t in tg.textos())
    # Respondiendo al pedido sí queda la nota.
    await bot.manejar_update(
        db,
        _update(
            text="El profesor X pide más soportes",
            reply_to_message={
                "message_id": 9,
                "chat": {"id": USUARIO, "type": "private"},
                "text": pedido["texto"],
            },
        ),
    )
    caso1 = await repo.get_caso(db, 1)
    assert caso1 and caso1.nota_comite == "El profesor X pide más soportes"


async def test_no_se_cambia_de_direccion(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _callback("dir:matematicas"))
    usuario = await repo.get_usuario(db, USUARIO)
    assert usuario and usuario.direccion == "ciencias_naturales"


async def test_correccion_no_revive_caso_cerrado(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo"))
    await bot.manejar_update(db, _update(text="/listo"))
    ficha = tg.textos()[-1]
    await bot.manejar_update(db, _callback("s:1:aprobar"))
    await bot.manejar_update(db, _callback("cerrar:ing_fisica"))
    await bot.manejar_update(
        db,
        _update(
            text="el documento es 2",
            reply_to_message={
                "message_id": 1,
                "chat": {"id": USUARIO, "type": "private"},
                "text": ficha,
            },
        ),
    )
    caso = await repo.get_caso(db, 1)
    assert caso and caso.estado == EstadoCaso.CERRADO
    assert "no lo modifico" in tg.textos()[-1]


async def test_acta_a_pedido_no_frena_la_entrega_diaria(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import borrador

    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo"))
    await bot.manejar_update(db, _update(text="/listo"))
    await bot.manejar_update(db, _update(text="/acta"))
    assert await borrador.entrega_diaria(db) == {"ciencias_naturales": 1}


async def test_envio_fallido_no_se_da_por_entregado(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations import telegram
    from app.services import borrador

    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo"))
    await bot.manejar_update(db, _update(text="/listo"))

    async def falla(*a: Any, **kw: Any) -> None:
        raise RuntimeError("403 bot bloqueado")

    monkeypatch.setattr(telegram, "send_document", falla)
    assert await borrador.entrega_diaria(db) == {"ciencias_naturales": 0}
    monkeypatch.setattr(telegram, "send_document", tg.send_document)
    assert await borrador.entrega_diaria(db) == {"ciencias_naturales": 1}


async def test_caso_interrumpido_se_puede_reprocesar(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo"))
    await repo.set_estado_caso(db, 1, EstadoCaso.PROCESANDO)
    await bot.manejar_update(db, _update(text="/listo"))
    caso = await repo.get_caso(db, 1)
    assert caso and caso.estado == EstadoCaso.LISTO


async def test_palabra_procesar_sin_barra(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo del estudiante"))
    await bot.manejar_update(db, _update(text="Procesar"))
    caso = await repo.get_caso(db, 1)
    assert caso and caso.estado == EstadoCaso.LISTO
    assert "Procesar" not in caso.texto


async def test_concepto_de_otro_miembro_y_borrar(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo"))
    await bot.manejar_update(db, _update(text="/listo"))
    await bot.manejar_update(db, _callback("k:1:x"))
    pedido = tg.mensajes[-1]["texto"]
    assert pedido.startswith("Concepto de otro miembro · caso #1")

    def respuesta(texto: str) -> Update:
        return _update(
            text=texto,
            reply_to_message={
                "message_id": 3,
                "chat": {"id": USUARIO, "type": "private"},
                "text": pedido,
            },
        )

    await bot.manejar_update(db, respuesta("El profesor Juan Invitado:\nDe acuerdo."))
    caso = await repo.get_caso(db, 1)
    assert caso and caso.conceptos[0].miembro == "Juan Invitado"
    assert caso.conceptos[0].tratamiento == "El profesor"
    assert caso.conceptos[0].texto == "De acuerdo."

    # Sin concepto debajo del nombre: no se guarda nada nuevo.
    await bot.manejar_update(db, respuesta("Solo un nombre"))
    assert "primera línea" in tg.textos()[-1]

    await bot.manejar_update(db, respuesta("Juan Invitado\nborrar"))
    caso = await repo.get_caso(db, 1)
    assert caso and caso.conceptos == []
