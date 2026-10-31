"""Línea única de estados de una solicitud (app/services/flujo.py).

Datos ficticios. Cubre las transiciones permitidas y las prohibidas, la
migración de los casos anteriores y que Telegram y la web escriben sobre la
misma línea.
"""

from __future__ import annotations

import json
import re
from datetime import date

import aiosqlite
import pytest

from app.core import solicitudes
from app.db import repo
from app.db.session import connect
from app.schemas.caso import EstadoCaso, Sentido
from app.schemas.consejo import SentidoConsejo
from app.services import bot, flujo, indicadores, notificaciones
from app.services.flujo import Accion, Etapa, TransicionNoPermitida
from tests.conftest import TelegramFalso
from tests.test_bot import (  # noqa: F401
    USUARIO,
    EstructuradorFalso,
    _callback,
    _registrar,
    _update,
    estructurador,
)
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

ADM = flujo.ADMINISTRATIVA
SEC = flujo.SECRETARIA


async def _nuevo(db: aiosqlite.Connection, canal: str = "web") -> int:
    """Un caso ya leído (estado «listo»), como lo deja la lectura."""
    caso = await repo.crear_caso(
        db, chat_id=0, user_id=0, direccion="ciencias_naturales", canal=canal
    )
    await db.execute(
        "UPDATE casos SET estado = 'listo', programa = 'ing_fisica' WHERE id = ?",
        (caso,),
    )
    await db.commit()
    return caso


async def _etapa(db: aiosqlite.Connection, caso_id: int) -> Etapa:
    return await flujo.etapa_de(db, caso_id)


def _con_flujo(monkeypatch: pytest.MonkeyPatch, **valores: bool) -> None:
    config = solicitudes.actual().model_copy(
        update={"flujo": solicitudes.Flujo(**valores)}
    )
    monkeypatch.setattr(solicitudes, "actual", lambda: config)


async def _hasta_consejo(db: aiosqlite.Connection) -> int:
    caso = await _nuevo(db)
    await flujo.lectura_lista(db, caso)
    await flujo.recomendar(
        db, caso, Sentido.APROBAR, rol=ADM, persona="Adm", canal="web"
    )
    await flujo.enviar_consejo(db, [caso], rol=ADM, persona="Adm", canal="web")
    return caso


async def _decidir(db: aiosqlite.Connection, caso: int, fecha: str) -> None:
    await flujo.transicionar(
        db, caso, Accion.DECIDIR, rol=ADM, persona="Adm", canal="web", fecha=fecha
    )


# ---------------------------------------------------------------------------
# El comité nunca aprueba
# ---------------------------------------------------------------------------


def test_ninguna_transicion_es_del_comite() -> None:
    for config in (
        solicitudes.Flujo(),
        solicitudes.Flujo(prerrevision_obligatoria=True),
        solicitudes.Flujo(improcedente_va_a_comite=False),
    ):
        for accion, t in flujo.transiciones(config).items():
            assert "comite" not in t.roles, accion
    # Antes de la decisión, a «decidida» solo se llega registrando el acta del
    # Consejo (lo demás es la Secretaría que corrige su propia expedición).
    antes = {Etapa.EN_COMITE, Etapa.RECOMENDADA, Etapa.EN_CONSEJO}
    a_decidida = [
        a
        for a, t in flujo.transiciones().items()
        if t.hacia == Etapa.DECIDIDA and t.desde & antes
    ]
    assert a_decidida == [Accion.DECIDIR]


