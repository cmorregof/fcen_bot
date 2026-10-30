"""Revisión de soportes desde la web, con soportes FICTICIOS y el modelo simulado.

Ninguna prueba llama a la API: `corrida.crear_cliente` se reemplaza por un
cliente falso que registra lo que se le pide.
"""

from __future__ import annotations

import io
import json
import stat
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.soportes import corrida
from app.servicios.calidad.soportes.carga import ZipNoValido, extraer
from app.servicios.calidad.soportes.cliente import ClienteConTope, Respuesta
from app.servicios.calidad.soportes.modelos import Uso
from tests.calidad.conftest import ALFA
from tests.calidad.test_soportes import imagen_ficticia, pdf_ficticio
from tests.web.test_web import Cliente, _token, cliente, web  # noqa: F401

RUTA = "/api/web/calidad/revisor"


class ModeloFalso:
    """Contesta cada herramienta con datos ficticios y cuenta las llamadas."""

    def __init__(self) -> None:
        self.llamadas: list[str] = []

    async def llamar(
        self,
        *,
        modelo: str,
        sistema: str,
        bloques: list[dict[str, Any]],
        texto: str,
        salida: type[BaseModel],
        nombre_herramienta: str,
        esfuerzo: str,
        max_tokens: int,
    ) -> Respuesta:
        self.llamadas.append(nombre_herramienta)
        if nombre_herramienta == "registrar_descripcion":
            datos: dict[str, Any] = {
                "que_es": "Acta ficticia",
                "fecha_documento": "2025-05",
                "que_prueba": "Una reunión del comité",
                "ilegible_o_incompleto": False,
                "observacion": "",
            }
        elif nombre_herramienta == "registrar_cruce":
            propios = texto.split("Documentos generales")[0]
            ids = [
                ln.split("]")[0][1:]
                for ln in propios.splitlines()
                if ln.startswith("[S")
            ]
            datos = {
                "veredicto": "evidencia suficiente" if ids else "sin evidencia",
                "justificacion": f"Según el acta [{ids[0]}]." if ids else "No hay.",
                "falta": "",
                "avance_propuesto": 100 if ids else 0,
                "citas": ids[:1],
                "parrafo_cierre": f"Se cumplió [{ids[0]}]." if ids else "Sin soportes.",
            }
        elif nombre_herramienta == "registrar_sugerencias":
            datos = {"sugerencias": []}
        else:
            datos = {"resumen": "Resumen ficticio."}
        return Respuesta(datos, 1000, 100, modelo=modelo)


@pytest.fixture
def falso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModeloFalso:
    modelo = ModeloFalso()
    monkeypatch.setattr(calidad_settings, "revisor_activo", True)
    monkeypatch.setattr(calidad_settings, "revisor_tope_usd", 10.0)
    monkeypatch.setattr(calidad_settings, "revisor_dir", tmp_path / "volumen")
    monkeypatch.setattr(corrida, "_tarea", None)
    monkeypatch.setattr(corrida, "_ocupado", False)
    monkeypatch.setattr(corrida, "crear_cliente", lambda: modelo)
    return modelo


def zip_ficticio() -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as zf:
        zf.writestr("Soportes/ACCIÓN 1.1.1/acta_ficticia.pdf", pdf_ficticio(2))
        zf.writestr("Soportes/ACCIÓN 1.1.1/foto_ficticia.png", imagen_ficticia())
        zf.writestr("Soportes/ACCIÓN 2.1.1/informe_ficticio.pdf", pdf_ficticio(1))
        zf.writestr("Soportes/ACCIÓN 9.9.9/de_otro_plan.pdf", pdf_ficticio(1))
        zf.writestr("Soportes/lineamientos_ficticios.pdf", pdf_ficticio(1))
        zf.writestr("Soportes/desktop.ini", b"[.ShellClassInfo]")
    return salida.getvalue()


