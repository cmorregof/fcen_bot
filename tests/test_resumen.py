"""Resumen para la decanatura: formato, privacidad, autorización y la regla de
que «pendiente de acta del Consejo» nunca se cuenta como aprobado.

Todos los datos son ficticios.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db import repo
from app.main import app
from app.schemas.caso import EstadoCaso, Sentido
from app.schemas.telegram import Update
from app.services import bot, resumen
from tests.conftest import TelegramFalso, extraccion_ejemplo

DECANA = 9001
VICEDECANO = 9002
ADMINISTRATIVA = 555
EXTRANO = 4444
AHORA = datetime(2026, 11, 2, 12, 30, tzinfo=UTC)

_n = 0


@pytest.fixture(autouse=True)
def decanatura(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "decanatura_telegram_ids", f"{DECANA}, {VICEDECANO}")
    monkeypatch.setattr(settings, "periodo_inicio", date(2026, 8, 3))
    monkeypatch.setattr(settings, "periodo_actual", "2026-2S")
    monkeypatch.setattr(settings, "resumen_dias_sin_movimiento", 7)
    monkeypatch.setattr(settings, "resumen_semanal_activo", True)
    monkeypatch.setattr(settings, "resumen_secret", "")
    monkeypatch.setattr(resumen, "_ahora", lambda: AHORA)


def _update(uid: int, texto: str) -> Update:
    global _n
    _n += 1
    return Update.model_validate(
        {
            "update_id": 50_000 + _n,
            "message": {
                "message_id": _n,
                "chat": {"id": uid, "type": "private"},
                "from": {"id": uid, "first_name": "Persona"},
                "text": texto,
            },
        }
    )


async def _caso(
    db: aiosqlite.Connection,
    *,
    programa: str | None = "ing_fisica",
    estado: EstadoCaso = EstadoCaso.LISTO,
    sentido: Sentido = Sentido.PENDIENTE,
    actualizado: str = "2026-11-01 10:00:00",
    creado: str = "2026-10-01 10:00:00",
) -> int:
    direccion = "ciencias_naturales"
    if programa in ("matematicas", "ciencias_computacion", "estadistica"):
        direccion = "matematicas"
    caso_id = await repo.crear_caso(
        db, chat_id=ADMINISTRATIVA, user_id=ADMINISTRATIVA, direccion=direccion
    )
    await repo.guardar_extraccion(db, caso_id, extraccion_ejemplo(), programa)
    await db.execute(
        "UPDATE casos SET programa = ?, estado = ?, sentido = ?, actualizado = ?,"
        " creado = ? WHERE id = ?",
        (programa, estado.value, sentido.value, actualizado, creado, caso_id),
    )
    await db.commit()
    return caso_id


async def _escenario(db: aiosqlite.Connection) -> None:
    """Física: 2 en preparación (uno viejo), 2 recomendados. Matemáticas: 1
    recomendado no aprobar ya cerrado y 1 con error. Más uno sin programa, uno
    descartado y uno de un periodo anterior ya cerrado."""
    await _caso(db, actualizado="2026-10-10 10:00:00")
    await _caso(db, estado=EstadoCaso.ABIERTO)
    await _caso(db, sentido=Sentido.APROBAR)
    await _caso(db, estado=EstadoCaso.CERRADO, sentido=Sentido.APROBAR)
    await _caso(
        db,
        programa="matematicas",
        estado=EstadoCaso.CERRADO,
        sentido=Sentido.NO_APROBAR,
    )
    await _caso(
        db,
        programa="matematicas",
        estado=EstadoCaso.ERROR,
        actualizado="2026-10-20 10:00:00",
    )
    await _caso(db, programa=None, estado=EstadoCaso.ABIERTO)
    await _caso(db, estado=EstadoCaso.DESCARTADO)
    await _caso(
        db,
        estado=EstadoCaso.CERRADO,
        sentido=Sentido.APROBAR,
        creado="2026-03-01 10:00:00",
    )


# ---------------------------------------------------------------------------
# Cifras y formato
# ---------------------------------------------------------------------------


async def test_cifras_por_programa_y_estado(db: aiosqlite.Connection) -> None:
    await _escenario(db)
    cifras = await resumen.cifras_actas(db, AHORA)
    t = cifras.total
    assert (t.recibidos, t.en_preparacion) == (7, 4)
    assert (t.recomendar_aprobar, t.recomendar_no_aprobar) == (2, 1)
    assert t.pendientes_acta_consejo == 3
    fisica = cifras.por_programa["Ingeniería Física"]
    assert (fisica.recibidos, fisica.en_preparacion, fisica.recomendados) == (4, 2, 2)
    assert cifras.por_programa["Sin programa asignado"].recibidos == 1
    assert (cifras.sin_movimiento, cifras.con_error, cifras.sin_programa) == (2, 1, 1)
    assert [(s.dias, s.programa) for s in cifras.mas_antiguos] == [
        (23, "Ingeniería Física"),
        (13, "Matemáticas"),
        (1, "Ingeniería Física"),
    ]


async def test_formato_del_mensaje(db: aiosqlite.Connection) -> None:
    await _escenario(db)
    texto = resumen.formatear(await resumen.cifras_actas(db, AHORA), date(2026, 11, 2))
    assert texto.startswith("<b>Resumen de casos estudiantiles</b>\n")
    assert "Comités asesores · 2 de noviembre de 2026 · periodo 2026-2S" in texto
    assert (
        "<b>Total</b>: 7 recibidos · 4 en preparación · 3 recomendados por el "
        "comité · 3 pendientes de acta del Consejo"
    ) in texto
    assert "2 recomendar aprobar, 1 recomendar no aprobar" in texto
    assert (
        "• Ingeniería Física: 4 recibidos · 2 en preparación · 2 recomendados por "
        "el comité · 2 pendientes de acta del Consejo"
    ) in texto
    # «Sin programa» va al final de la lista.
    programas = texto.split("<b>Por programa</b>\n")[1].split("\n\n")[0]
    assert programas.splitlines()[-1].startswith("• Sin programa asignado")
    assert "• Ingeniería Física, caso #1: 23 días (esperando al comité)" in texto
    assert "• Matemáticas, caso #6: 13 días (no se pudo leer)" in texto
    assert "• 2 casos llevan más de 7 días sin movimiento." in texto
    assert "• 1 caso no se pudo leer" in texto
    assert "• 1 caso sin programa asignado." in texto
    # Legible: corto y sin jerga técnica.
    assert len(texto) < 2000
    for jerga in ("listo", "abierto", "procesando", "sentido", "None", "null"):
        assert jerga not in texto


async def test_sin_casos(db: aiosqlite.Connection) -> None:
    texto = resumen.formatear(await resumen.cifras_actas(db, AHORA), date(2026, 11, 2))
    assert "No hay casos registrados en el periodo." in texto
    assert "Sin alertas." in texto


# ---------------------------------------------------------------------------
# Regla: lo que decide el Consejo sale de su acta
# ---------------------------------------------------------------------------


async def test_pendiente_de_acta_nunca_cuenta_como_aprobado(
    db: aiosqlite.Connection,
) -> None:
    for _ in range(3):
        await _caso(db, estado=EstadoCaso.CERRADO, sentido=Sentido.APROBAR)
    cifras = await resumen.cifras_actas(db, AHORA)
    assert cifras.total.pendientes_acta_consejo == 3
    texto = resumen.formatear(cifras, date(2026, 11, 2)).lower()
    # La palabra «aprobado/a/s» solo aparece en la aclaración de que no lo es.
    assert texto.count("aprobad") == 1
    assert "no como aprobado" in texto
    assert "aprobados" not in texto
    assert "3 pendientes de acta del consejo" in texto
    assert "recomendar aprobar" in texto


# ---------------------------------------------------------------------------
# Privacidad
# ---------------------------------------------------------------------------


async def test_no_salen_datos_personales(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    await _escenario(db)
    await bot.manejar_update(db, _update(DECANA, "/resumen"))
    texto = tg.textos()[-1]
    ext = extraccion_ejemplo()
    for dato in (
        ext.nombre_estudiante,
        "Persona Ficticia",
        ext.documento,
        "1000000001",
        "Termodinámica",
        "4100849",
        ext.objeto_solicitud,
    ):
        assert dato and dato not in texto


# ---------------------------------------------------------------------------
# Autorización
# ---------------------------------------------------------------------------


async def test_decanatura_recibe_resumen(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    await _caso(db)
    await bot.manejar_update(db, _update(VICEDECANO, "/resumen@fcenpregrado_bot"))
    assert tg.mensajes[-1]["chat_id"] == VICEDECANO
    assert "<b>Resumen de casos estudiantiles</b>" in tg.textos()[-1]


async def test_decanatura_sin_registro_ve_la_ayuda(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    await bot.manejar_update(db, _update(DECANA, "/start"))
    assert tg.textos() == [resumen.AYUDA]
    assert await repo.get_usuario(db, DECANA) is None


async def test_extrano_no_recibe_resumen(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    await _escenario(db)
    await bot.manejar_update(db, _update(EXTRANO, "/resumen"))
    assert all("Resumen" not in t for t in tg.textos())
    assert "uso interno" in tg.textos()[-1]


async def test_administrativa_no_recibe_resumen(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    await repo.registrar_usuario(db, ADMINISTRATIVA, "Administrativa Ficticia")
    await repo.asignar_direccion(db, ADMINISTRATIVA, "ciencias_naturales")
    await _escenario(db)
    await bot.manejar_update(db, _update(ADMINISTRATIVA, "/resumen"))
    assert tg.textos() == ["No conozco ese comando. Escribe /ayuda."]


async def test_grupo_no_recibe_resumen(
    db: aiosqlite.Connection, tg: TelegramFalso
) -> None:
    update = _update(DECANA, "/resumen")
    assert update.message is not None
    update.message.chat.type = "group"
    await bot.manejar_update(db, update)
    assert tg.mensajes == []


def test_ids_de_la_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "decanatura_telegram_ids", " 12;34, x, ,56")
    assert settings.ids_decanatura == {12, 34, 56}
    monkeypatch.setattr(settings, "decanatura_telegram_ids", "")
    assert not resumen.es_decanatura(12)


# ---------------------------------------------------------------------------
# Envío semanal
# ---------------------------------------------------------------------------


def _cliente(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "internal_cron_secret", "cron-prueba")
    monkeypatch.setattr(settings, "bot_servicio", "actas")
    return TestClient(app)


async def test_semanal_envia_a_la_decanatura(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _escenario(db)
    with _cliente(monkeypatch) as cliente:
        r = cliente.post(
            "/internal/resumen-semanal", headers={"X-Cron-Secret": "cron-prueba"}
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "activo": True, "enviados": 2, "destinatarios": 2}
    assert sorted(m["chat_id"] for m in tg.mensajes) == [DECANA, VICEDECANO]
    assert all("pendientes de acta del Consejo" in t for t in tg.textos())


async def test_semanal_se_apaga(
    tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "resumen_semanal_activo", False)
    with _cliente(monkeypatch) as cliente:
        r = cliente.post(
            "/internal/resumen-semanal", headers={"X-Cron-Secret": "cron-prueba"}
        )
    assert r.json() == {"ok": True, "activo": False, "enviados": 0}
    assert tg.mensajes == []


async def test_semanal_pide_secreto(
    tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _cliente(monkeypatch) as cliente:
        r = cliente.post("/internal/resumen-semanal", headers={"X-Cron-Secret": "x"})
    assert r.status_code == 403
    assert tg.mensajes == []


async def test_semanal_sigue_si_un_envio_falla(
    db: aiosqlite.Connection, tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def enviar(chat_id: int, texto: str, **kw: Any) -> int:
        if chat_id == DECANA:
            raise RuntimeError("bot bloqueado")
        return await tg.send_message(chat_id, texto, **kw)

    monkeypatch.setattr(resumen.telegram, "send_message", enviar)
    resultado = await resumen.enviar_semanal(db)
    assert resultado["enviados"] == 1
    assert [m["chat_id"] for m in tg.mensajes] == [VICEDECANO]


# ---------------------------------------------------------------------------
# Calidad y admisión: solo sus conteos, por /internal/cifras
# ---------------------------------------------------------------------------


def test_lineas_de_otros_servicios() -> None:
    calidad = resumen.linea_calidad(
        {
            "total": {
                "no funcionó": 1,
                "vencida": 2,
                "en curso": 3,
                "por iniciar": 1,
                "cumplida": 4,
            },
            "reprogramadas": 3,
        }
    )
    assert calidad.linea == (
        "Calidad, plan de mejoramiento: 11 acciones · 4 cumplidas · 3 en curso · "
        "2 vencidas · 3 reprogramadas"
    )
    assert len(calidad.alertas) == 2
    admision = resumen.linea_admision(
        {
            "total": {
                "documentos_revisados": 40,
                "documentos_con_errores": 6,
                "preguntas_sin_respuesta": 0,
            }
        }
    )
    assert admision.linea == (
        "Admisión: 40 documentos revisados · 6 con errores · 0 preguntas sin respuesta"
    )
    assert admision.alertas == ()
    # Una respuesta rara no rompe el resumen.
    assert resumen.linea_admision({"total": "x"}).linea.startswith("Admisión: 0")


async def test_otros_servicios_en_el_mensaje(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "resumen_secret", "compartido")
    monkeypatch.setattr(settings, "resumen_calidad_url", "https://calidad.ejemplo")
    monkeypatch.setattr(settings, "resumen_admision_url", "https://admision.ejemplo")

    async def pedir(url: str) -> dict[str, Any]:
        if "calidad" in url:
            return {"total": {"vencida": 1, "cumplida": 2}, "reprogramadas": 0}
        raise RuntimeError("caído")

    monkeypatch.setattr(resumen, "_pedir", pedir)
    texto = await resumen.armar(db)
    assert "<b>Otros servicios</b>" in texto
    assert "• Calidad, plan de mejoramiento: 3 acciones · 2 cumplidas" in texto
    assert "• Calidad: 1 acción vencida en el plan de mejoramiento." in texto
    assert "• Admisión: sin datos (el servicio no respondió)." in texto


async def test_sin_secreto_no_se_piden_otros_servicios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "resumen_calidad_url", "https://calidad.ejemplo")

    async def pedir(url: str) -> dict[str, Any]:
        raise AssertionError("no debía pedir nada")

    monkeypatch.setattr(resumen, "_pedir", pedir)
    assert await resumen.externos() == []


@pytest.mark.parametrize("servicio", ["calidad", "admision"])
def test_ruta_de_cifras(servicio: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resumen_secret", "compartido")
    monkeypatch.setattr(settings, "bot_servicio", servicio)
    with TestClient(app) as cliente:
        assert cliente.get("/internal/cifras").status_code == 403
        assert (
            cliente.get(
                "/internal/cifras", headers={"X-Resumen-Secret": "otro"}
            ).status_code
            == 403
        )
        r = cliente.get("/internal/cifras", headers={"X-Resumen-Secret": "compartido"})
    assert r.status_code == 200
    assert r.json()["servicio"] == servicio
    assert "total" in r.json()


def test_ruta_de_cifras_apagada_sin_secreto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bot_servicio", "calidad")
    with TestClient(app) as cliente:
        r = cliente.get("/internal/cifras", headers={"X-Resumen-Secret": ""})
    assert r.status_code == 403


def test_actas_no_expone_cifras(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resumen_secret", "compartido")
    monkeypatch.setattr(settings, "bot_servicio", "actas")
    with TestClient(app) as cliente:
        r = cliente.get("/internal/cifras", headers={"X-Resumen-Secret": "compartido"})
    assert r.status_code == 404