async def test_falla_si_el_comite_aprueba(db: aiosqlite.Connection) -> None:
    """Si alguna vez el comité puede «aprobar», esta prueba falla."""
    caso = await _hasta_consejo(db)
    for accion in Accion:
        with pytest.raises(TransicionNoPermitida):
            await flujo.transicionar(
                db, caso, accion, rol="comite", persona="Comité", canal="web"
            )
    with pytest.raises(TransicionNoPermitida):
        await flujo.recomendar(
            db, caso, Sentido.APROBAR, rol="comite", persona="Comité", canal="web"
        )
    assert await _etapa(db, caso) == Etapa.EN_CONSEJO
    # El comité solo recomienda: no hay un sentido «aprobado» del comité.
    assert {s.value for s in Sentido} == {"pendiente", "aprobar", "no_aprobar"}
    textos = list(flujo.NOMBRE_ACCION.values()) + list(flujo.NOMBRE_ETAPA.values())
    for texto in textos:
        assert not re.search(r"comit[ée]\s+(aprueba|aprob[óo]|decide)", texto, re.I)


async def test_el_comite_no_aprueba_desde_la_web(cliente: Cliente) -> None:  # noqa: F811
    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", "ciencias_naturales")
    caso = c.post("/api/web/actas/casos", data={"texto": "Correo"}, headers=adm).json()
    ruta = f"/api/web/actas/casos/{caso['id']}"
    comite = await _token("dir@unal.edu.co", "comite", "ciencias_naturales")
    for sub, cuerpo in (
        ("/recomendacion", {"sentido": "aprobar"}),
        ("/prerrevision", {"resultado": "procedente"}),
        ("/enviar-consejo", None),
    ):
        assert c.post(ruta + sub, json=cuerpo, headers=comite).status_code == 403


# ---------------------------------------------------------------------------
# Transiciones permitidas: el recorrido completo
# ---------------------------------------------------------------------------


async def test_recorrido_completo(db: aiosqlite.Connection) -> None:
    caso = await _nuevo(db)
    assert await _etapa(db, caso) == Etapa.LLEGADA
    await flujo.lectura_lista(db, caso)
    assert await _etapa(db, caso) == Etapa.EN_COMITE
    await flujo.prerrevisar(
        db, caso, flujo.Prerrevision.PROCEDENTE, rol=ADM, persona="Adm", canal="web"
    )
    await flujo.recomendar(
        db, caso, Sentido.APROBAR, rol=ADM, persona="Adm", canal="web"
    )
    assert await _etapa(db, caso) == Etapa.RECOMENDADA
    await flujo.enviar_consejo(db, [caso], rol=ADM, persona="Adm", canal="web")
    assert await _etapa(db, caso) == Etapa.EN_CONSEJO
    assert (await repo.get_caso(db, caso)).estado == EstadoCaso.CERRADO  # type: ignore[union-attr]
    await _decidir(db, caso, "2026-09-17")
    assert await _etapa(db, caso) == Etapa.DECIDIDA

    registro = notificaciones.Registro(
        acto="oficio",
        numero="Mz.FCEN.1.004-001-2026",
        fecha_ingreso=date(2026, 9, 18),
        fecha_expedicion=date(2026, 9, 20),
        fecha_notificacion=date(2026, 9, 22),
    )
    await notificaciones.guardar(db, caso, registro, "sec@unal.edu.co")
    assert await _etapa(db, caso) == Etapa.NOTIFICADA
    await flujo.archivar(db, caso, rol=SEC, persona="sec", detalle="Drive/x.pdf")
    assert await _etapa(db, caso) == Etapa.ARCHIVADA

    evs = await flujo.eventos(db, caso)
    assert [e.hacia for e in evs] == [
        Etapa.LLEGADA,
        Etapa.EN_COMITE,
        Etapa.EN_COMITE,
        Etapa.RECOMENDADA,
        Etapa.EN_CONSEJO,
        Etapa.DECIDIDA,
        Etapa.EXPEDIDA,
        Etapa.NOTIFICADA,
        Etapa.ARCHIVADA,
    ]
    # Cada transición guarda fecha, rol y quién la hizo.
    assert all(e.fecha for e in evs)
    assert [e.rol for e in evs[-3:]] == [SEC, SEC, SEC]
    assert evs[-3].fecha == "2026-09-20" and evs[-2].fecha == "2026-09-22"
    assert flujo.siguiente(Etapa.ARCHIVADA, leido=True, tipos=[]) is None


