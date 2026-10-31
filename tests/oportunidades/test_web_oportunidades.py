"""API web y cron de oportunidades de punta a punta, con fuentes y modelo falsos."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.servicios.oportunidades.config import config
from tests.oportunidades.conftest import Falsos, dia
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

R = "/api/web/oportunidades"
REVISOR = "revisor.ficticio@unal.edu.co"


@pytest.fixture
def c(cliente: Cliente) -> TestClient:  # noqa: F811
    return cliente("oportunidades")


async def _cab(rol: str, correo: str = REVISOR) -> dict[str, str]:
    return await _token(correo, rol)


def _ofertas(c: TestClient, cab: dict[str, str], **params: str) -> dict[str, Any]:
    r = c.get(f"{R}/ofertas", params=params, headers=cab)
    assert r.status_code == 200, r.text
    return {o["titulo"]: o for o in r.json()["ofertas"]}


async def test_flujo_completo_desde_la_web(c: TestClient, falsos: Falsos) -> None:
    cab = await _cab("oportunidades")

    # 1. Vigía (en segundo plano: TestClient la corre al responder).
    r = c.post(f"{R}/vigia", headers=cab)
    assert r.status_code == 200, r.text
    corridas = c.get(f"{R}/corridas", headers=cab).json()["corridas"]
    assert corridas[0]["estado"] == "terminada"
    assert corridas[0]["nuevas"] == 4
    assert corridas[0]["costo_usd"] > 0

    # 2. Cola de revisión con motivos.
    cola = c.get(f"{R}/cola", headers=cab).json()["ofertas"]
    assert {o["titulo"] for o in cola} == {
        "Analista junior",
        "Pasantía vencida",
        "Beca inventada",
    }
    assert all(o["motivos"] for o in cola)

    ofertas = _ofertas(c, cab)
    buena = ofertas["Practicante de estadística"]["id"]
    analista = ofertas["Analista junior"]["id"]
    vencida = ofertas["Pasantía vencida"]["id"]

    # 3. Revisión humana.
    assert (
        c.post(f"{R}/ofertas/{analista}/verificar", json={}, headers=cab).status_code
        == 409
    )
    r = c.post(
        f"{R}/ofertas/{analista}/verificar",
        json={"nota": "Revisé el enlace y el programa."},
        headers=cab,
    )
    assert r.status_code == 200, r.text
    assert c.post(f"{R}/ofertas/{vencida}/aprobar", headers=cab).status_code == 409
    r = c.post(
        f"{R}/ofertas/{vencida}/descartar", json={"motivo": "Ya cerró."}, headers=cab
    )
    assert r.status_code == 200
    for oferta_id in (buena, analista):
        assert (
            c.post(f"{R}/ofertas/{oferta_id}/aprobar", headers=cab).status_code == 200
        )

    detalle = c.get(f"{R}/ofertas/{analista}", headers=cab).json()
    assert detalle["oferta"]["verificado_por"] == REVISOR
    assert detalle["oferta"]["aprobado_por"] == REVISOR
    assert [h["a_estado"] for h in detalle["historial"]] == [
        "encontrada",
        "verificada",
        "aprobada",
    ]

    # 4. Borrador del boletín y «Aprobar y publicar».
    r = c.post(f"{R}/boletin/borrador", headers=cab)
    assert r.json()["ofertas"] == 2
    hoja = c.get(f"{R}/boletin", headers=cab).json()["boletin"]
    assert hoja["estado"] == "borrador"
    r = c.post(f"{R}/boletin/{hoja['id']}/aprobar", headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["boletin"]["aprobado_por"] == REVISOR
    assert c.post(f"{R}/boletin/{hoja['id']}/aprobar", headers=cab).status_code == 409

    publicadas = _ofertas(c, cab, estado="publicada")
    assert set(publicadas) == {"Practicante de estadística", "Analista junior"}

    # 5. Exportar para el correo (MemorIA no lo envía).
    texto = c.get(f"{R}/boletin/{hoja['id']}/exportar", headers=cab)
    assert texto.headers["content-type"].startswith("text/plain")
    assert "Practicante de estadística" in texto.text
    html = c.get(
        f"{R}/boletin/{hoja['id']}/exportar", params={"formato": "html"}, headers=cab
    )
    assert html.headers["content-type"].startswith("text/html")
    assert '<a href="https://alfa.invalid/ofertas/101">' in html.text

    resumen = c.get(f"{R}/resumen", headers=cab).json()
    assert resumen["por_estado"]["publicada"] == 2
    assert resumen["por_estado"]["descartada"] == 1


async def test_decanatura_consulta_pero_no_decide(
    c: TestClient, falsos: Falsos
) -> None:
    resp = await _cab("oportunidades")
    c.post(f"{R}/vigia", headers=resp)
    cab = await _cab("decanatura", "decana.ficticia@unal.edu.co")
    assert c.get(f"{R}/cola", headers=cab).status_code == 200
    assert c.get(f"{R}/boletin", headers=cab).status_code == 200
    oferta_id = next(iter(_ofertas(c, cab).values()))["id"]
    for ruta, cuerpo in (
        (f"{R}/ofertas/{oferta_id}/aprobar", None),
        (f"{R}/ofertas/{oferta_id}/verificar", {"nota": "x"}),
        (f"{R}/ofertas/{oferta_id}/descartar", {"motivo": "xyz"}),
        (f"{R}/boletin/borrador", None),
        (f"{R}/vigia", None),
    ):
        assert c.post(ruta, json=cuerpo, headers=cab).status_code == 403, ruta


async def test_otros_roles_no_entran(c: TestClient) -> None:
    from app.api.web import auth

    token = auth.sesion_de(auth.Usuario("x@unal.edu.co", None, "calidad", None))
    r = c.get(f"{R}/cola", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_registro_manual_y_entidades(c: TestClient, falsos: Falsos) -> None:
    cab = await _cab("oportunidades")
    r = c.post(
        f"{R}/entidades",
        json={"nombre": "Empresa Ficticia Aliada", "aliada": True, "sector": "Datos"},
        headers=cab,
    )
    assert r.status_code == 200, r.text
    assert (
        c.post(
            f"{R}/entidades", json={"nombre": "empresa ficticia aliada"}, headers=cab
        ).status_code
        == 409
    )

    r = c.post(
        f"{R}/ofertas",
        json={
            "titulo": "Práctica en modelación",
            "entidad": "Empresa Ficticia Aliada",
            "tipo": "practica",
            "url": "https://aliada.invalid/practica",
            "programas": ["matematicas"],
            "fecha_cierre": dia(15).isoformat(),
        },
        headers=cab,
    )
    assert r.status_code == 200, r.text
    # Registrada a mano: el enlace queda por comprobar y va a la cola.
    assert r.json()["motivos"] == ["enlace_vivo: sin comprobar (revisión sin red)"]
    (entidad,) = c.get(f"{R}/entidades", headers=cab).json()["entidades"]
    assert entidad["ofertas"] == 1

    r = c.post(f"{R}/ofertas", json={"titulo": "Xyz", "entidad": "Ab", "tipo": "beca",
               "url": "https://a.invalid", "programas": ["no_existe"]}, headers=cab)  # fmt: skip
    assert r.status_code == 400


async def test_editar_oferta_aprobada_la_devuelve_a_la_cola(
    c: TestClient, falsos: Falsos
) -> None:
    cab = await _cab("oportunidades")
    c.post(f"{R}/vigia", headers=cab)
    buena = _ofertas(c, cab)["Practicante de estadística"]["id"]
    c.post(f"{R}/ofertas/{buena}/aprobar", headers=cab)
    r = c.put(
        f"{R}/ofertas/{buena}", json={"fecha_cierre": dia(10).isoformat()}, headers=cab
    )
    assert r.status_code == 200, r.text
    oferta = c.get(f"{R}/ofertas/{buena}", headers=cab).json()["oferta"]
    assert oferta["estado"] == "encontrada" and oferta["aprobado_por"] is None


async def test_fuentes_muestra_activas_y_excluidas(
    c: TestClient, falsos: Falsos
) -> None:
    cab = await _cab("oportunidades")
    datos = c.get(f"{R}/fuentes", headers=cab).json()
    assert [f["clave"] for f in datos["fuentes"] if f["activa"]] == [
        "portal_alfa",
        "portal_beta",
        "portal_gamma",
    ]
    assert datos["excluidas"][0]["nombre"] == "Portal privado ficticio"


# ---------------------------------------------------------------------------
# Cron semanal
# ---------------------------------------------------------------------------


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(settings, "internal_cron_secret", "cron-prueba")
    monkeypatch.setattr(settings, "bot_servicio", "oportunidades")
    return {"X-Cron-Secret": "cron-prueba"}


def test_cron_exige_el_secreto(cron: dict[str, str]) -> None:
    with TestClient(app) as client:
        r = client.post("/internal/vigia-semanal", headers={"X-Cron-Secret": "otro"})
    assert r.status_code == 403


def test_cron_apagado_no_busca(cron: dict[str, str], falsos: Falsos) -> None:
    with TestClient(app) as client:
        r = client.post("/internal/vigia-semanal", headers=cron)
    assert r.json() == {"ok": True, "activo": False}
    assert falsos.transporte.pedidos == []


def test_cron_activo_corre_la_vigia(
    cron: dict[str, str], falsos: Falsos, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "vigia_activa", True)
    with TestClient(app) as client:
        r = client.post("/internal/vigia-semanal", headers=cron)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["activo"] is True and datos["nuevas"] == 4
    assert datos["boletin"]["estado"] == "borrador"


@pytest.mark.parametrize("servicio", ["actas", "calidad"])
def test_cron_no_aplica_a_otros_servicios(
    servicio: str, cron: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "bot_servicio", servicio)
    with TestClient(app) as client:
        r = client.post("/internal/vigia-semanal", headers=cron)
    assert r.status_code == 404


async def test_tablero_para_la_decanatura(c: TestClient, falsos: Falsos) -> None:
    c.post(f"{R}/vigia", headers=await _cab("oportunidades"))
    cab = await _cab("decanatura", "decana.ficticia@unal.edu.co")
    datos = c.get(f"{R}/tablero", headers=cab).json()
    assert datos["total"]["Verificada"] == 1
    estadistica = next(p for p in datos["por_programa"] if p["nombre"] == "Estadística")
    assert estadistica["conteo"]["Verificada"] == 1