async def _plan_cargado(c: TestClient, cab: dict[str, str]) -> None:
    archivo = {"archivo": ("plan.xlsx", ALFA.read_bytes())}
    r = c.post(
        "/api/web/calidad/importar",
        files=archivo,
        data={"confirmar": "true"},
        headers=cab,
    )
    assert r.status_code == 200 and r.json()["guardado"]


def _esperar(c: TestClient, cab: dict[str, str]) -> dict[str, Any]:
    for _ in range(400):
        estado: dict[str, Any] = c.get(RUTA, headers=cab).json()
        if estado["estado"] != "corriendo":
            return estado
        time.sleep(0.025)
    raise AssertionError("la corrida no terminó")


# ---------------------------------------------------------------------------
# Interruptor y roles
# ---------------------------------------------------------------------------


async def test_apagado_responde_403_con_el_aviso(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(calidad_settings, "revisor_activo", False)
    c = cliente("calidad")
    cab = await _token("lili@unal.edu.co", "calidad")
    for metodo, ruta in [
        ("GET", RUTA),
        ("POST", f"{RUTA}/soportes?programa=alfa"),
        ("POST", f"{RUTA}/correr"),
        ("GET", f"{RUTA}/descargar/borrador"),
        ("DELETE", RUTA),
    ]:
        r = c.request(metodo, ruta, headers=cab, content=zip_ficticio())
        assert r.status_code == 403, ruta
        assert "Pendiente del aval de tratamiento de datos" in r.json()["detail"]
    assert not corrida.base().exists()
    assert falso.llamadas == []


def test_apagado_por_defecto() -> None:
    assert type(calidad_settings).model_fields["revisor_activo"].default is False
    assert type(calidad_settings).model_fields["revisor_tope_usd"].default == 10.0


@pytest.mark.parametrize(
    ("rol", "esperado"),
    [("calidad", 200), ("admin", 200), ("decanatura", 403)],
)
async def test_solo_calidad_y_admin(
    rol: str,
    esperado: int,
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
) -> None:
    c = cliente("calidad")
    correo = "admin@unal.edu.co" if rol == "admin" else f"{rol}@unal.edu.co"
    cab = await _token(correo, rol)
    assert c.get(RUTA, headers=cab).status_code == esperado
    assert c.get(RUTA).status_code == 401


# ---------------------------------------------------------------------------
# Flujo completo
# ---------------------------------------------------------------------------


async def test_flujo_completo_con_cliente_falso(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
) -> None:
    with cliente("calidad") as c:
        cab = await _token("lili@unal.edu.co", "calidad")
        await _plan_cargado(c, cab)
        assert c.get(RUTA, headers=cab).json()["estado"] == "vacio"

        # Paso 1-2: subir y estimar. No llama al modelo.
        r = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        )
        assert r.status_code == 200, r.text
        estado = r.json()
        est = estado["estimacion"]
        assert estado["estado"] == "cargado"
        assert est["archivos"] == 5 and est["acciones"] == 7
        assert est["al_modelo"] == 5 and est["en_cache"] == 0
        assert est["generales"] == 1
        assert est["carpetas_sin_accion"] == ["9.9.9"]
        assert "1.1.2" in est["acciones_sin_soportes"]
        assert 0 < est["costo_usd"] < est["tope_usd"] and not est["excede_tope"]
        assert falso.llamadas == []
        assert not (corrida.base() / "actual" / "subida.zip").exists()

        # Paso 3: sin confirmar el costo, no corre.
        r = c.post(f"{RUTA}/correr", json={}, headers=cab)
        assert r.status_code == 400
        assert falso.llamadas == []

        r = c.post(f"{RUTA}/correr", json={"confirmo_costo": True}, headers=cab)
        assert r.status_code == 200, r.text
        estado = _esperar(c, cab)

        assert estado["estado"] == "terminado", estado
        assert [p["estado"] for p in estado["pasos"]] == ["hecho"] * 4
        assert estado["pasos"][0]["total"] == 5
        assert estado["resumen"]["veredictos"]["evidencia suficiente"] == 2
        assert estado["costo_usd"] > 0
        assert falso.llamadas.count("registrar_descripcion") == 5
        # Los soportes se borran al terminar; las salidas y la caché quedan.
        assert not estado["soportes_presentes"]
        assert sorted(estado["descargas"]) == ["borrador", "cruce", "inventario"]
        assert list((corrida.base() / "cache").glob("desc-*.json"))

        for clave, extension in [
            ("inventario", ".xlsx"),
            ("cruce", ".xlsx"),
            ("borrador", ".docx"),
        ]:
            r = c.get(f"{RUTA}/descargar/{clave}", headers=cab)
            assert r.status_code == 200
            assert r.content[:2] == b"PK"
            assert extension in r.headers["content-disposition"]
        assert c.get(f"{RUTA}/descargar/otro", headers=cab).status_code == 404

        # Volver a subir lo mismo no paga otra vez las descripciones.
        r = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        )
        est = r.json()["estimacion"]
        assert est["al_modelo"] == 0 and est["en_cache"] == 5
        antes = len(falso.llamadas)
        c.post(f"{RUTA}/correr", json={"confirmo_costo": True}, headers=cab)
        assert _esperar(c, cab)["estado"] == "terminado"
        assert "registrar_descripcion" not in falso.llamadas[antes:]