async def test_la_fecha_de_la_recomendacion_es_la_misma_en_la_linea(
    db: aiosqlite.Connection,
) -> None:
    caso = await _nuevo(db)
    await flujo.recomendar(
        db, caso, Sentido.NO_APROBAR, rol=ADM, persona="Adm", canal="web"
    )
    # Volver a pulsar el mismo botón no mueve la fecha ni agrega eventos.
    await flujo.recomendar(
        db, caso, Sentido.NO_APROBAR, rol=ADM, persona="Adm", canal="web"
    )
    cur = await db.execute("SELECT recomendado FROM casos WHERE id = ?", (caso,))
    recomendado = (await cur.fetchone())[0]
    evs = [e for e in await flujo.eventos(db, caso) if e.accion == Accion.RECOMENDAR]
    assert len(evs) == 1 and evs[0].fecha == recomendado
    # Retirar la recomendación también queda en la línea.
    await flujo.recomendar(
        db, caso, Sentido.PENDIENTE, rol=ADM, persona="Adm", canal="web"
    )
    assert await _etapa(db, caso) == Etapa.EN_COMITE


async def test_tramos_del_indicador_principal(db: aiosqlite.Connection) -> None:
    caso = await _hasta_consejo(db)
    await _decidir(db, caso, "2099-01-10")
    tramos = flujo.tramos(
        await flujo.eventos(db, caso), json.dumps({"fecha_solicitud": "2000-01-01"})
    )
    assert tramos[0].nombre.startswith("De la llegada a la decisión")
    # La fecha leída (2000-01-01) es anterior al registro: cuenta desde ella.
    assert tramos[0].dias == (date(2099, 1, 10) - date(2000, 1, 1)).days


# ---------------------------------------------------------------------------
# Transiciones prohibidas
# ---------------------------------------------------------------------------


async def test_transiciones_prohibidas(db: aiosqlite.Connection) -> None:
    caso = await _nuevo(db)
    await flujo.lectura_lista(db, caso)
    # Sin recomendación no se envía al Consejo, ni se expide ni se notifica.
    for accion, rol in (
        (Accion.ENVIAR_CONSEJO, ADM),
        (Accion.EXPEDIR, SEC),
        (Accion.NOTIFICAR, SEC),
        (Accion.ARCHIVAR, SEC),
        (Accion.COMPLETAR, ADM),
        (Accion.REGISTRAR, ADM),
    ):
        with pytest.raises(TransicionNoPermitida):
            await flujo.transicionar(
                db, caso, accion, rol=rol, persona="x", canal="web"
            )
    # Roles: la Secretaría no registra recomendaciones; la administrativa no
    # expide.
    with pytest.raises(TransicionNoPermitida):
        await flujo.recomendar(
            db, caso, Sentido.APROBAR, rol=SEC, persona="x", canal="web"
        )
    await flujo.recomendar(db, caso, Sentido.APROBAR, rol=ADM, persona="x", canal="web")
    await flujo.enviar_consejo(db, [caso], rol=ADM, persona="x", canal="web")
    # En el Consejo, la recomendación ya no se cambia (debe volver al comité).
    with pytest.raises(TransicionNoPermitida, match="en el consejo"):
        await flujo.recomendar(
            db, caso, Sentido.NO_APROBAR, rol=ADM, persona="x", canal="web"
        )
    await flujo.volver_al_comite(db, caso, rol=ADM, persona="x", canal="web")
    assert (await repo.get_caso(db, caso)).estado == EstadoCaso.LISTO  # type: ignore[union-attr]
    await flujo.enviar_consejo(db, [caso], rol=ADM, persona="x", canal="web")
    await _decidir(db, caso, "2026-09-17")
    with pytest.raises(TransicionNoPermitida):
        await flujo.transicionar(
            db, caso, Accion.EXPEDIR, rol=ADM, persona="x", canal="web"
        )
    with pytest.raises(TransicionNoPermitida):
        await flujo.descartar(db, caso, rol=ADM, persona="x", canal="web")
    await flujo.transicionar(
        db, caso, Accion.EXPEDIR, rol=SEC, persona="x", canal="web"
    )
    # Con el acto expedido, la decisión del Consejo no se reemplaza.
    with pytest.raises(TransicionNoPermitida, match="expedido"):
        await flujo.validar_consejo(db, caso, SentidoConsejo.NO_APROBO, ADM)
    assert await _etapa(db, caso) == Etapa.EXPEDIDA


