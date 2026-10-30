"""Acta del Consejo: lectura literal, cruce determinista, cola de revisión y
confirmación por una persona.

El acta es ficticia (tests/fixtures/consejo/) y el modelo es un falso que
devuelve lo que una lectura correcta copiaría, más un fragmento inventado.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web import auth, crear_router
from app.api.web.config import web_settings
from app.core.config import settings
from app.db import repo
from app.integrations.claude import Resultado
from app.schemas.caso import EstadoCaso, Sentido
from app.schemas.consejo import (
    ActaLeida,
    Cruce,
    DecisionLeida,
    EstadoDecision,
    Instancia,
    SentidoConsejo,
)
from app.schemas.telegram import Update
from app.services import bot, consejo, extraccion, formatos, resumen
from tests.conftest import TelegramFalso, extraccion_ejemplo

ACTA = Path(__file__).parent / "fixtures" / "consejo" / "acta_consejo_ficticia.docx"
DIRECCION = "ciencias_naturales"
USUARIO = 555

F_UNO = (
    "4.1 Persona Ficticia Uno, documento 1000000001, caso MemorIA #1, Ingeniería "
    "Física. Solicita la cancelación de la asignatura Termodinámica. Decisión: "
    "APROBADO."
)
F_DOS = (
    "4.2 Persona Ficticia Dos, documento 1000000002, Física. Solicita reingreso. "
    "Decisión: El Consejo no aprueba la solicitud."
)
F_TRES = (
    "4.3 Persona Ficticia Tres, Matemáticas. Solicita carga mínima. Decisión: Se "
    "aplaza para la próxima sesión."
)
F_AUSENTE = (
    "4.4 Estudiante Ficticio Ausente, documento 1999999999, Química. Solicita "
    "traslado. Decisión: APROBADO."
)
# El modelo «mejoró» la redacción: ya no es literal.
F_INVENTADO = "Persona Ficticia Cuatro: el Consejo aprueba su solicitud de traslado."


def leida_ficticia() -> ActaLeida:
    return ActaLeida(
        numero_acta="099",
        fecha_acta="2026-11-05",
        instancia_texto="CONSEJO DE FACULTAD DE CIENCIAS EXACTAS Y NATURALES",
        decisiones=[
            DecisionLeida(
                nombre_estudiante="Persona Ficticia Uno",
                documento="1000000001",
                numero_caso="#1",
                texto_decision="APROBADO",
                fragmento=F_UNO,
            ),
            DecisionLeida(
                nombre_estudiante="Persona Ficticia Dos",
                documento="1000000002",
                texto_decision="El Consejo no aprueba la solicitud",
                fragmento=F_DOS,
            ),
            DecisionLeida(
                nombre_estudiante="Persona Ficticia Tres",
                texto_decision="Se aplaza",
                fragmento=F_TRES,
            ),
            DecisionLeida(
                nombre_estudiante="Estudiante Ficticio Ausente",
                documento="1999999999",
                texto_decision="APROBADO",
                fragmento=F_AUSENTE,
            ),
            DecisionLeida(
                nombre_estudiante="Persona Ficticia Cuatro",
                documento="1000000004",
                texto_decision="el Consejo aprueba",
                fragmento=F_INVENTADO,
            ),
        ],
    )


class EstructuradorFalso:
    def __init__(self, salida: ActaLeida) -> None:
        self.salida = salida
        self.llamadas: list[dict[str, Any]] = []

    async def extraer(self, **kw: Any) -> Resultado:
        self.llamadas.append(kw)
        return Resultado(self.salida, 3000, 900)


@pytest.fixture
def modelo() -> Any:
    falso = EstructuradorFalso(leida_ficticia())
    extraccion.set_estructurador(falso)  # type: ignore[arg-type]
    yield falso
    extraccion.set_estructurador(None)


async def _caso(
    db: aiosqlite.Connection,
    nombre: str,
    documento: str,
    *,
    sentido: Sentido = Sentido.APROBAR,
    direccion: str = DIRECCION,
    chat_id: int = USUARIO,
) -> int:
    caso_id = await repo.crear_caso(
        db, chat_id=chat_id, user_id=chat_id, direccion=direccion
    )
    await repo.guardar_extraccion(
        db,
        caso_id,
        extraccion_ejemplo(nombre_estudiante=nombre, documento=documento),
        "ing_fisica",
    )
    await repo.set_sentido(db, caso_id, sentido)
    return caso_id


async def _escenario(db: aiosqlite.Connection) -> list[int]:
    return [
        await _caso(db, "Persona Ficticia Uno", "1000000001"),
        await _caso(
            db, "Persona Ficticia Dos", "1000000002", sentido=Sentido.NO_APROBAR
        ),
        await _caso(db, "Persona Ficticia Tres", "1000000003"),
        await _caso(db, "Persona Ficticia Cuatro", "1000000004"),
    ]


async def _registrar(db: aiosqlite.Connection) -> consejo.ActaRegistrada:
    return await consejo.leer_y_registrar(
        db,
        datos=ACTA.read_bytes(),
        nombre_archivo=ACTA.name,
        direccion=DIRECCION,
        instancia=None,
        subido_por="Administrativa Ficticia",
    )


# ---------------------------------------------------------------------------
# Reglas fijas
# ---------------------------------------------------------------------------


def test_el_acta_ficticia_contiene_los_fragmentos() -> None:
    texto = formatos.texto_docx(ACTA.read_bytes())
    for f in (F_UNO, F_DOS, F_TRES, F_AUSENTE):
        assert consejo.es_literal(f, texto)
    assert not consejo.es_literal(F_INVENTADO, texto)
    assert "Ficticio" in texto


@pytest.mark.parametrize(
    ("texto", "sentido"),
    [
        ("APROBADO", SentidoConsejo.APROBO),
        ("El Consejo aprueba", SentidoConsejo.APROBO),
        ("El Consejo no aprueba la solicitud", SentidoConsejo.NO_APROBO),
        ("NO APROBADO", SentidoConsejo.NO_APROBO),
        ("Se niega", SentidoConsejo.NO_APROBO),
        ("Se aplaza para la próxima sesión", SentidoConsejo.APLAZO),
        ("Se remite a la Dirección de Bienestar", SentidoConsejo.OTRO),
    ],
)
def test_sentido_sale_del_texto_literal(texto: str, sentido: SentidoConsejo) -> None:
    assert consejo.sentido_de(texto) == sentido


def test_instancia() -> None:
    facultad = "CONSEJO DE FACULTAD DE CIENCIAS EXACTAS Y NATURALES, Sede Manizales"
    assert consejo.instancia_de(facultad) == Instancia.FACULTAD
    assert consejo.instancia_de("Consejo de Sede Manizales") == Instancia.SEDE
    assert consejo.instancia_de("Consejo Superior Universitario") == Instancia.SUPERIOR
    assert consejo.instancia_de("Comité de Matrículas") is None


def test_literal_tolera_solo_espacios() -> None:
    acta = "Decisión:   APROBADO.\nSe levanta la sesión."
    assert consejo.es_literal("Decisión: APROBADO.", acta)
    assert not consejo.es_literal("Decision: APROBADO.", acta)  # sin tilde
    assert not consejo.es_literal("Decisión: Aprobado.", acta)
    assert not consejo.es_literal("", acta)


# ---------------------------------------------------------------------------
# Cruce
# ---------------------------------------------------------------------------


async def test_cruce_del_acta_ficticia(db: aiosqlite.Connection, modelo: Any) -> None:
    uno, dos, tres, cuatro = await _escenario(db)
    registrada = await _registrar(db)
    p = registrada.propuestas
    assert len(modelo.llamadas) == 1
    assert modelo.llamadas[0]["nombre_herramienta"] == "registrar_acta"

    # Cruce exacto: documento y número de caso coinciden con un solo caso.
    assert (p[0].cruce, p[0].caso_id, p[0].sentido) == (
        Cruce.EXACTO,
        uno,
        SentidoConsejo.APROBO,
    )
    assert (p[1].cruce, p[1].caso_id, p[1].sentido) == (
        Cruce.EXACTO,
        dos,
        SentidoConsejo.NO_APROBO,
    )
    # Caso dudoso: solo el nombre; va a la cola con su candidato.
    assert p[2].cruce == Cruce.DUDOSO
    assert p[2].caso_id is None and p[2].candidatos == (tres,)
    assert "Solo coincide el nombre" in (p[2].motivo or "")
    # Decisión sin caso en MemorIA.
    assert p[3].cruce == Cruce.SIN_CASO and p[3].candidatos == ()
    # Fragmento que no está en el acta: no se puede aplicar.
    assert p[4].cruce == Cruce.NO_VERIFICADO
    assert p[4].caso_id is None

    acta = await consejo.get_acta(db, registrada.acta_id)
    assert acta is not None
    assert (acta.instancia, acta.numero, acta.fecha) == (
        Instancia.FACULTAD,
        "099",
        "2026-11-05",
    )
    # Recomendado que no aparece en el acta: el del fragmento inventado no
    # cuenta como aparición (no se cruzó contra nada).
    faltan = await consejo.no_aparecieron(db, registrada.acta_id, DIRECCION)
    assert [c.id for c in faltan] == [cuatro]


async def test_nada_se_aplica_sin_confirmacion(
    db: aiosqlite.Connection, modelo: Any
) -> None:
    uno, *_ = await _escenario(db)
    registrada = await _registrar(db)
    caso = await repo.get_caso(db, uno)
    assert caso is not None
    assert caso.estado == EstadoCaso.LISTO and caso.consejo is None
    cur = await db.execute("SELECT COUNT(*) FROM decisiones_consejo")
    assert (await cur.fetchone())[0] == 0  # type: ignore[index]
    cifras = await resumen.cifras_actas(db, datetime(2026, 11, 6, tzinfo=UTC))
    assert cifras.total.pendientes_acta_consejo == 4
    assert cifras.total.decididos_consejo == 0

    # Una persona confirma: solo entonces se registra.
    filas = await consejo.decisiones_del_acta(db, registrada.acta_id)
    await consejo.aplicar(
        db, filas[0].id, caso_id=None, persona="Administrativa", direccion=DIRECCION
    )
    caso = await repo.get_caso(db, uno)
    assert caso is not None and caso.consejo is not None
    assert caso.estado == EstadoCaso.DECIDIDO_CONSEJO
    assert caso.consejo.sentido == SentidoConsejo.APROBO
    assert caso.consejo.texto_decision == "APROBADO"
    assert caso.consejo.fragmento == F_UNO
    assert caso.consejo.acta_numero == "099"
    assert caso.consejo.instancia == Instancia.FACULTAD
    assert caso.consejo.confirmado_por == "Administrativa"
    # No se confirma dos veces.
    with pytest.raises(consejo.ErrorActa):
        await consejo.aplicar(
            db, filas[0].id, caso_id=None, persona="Otra", direccion=DIRECCION
        )


async def test_dudoso_exige_elegir_el_caso(
    db: aiosqlite.Connection, modelo: Any
) -> None:
    _, _, tres, _ = await _escenario(db)
    registrada = await _registrar(db)
    filas = await consejo.decisiones_del_acta(db, registrada.acta_id)
    with pytest.raises(consejo.ErrorActa, match="Elija el caso"):
        await consejo.aplicar(
            db, filas[2].id, caso_id=None, persona="A", direccion=DIRECCION
        )
    decision = await consejo.aplicar(
        db, filas[2].id, caso_id=tres, persona="A", direccion=DIRECCION
    )
    assert decision.sentido == SentidoConsejo.APLAZO


async def test_fragmento_no_literal_no_se_aplica(
    db: aiosqlite.Connection, modelo: Any
) -> None:
    *_, cuatro = await _escenario(db)
    registrada = await _registrar(db)
    filas = await consejo.decisiones_del_acta(db, registrada.acta_id)
    with pytest.raises(consejo.ErrorActa, match="literal"):
        await consejo.aplicar(
            db, filas[4].id, caso_id=cuatro, persona="A", direccion=DIRECCION
        )
    await consejo.descartar(db, filas[4].id, persona="A", direccion=DIRECCION)
    filas = await consejo.decisiones_del_acta(db, registrada.acta_id)
    assert filas[4].estado == EstadoDecision.DESCARTADA
    assert (await repo.get_caso(db, cuatro)).consejo is None  # type: ignore[union-attr]


async def test_otra_area_no_cruza_ni_se_aplica(
    db: aiosqlite.Connection, modelo: Any
) -> None:
    ajeno = await _caso(
        db, "Persona Ficticia Uno", "1000000001", direccion="matematicas"
    )
    registrada = await _registrar(db)
    assert registrada.propuestas[0].cruce == Cruce.SIN_CASO
    filas = await consejo.decisiones_del_acta(db, registrada.acta_id)
    with pytest.raises(consejo.ErrorActa):
        await consejo.aplicar(
            db, filas[0].id, caso_id=ajeno, persona="A", direccion=DIRECCION
        )


def test_dos_decisiones_al_mismo_caso_van_a_la_cola() -> None:
    from app.schemas.caso import Caso

    caso = Caso(
        id=7,
        chat_id=1,
        direccion=DIRECCION,
        estado=EstadoCaso.LISTO,
        extraccion=extraccion_ejemplo(
            nombre_estudiante="Persona Ficticia Siete", documento="1000000007"
        ),
    )
    texto = (
        "Persona Ficticia Siete, 1000000007: APROBADO. Persona Ficticia Siete: NIEGA."
    )
    leidas = [
        DecisionLeida(
            nombre_estudiante="Persona Ficticia Siete",
            documento="1000000007",
            texto_decision="APROBADO",
            fragmento="Persona Ficticia Siete, 1000000007: APROBADO.",
        ),
        DecisionLeida(
            nombre_estudiante="Persona Ficticia Siete",
            documento="1000000007",
            texto_decision="NIEGA",
            fragmento="Persona Ficticia Siete: NIEGA.",
        ),
    ]
    propuestas = consejo.cruzar(leidas, [caso], texto)
    assert [p.cruce for p in propuestas] == [Cruce.DUDOSO, Cruce.DUDOSO]
    # Documento distinto con el mismo nombre: conflicto, a la cola.
    otro = DecisionLeida(
        nombre_estudiante="Persona Ficticia Siete",
        documento="1000000099",
        texto_decision="APROBADO",
        fragmento="Persona Ficticia Siete, 1000000007: APROBADO.",
    )
    (p,) = consejo.cruzar([otro], [caso], texto)
    assert p.cruce == Cruce.DUDOSO and "documento" in (p.motivo or "")


# ---------------------------------------------------------------------------
# Resumen y aviso
# ---------------------------------------------------------------------------


async def test_resumen_cuenta_lo_que_decidio_el_consejo(
    db: aiosqlite.Connection, modelo: Any
) -> None:
    _, _, tres, _ = await _escenario(db)
    registrada = await _registrar(db)
    await consejo.aplicar_exactos(
        db, registrada.acta_id, persona="A", direccion=DIRECCION
    )
    filas = await consejo.decisiones_del_acta(db, registrada.acta_id)
    await consejo.aplicar(db, filas[2].id, caso_id=tres, persona="A", direccion=None)
    cifras = await resumen.cifras_actas(db, datetime(2026, 11, 6, tzinfo=UTC))
    t = cifras.total
    assert (t.consejo_aprobo, t.consejo_no_aprobo, t.consejo_aplazo) == (1, 1, 1)
    assert t.decididos_consejo == 2
    # 4 recomendados − 2 decididos; el aplazado sigue pendiente.
    assert t.pendientes_acta_consejo == 2
    texto = resumen.formatear(cifras, date(2026, 11, 6))
    assert "2 pendientes de acta del Consejo · 2 decididos por el Consejo" in texto
    assert "Según el acta del Consejo: aprobó 1, no aprobó 1, aplazó 1." in texto
    assert "Ficticia" not in texto


async def test_aviso_por_telegram_solo_con_el_interruptor(
    db: aiosqlite.Connection,
    modelo: Any,
    tg: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await repo.registrar_usuario(db, USUARIO, "Administrativa Ficticia")
    await repo.asignar_direccion(db, USUARIO, DIRECCION)
    await _escenario(db)
    registrada = await _registrar(db)
    filas = await consejo.decisiones_del_acta(db, registrada.acta_id)

    monkeypatch.setattr(settings, "aviso_consejo_telegram", False)
    await consejo.aplicar(db, filas[0].id, caso_id=None, persona="A", direccion=None)
    assert tg.mensajes == []

    monkeypatch.setattr(settings, "aviso_consejo_telegram", True)
    await consejo.aplicar(db, filas[1].id, caso_id=None, persona="A", direccion=None)
    assert len(tg.mensajes) == 1
    aviso = tg.mensajes[0]
    assert aviso["chat_id"] == USUARIO
    assert "Decisión del Consejo · caso #2" in aviso["texto"]
    assert "no aprobó" in aviso["texto"]
    assert "El Consejo no aprueba la solicitud" in aviso["texto"]


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

_n = 0


def _update(**mensaje: Any) -> Update:
    global _n
    _n += 1
    base = {
        "message_id": _n,
        "chat": {"id": USUARIO, "type": "private"},
        "from": {"id": USUARIO, "first_name": "Ana", "last_name": "Prueba"},
    }
    base.update(mensaje)
    return Update.model_validate({"update_id": 70_000 + _n, "message": base})


def _callback(data: str) -> Update:
    global _n
    _n += 1
    return Update.model_validate(
        {
            "update_id": 70_000 + _n,
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


async def test_acta_consejo_por_telegram(
    db: aiosqlite.Connection,
    modelo: Any,
    tg: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await repo.registrar_usuario(db, USUARIO, "Ana Prueba")
    await repo.asignar_direccion(db, USUARIO, DIRECCION)
    uno, dos, tres, _ = await _escenario(db)

    async def acta(file_id: str, **kw: Any) -> bytes:
        return ACTA.read_bytes()

    monkeypatch.setattr(tg, "descargar_archivo", acta)
    from app.integrations import telegram

    monkeypatch.setattr(telegram, "descargar_archivo", acta)

    await bot.manejar_update(db, _update(text="/acta_consejo"))
    assert "Envíe el acta del Consejo" in tg.textos()[-1]
    await bot.manejar_update(
        db,
        _update(
            document={
                "file_id": "f1",
                "file_unique_id": "u1",
                "file_name": "acta_099.docx",
                "file_size": 10_000,
            }
        ),
    )
    resumen_acta = tg.mensajes[-1]
    assert "Cruzaron: 2 · En duda: 2 · Sin caso: 1" in resumen_acta["texto"]
    assert "Nada se ha registrado todavía." in resumen_acta["texto"]
    boton = resumen_acta["botones"][0][0]
    assert boton["text"] == "Confirmar 2 cruce(s)"
    # El documento no se agregó a ningún caso.
    assert (await repo.get_estado(db, USUARIO)).esperando is None
    assert (await repo.get_caso(db, uno)).consejo is None  # type: ignore[union-attr]

    await bot.manejar_update(db, _callback(boton["callback_data"]))
    assert f"#{uno}, #{dos}" in tg.textos()[-1]
    assert (await repo.get_caso(db, uno)).consejo is not None  # type: ignore[union-attr]
    assert (await repo.get_caso(db, tres)).consejo is None  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(web_settings, "session_secret", "secreto-de-prueba")
    monkeypatch.setattr(web_settings, "admins", "admin@unal.edu.co")
    monkeypatch.setattr(web_settings, "auth_dev", False)
    monkeypatch.setattr(settings, "bot_servicio", "actas")
    app = FastAPI()
    app.include_router(crear_router("actas"))
    return TestClient(app)


async def _cabecera(
    db: aiosqlite.Connection, correo: str, rol: str, direccion: str | None
) -> dict[str, str]:
    await db.execute(auth._ESQUEMA)
    await db.execute(
        "INSERT INTO web_usuarios (correo, rol, direccion) VALUES (?, ?, ?)",
        (correo, rol, direccion),
    )
    await db.commit()
    usuario = auth.Usuario(correo, None, rol, direccion)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {auth.sesion_de(usuario)}"}


async def test_pantalla_acta_del_consejo(
    db: aiosqlite.Connection, modelo: Any, web: TestClient
) -> None:
    uno, dos, tres, cuatro = await _escenario(db)
    adm = await _cabecera(db, "adm@unal.edu.co", "administrativa", DIRECCION)
    comite = await _cabecera(db, "com@unal.edu.co", "comite", DIRECCION)
    base = "/api/web/actas/consejo"

    with ACTA.open("rb") as f:
        r = web.post(base, headers=comite, files={"archivo": (ACTA.name, f.read())})
    assert r.status_code == 403

    r = web.post(
        base,
        headers=adm,
        files={"archivo": (ACTA.name, ACTA.read_bytes())},
        data={"instancia": "facultad"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    acta_id = d["id"]
    assert d["instancia_texto"] == "Consejo de Facultad"
    assert [f["caso"]["id"] for f in d["cruzaron"]] == [uno, dos]
    assert [f["cruce"] for f in d["en_duda"]] == ["dudoso", "no_verificado"]
    assert d["en_duda"][0]["candidatos"][0]["id"] == tres
    assert [f["leida"]["nombre_estudiante"] for f in d["sin_caso"]] == [
        "Estudiante Ficticio Ausente"
    ]
    assert [c["id"] for c in d["no_aparecieron"]] == [cuatro]
    assert d["pendientes"] == 5
    # Subir no registra nada en el caso.
    r = web.get(f"/api/web/actas/casos/{uno}", headers=adm)
    assert r.json()["consejo"] is None

    r = web.post(f"{base}/{acta_id}/confirmar-exactos", headers=adm)
    assert r.status_code == 200
    duda = r.json()["en_duda"]
    # Asignar a mano el caso dudoso.
    r = web.post(
        f"{base}/{acta_id}/decisiones/{duda[0]['id']}/confirmar",
        headers=adm,
        json={"caso_id": tres},
    )
    assert r.status_code == 200, r.text
    # El fragmento inventado no se puede confirmar; solo descartar.
    r = web.post(
        f"{base}/{acta_id}/decisiones/{duda[1]['id']}/confirmar",
        headers=adm,
        json={"caso_id": cuatro},
    )
    assert r.status_code == 409
    r = web.post(f"{base}/{acta_id}/decisiones/{duda[1]['id']}/descartar", headers=adm)
    assert r.status_code == 200
    assert r.json()["pendientes"] == 1  # queda la decisión sin caso

    r = web.get(f"/api/web/actas/casos/{uno}", headers=adm)
    consejo_uno = r.json()["consejo"]
    assert consejo_uno["sentido_texto"] == "Aprobó"
    assert consejo_uno["fragmento"] == F_UNO
    assert r.json()["estado"] == "decidido_consejo"

    r = web.get(base, headers=adm)
    assert r.json()["actas"][0]["pendientes"] == 1


async def test_admin_entra_y_otra_area_no_ve_el_acta(
    db: aiosqlite.Connection, modelo: Any, web: TestClient
) -> None:
    await _escenario(db)
    adm = await _cabecera(db, "adm@unal.edu.co", "administrativa", DIRECCION)
    otra = await _cabecera(db, "mat@unal.edu.co", "administrativa", "matematicas")
    admin = await _cabecera(db, "admin@unal.edu.co", "admin", None)
    r = web.post(
        "/api/web/actas/consejo",
        headers=adm,
        files={"archivo": (ACTA.name, ACTA.read_bytes())},
    )
    acta_id = r.json()["id"]
    assert web.get(f"/api/web/actas/consejo/{acta_id}", headers=otra).status_code == 404
    assert (
        web.get(f"/api/web/actas/consejo/{acta_id}", headers=admin).status_code == 200
    )
    r = web.post(
        "/api/web/actas/consejo",
        headers=adm,
        files={"archivo": ("acta.txt", b"hola")},
    )
    assert r.status_code == 400