async def test_borrar_soportes_y_cache(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
) -> None:
    with cliente("calidad") as c:
        cab = await _token("lili@unal.edu.co", "calidad")
        await _plan_cargado(c, cab)
        c.post(f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab)
        c.post(f"{RUTA}/correr", json={"confirmo_costo": True}, headers=cab)
        _esperar(c, cab)
        cache = corrida.base() / "cache"

        r = c.delete(RUTA, headers=cab)
        assert r.status_code == 200 and r.json()["estado"] == "vacio"
        assert not (corrida.base() / "actual").exists()
        assert list(cache.glob("*.json"))  # la caché se conserva
        assert c.get(f"{RUTA}/descargar/borrador", headers=cab).status_code == 404

        c.post(f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab)
        assert (corrida.base() / "actual" / "soportes").is_dir()
        r = c.delete(f"{RUTA}?cache=true", headers=cab)
        assert r.status_code == 200
        assert not (corrida.base() / "actual").exists()
        assert not cache.exists()


async def test_no_se_borra_ni_se_sube_mientras_corre(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = cliente("calidad")
    cab = await _token("lili@unal.edu.co", "calidad")
    await _plan_cargado(c, cab)
    monkeypatch.setattr(corrida, "corriendo", lambda: True)
    assert c.delete(RUTA, headers=cab).status_code == 409
    r = c.post(f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab)
    assert r.status_code == 409


def test_corrida_interrumpida_por_reinicio(falso: ModeloFalso) -> None:
    actual = corrida.base() / "actual"
    (actual / "soportes").mkdir(parents=True)
    (actual / "estado.json").write_text(json.dumps({"estado": "corriendo"}))
    estado = corrida.leer_estado()
    assert estado["estado"] == "interrumpido" and estado["soportes_presentes"]


# ---------------------------------------------------------------------------
# Tope de costo
# ---------------------------------------------------------------------------


async def test_estimacion_sobre_el_tope_no_corre(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(calidad_settings, "revisor_tope_usd", 0.01)
    with cliente("calidad") as c:
        cab = await _token("lili@unal.edu.co", "calidad")
        await _plan_cargado(c, cab)
        r = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        )
        assert "pasa del tope" in r.json()["estimacion"]["excede_tope"]
        r = c.post(f"{RUTA}/correr", json={"confirmo_costo": True}, headers=cab)
        assert r.status_code == 409 and "tope" in r.json()["detail"]
        assert falso.llamadas == []


async def test_el_tope_detiene_la_corrida_aunque_la_estimacion_se_quede_corta() -> None:
    modelo = ModeloFalso()
    uso = Uso()
    # Cada llamada reserva 0,14 USD (50 000 de entrada y 4000 de salida en
    # Sonnet) y gasta 0,003 USD: caben tres antes de que la reserva pase del tope.
    tope = ClienteConTope(modelo, uso, tope_usd=0.1465)
    respuestas = []
    for _ in range(5):
        resp = await tope.llamar(
            modelo="claude-sonnet-5-5",
            sistema="",
            bloques=[],
            texto="",
            salida=BaseModel,
            nombre_herramienta="registrar_descripcion",
            esfuerzo="low",
            max_tokens=4000,
        )
        uso.registrar("claude-sonnet-5-5", resp)
        respuestas.append(resp)
    hechas = [r for r in respuestas if r.llamada]
    assert len(hechas) == 3
    assert uso.costo() <= 0.1465
    assert "tope" in tope.detenido
    assert respuestas[-1].entrada is None and not respuestas[-1].llamada
    assert len(modelo.llamadas) == len(hechas)


# ---------------------------------------------------------------------------
# Zip peligrosos
# ---------------------------------------------------------------------------


def _zip_con(nombre: str, enlace: bool = False) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as zf:
        zf.writestr("Soportes/ACCIÓN 1.1.1/bueno.pdf", pdf_ficticio(1))
        info = zipfile.ZipInfo(nombre)
        if enlace:
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
        else:
            zf.writestr(info, pdf_ficticio(1))
    return salida.getvalue()


@pytest.mark.parametrize(
    ("nombre", "enlace"),
    [
        ("../fuera.pdf", False),
        ("Soportes/../../fuera.pdf", False),
        ("/tmp/fuera.pdf", False),
        ("C:/fuera.pdf", False),
        ("..\\fuera.pdf", False),
        ("Soportes/enlace.pdf", True),
    ],
)
async def test_zip_con_rutas_peligrosas_se_rechaza(
    nombre: str,
    enlace: bool,
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    tmp_path: Path,
) -> None:
    c = cliente("calidad")
    cab = await _token("lili@unal.edu.co", "calidad")
    await _plan_cargado(c, cab)
    r = c.post(
        f"{RUTA}/soportes?programa=alfa", content=_zip_con(nombre, enlace), headers=cab
    )
    assert r.status_code == 400
    assert not (corrida.base() / "actual").exists()
    assert not list(tmp_path.rglob("fuera.pdf"))
    assert c.get(RUTA, headers=cab).json()["estado"] == "vacio"


def test_zip_bomba_y_demasiados_archivos(tmp_path: Path) -> None:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ceros.pdf", b"\0" * 3_000_000)
    bomba = tmp_path / "bomba.zip"
    bomba.write_bytes(salida.getvalue())
    destino = tmp_path / "destino"
    with pytest.raises(ZipNoValido, match="límite"):
        extraer(bomba, destino, max_bytes=1_000_000, max_archivos=10)
    assert not destino.exists()

    muchos = tmp_path / "muchos.zip"
    muchos.write_bytes(zip_ficticio())
    with pytest.raises(ZipNoValido, match="archivos"):
        extraer(muchos, destino, max_bytes=10**9, max_archivos=2)
    assert not destino.exists()


async def test_zip_que_pasa_del_tamano_o_no_es_zip(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = cliente("calidad")
    cab = await _token("lili@unal.edu.co", "calidad")
    await _plan_cargado(c, cab)
    r = c.post(f"{RUTA}/soportes?programa=alfa", content=b"no es un zip", headers=cab)
    assert r.status_code == 400 and "zip" in r.json()["detail"]
    r = c.post(f"{RUTA}/soportes?programa=nadie", content=zip_ficticio(), headers=cab)
    assert r.status_code == 404
    monkeypatch.setattr(calidad_settings, "revisor_max_mb", 0)
    r = c.post(f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab)
    assert r.status_code == 413
    assert not (corrida.base() / "actual").exists()