async def test_la_secretaria_corrige_fechas_y_queda_anotado(
    db: aiosqlite.Connection,
) -> None:
    caso = await _hasta_consejo(db)
    await _decidir(db, caso, "2026-09-17")

    def reg(exp: date | None, notif: date | None) -> notificaciones.Registro:
        return notificaciones.Registro(
            acto="oficio", numero="N-1", fecha_expedicion=exp, fecha_notificacion=notif
        )

    await notificaciones.guardar(db, caso, reg(date(2026, 9, 20), None), "s")
    assert await _etapa(db, caso) == Etapa.EXPEDIDA
    await notificaciones.guardar(db, caso, reg(date(2026, 9, 20), None), "s")
    n = len(await flujo.eventos(db, caso))  # guardar igual no agrega nada
    await notificaciones.guardar(db, caso, reg(date(2026, 9, 21), None), "s")
    evs = await flujo.eventos(db, caso)
    assert [e.accion for e in evs[n:]] == [Accion.ANULAR_EXPEDICION, Accion.EXPEDIR]
    assert evs[-1].fecha == "2026-09-21"
    # Archivar antes de notificar: se anota y se archiva al notificar.
    await flujo.archivar(db, caso, rol=SEC, persona="s", detalle="Drive")
    assert await _etapa(db, caso) == Etapa.EXPEDIDA
    await notificaciones.guardar(
        db, caso, reg(date(2026, 9, 21), date(2026, 9, 23)), "s"
    )
    assert await _etapa(db, caso) == Etapa.ARCHIVADA
    with pytest.raises(TransicionNoPermitida, match="archivado"):
        await notificaciones.guardar(db, caso, reg(date(2026, 9, 21), None), "s")


# ---------------------------------------------------------------------------
# Prerrevisión del programa (configurable)
# ---------------------------------------------------------------------------


async def test_prerrevision_por_defecto_no_cambia_el_recorrido(
    db: aiosqlite.Connection,
) -> None:
    caso = await _nuevo(db)
    await flujo.lectura_lista(db, caso)
    assert await _etapa(db, caso) == Etapa.EN_COMITE
    await flujo.prerrevisar(
        db, caso, flujo.Prerrevision.IMPROCEDENTE, rol=ADM, persona="x", canal="web"
    )
    # Por defecto el improcedente igual pasa por el comité, con la marca.
    assert await _etapa(db, caso) == Etapa.EN_COMITE
    assert (await repo.get_caso(db, caso)).prerrevision == "improcedente"  # type: ignore[union-attr]


async def test_prerrevision_obligatoria(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _con_flujo(monkeypatch, prerrevision_obligatoria=True)
    caso = await _nuevo(db)
    await flujo.lectura_lista(db, caso)
    assert await _etapa(db, caso) == Etapa.LLEGADA
    with pytest.raises(TransicionNoPermitida):
        await flujo.recomendar(
            db, caso, Sentido.APROBAR, rol=ADM, persona="x", canal="web"
        )
    await flujo.prerrevisar(
        db, caso, flujo.Prerrevision.INCOMPLETO, rol=ADM, persona="x", canal="web"
    )
    assert await _etapa(db, caso) == Etapa.INCOMPLETA
    await flujo.completar(db, caso, rol=ADM, persona="x", canal="web")
    await flujo.prerrevisar(
        db, caso, flujo.Prerrevision.PROCEDENTE, rol=ADM, persona="x", canal="web"
    )
    assert await _etapa(db, caso) == Etapa.EN_COMITE


async def test_improcedente_que_no_va_al_comite_se_guarda_para_metricas(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _con_flujo(monkeypatch, improcedente_va_a_comite=False)
    caso = await _nuevo(db)
    await flujo.lectura_lista(db, caso)
    assert [c.id for c in await repo.casos_listos(db, direccion="ciencias_naturales")]
    await flujo.prerrevisar(
        db, caso, flujo.Prerrevision.IMPROCEDENTE, rol=ADM, persona="x", canal="web"
    )
    assert await _etapa(db, caso) == Etapa.IMPROCEDENTE
    # Sale del borrador del comité, pero sigue contando como recibido.
    assert await repo.casos_listos(db, direccion="ciencias_naturales") == []
    hoy = indicadores.hoy_local()
    periodo = indicadores.periodo_de(f"{hoy.year}", hoy)
    r = await indicadores.reporte(db, periodo, hoy)
    assert r.total.recibidos == 1 and r.total.improcedentes == 1


# ---------------------------------------------------------------------------
# Migración de los casos anteriores
# ---------------------------------------------------------------------------


async def test_migracion_idempotente_de_casos_anteriores(
    db: aiosqlite.Connection,
) -> None:
    async def viejo(estado: str, sentido: str, recomendado: str | None) -> int:
        cur = await db.execute(
            "INSERT INTO casos (chat_id, user_id, direccion, estado, sentido,"
            " recomendado) VALUES (1, 1, 'ciencias_naturales', ?, ?, ?)",
            (estado, sentido, recomendado),
        )
        return int(cur.lastrowid or 0)

    abierto = await viejo("abierto", "pendiente", None)
    listo = await viejo("listo", "aprobar", "2026-09-10 15:00:00")
    sin_fecha = await viejo("cerrado", "no_aprobar", None)
    descartado = await viejo("descartado", "pendiente", None)
    decidido = await viejo("decidido_consejo", "aprobar", "2026-09-10 15:00:00")
    await db.execute(
        "INSERT INTO actas_consejo (id, instancia, numero, fecha, texto, subido_por)"
        " VALUES (1, 'facultad', '35', '2026-09-17', 'acta ficticia', 'x')"
    )
    await db.execute(
        "INSERT INTO decisiones_consejo (caso_id, acta_id, decision_id, instancia,"
        " sentido, texto_decision, acta_numero, acta_fecha, fragmento,"
        " confirmado_por) VALUES (?, 1, 1, 'facultad', 'aprobo', 't', '35',"
        " '2026-09-17', 'f', 'x')",
        (decidido,),
    )
    await db.execute(
        "INSERT INTO notificaciones (caso_id, numero, fecha_expedicion,"
        " registrado_por) VALUES (?, 'N-1', '2026-09-20', 'x')",
        (decidido,),
    )
    await db.commit()

    assert await flujo.migrar(db) == 5
    await db.commit()
    assert await flujo.migrar(db) == 0  # idempotente
    db2 = await connect()  # abrir la base también migra, sin duplicar
    await db2.close()
    esperado = {
        abierto: Etapa.LLEGADA,
        listo: Etapa.RECOMENDADA,
        sin_fecha: Etapa.EN_CONSEJO,
        descartado: Etapa.DESCARTADA,
        decidido: Etapa.EXPEDIDA,
    }
    for caso, etapa in esperado.items():
        assert await _etapa(db, caso) == etapa
    cur = await db.execute("SELECT COUNT(*) FROM caso_eventos")
    total = (await cur.fetchone())[0]
    assert total == 1 + 3 + 4 + 2 + 5
    # La fecha guardada se conserva; la que no existía no se inventa.
    evs = {e.accion: e for e in await flujo.eventos(db, listo)}
    assert evs[Accion.RECOMENDAR].fecha == "2026-09-10 15:00:00"
    evs = {e.accion: e for e in await flujo.eventos(db, sin_fecha)}
    assert evs[Accion.RECOMENDAR].fecha is None
    assert evs[Accion.ENVIAR_CONSEJO].fecha is None
    evs = {e.accion: e for e in await flujo.eventos(db, decidido)}
    assert evs[Accion.DECIDIR].fecha == "2026-09-17"
    assert all(e.canal == "migracion" for e in evs.values())


# ---------------------------------------------------------------------------
# Telegram y la web: la misma ficha y la misma línea
# ---------------------------------------------------------------------------


async def test_telegram_y_web_escriben_la_misma_linea(
    db: aiosqlite.Connection,
    tg: TelegramFalso,
    estructurador: EstructuradorFalso,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    cliente: Cliente,  # noqa: F811
) -> None:
    await _registrar(db, monkeypatch)
    await bot.manejar_update(db, _update(text="Correo ficticio"))
    await bot.manejar_update(db, _update(text="/listo"))
    await bot.manejar_update(db, _callback("pr:1:procedente"))
    assert "procedente" in (tg.callbacks[-1] or "")

    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", "ciencias_naturales")
    ruta = "/api/web/actas/casos/1"
    r = c.post(ruta + "/recomendacion", json={"sentido": "aprobar"}, headers=adm)
    assert r.status_code == 200
    await bot.manejar_update(db, _callback("cerrar:ing_fisica"))

    ficha = c.get(ruta, headers=adm).json()
    assert ficha["etapa"] == "en_consejo"
    canales = [e["canal"] for e in ficha["linea"]]
    assert canales == ["telegram", "sistema", "telegram", "web", "telegram"]
    assert ficha["siguiente"]["paso"].startswith("Decisión del")
    assert "Consejo" in ficha["siguiente"]["responsable"]
    assert ficha["tramos"][0]["dias"] is None  # aún sin decisión
    # Ya en el Consejo, el botón de Telegram no cambia la recomendación.
    await bot.manejar_update(db, _callback("s:1:no_aprobar"))
    assert "en el consejo" in (tg.callbacks[-1] or "")
    assert (await repo.get_caso(db, 1)).sentido == Sentido.APROBAR  # type: ignore[union-attr]
    r = c.post(ruta + "/recomendacion", json={"sentido": "no_aprobar"}, headers=adm)
    assert r.status_code == 409
    r = c.post(ruta + "/volver-al-comite", headers=adm)
    assert r.json()["etapa"] == "recomendada"
    assert "enviar_consejo" in r.json()["acciones"]


def test_indicador_principal_de_la_solicitud_a_la_decision() -> None:
    def fila(consejo: SentidoConsejo | None, acta: date | None) -> indicadores.FilaCaso:
        return indicadores.FilaCaso(
            direccion="ciencias_naturales",
            programa="P",
            tipo="T",
            instancia="Consejo de Facultad",
            recibido=date(2026, 9, 1),
            solicitud=date(2026, 9, 1),
            recomendado=date(2026, 9, 5),
            sentido=Sentido.APROBAR,
            consejo=consejo,
            acta_fecha=acta,
        )

    filas = [
        fila(SentidoConsejo.APROBO, date(2026, 9, 11)),
        fila(SentidoConsejo.NO_APROBO, date(2026, 9, 21)),
        fila(SentidoConsejo.APLAZO, date(2026, 9, 30)),  # no es decisión
        fila(None, None),
    ]
    r = indicadores.calcular(filas, date(2026, 10, 1), solicitudes.Plazos())
    assert r.dias_total.casos == 2 and r.dias_total.mediana == 15
    assert r.valor("dias_total_p90") == 20
