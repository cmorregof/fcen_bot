"""API web: autorización por rol y aislamiento entre servicios."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web import auth, crear_router
from app.api.web.config import web_settings
from app.core.config import settings
from app.servicios import admision
from app.servicios.admision.modelo import RespuestaPregunta
from tests.calidad.conftest import fila, xlsx

RAIZ = Path(__file__).resolve().parents[2]
DIR = "fisica"  # cualquier clave válida de DIRECCIONES


@pytest.fixture(autouse=True)
def web(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.programas import DIRECCIONES

    global DIR
    DIR = next(iter(DIRECCIONES))
    monkeypatch.setattr(web_settings, "session_secret", "secreto-de-prueba")
    monkeypatch.setattr(web_settings, "admins", "admin@unal.edu.co")
    monkeypatch.setattr(web_settings, "auth_dev", False)


Cliente = Callable[[str], TestClient]


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> Cliente:
    def _crear(servicio: str) -> TestClient:
        monkeypatch.setattr(settings, "bot_servicio", servicio)
        app = FastAPI()
        app.include_router(crear_router(servicio))
        return TestClient(app)

    return _crear


async def _autorizar(correo: str, rol: str, direccion: str | None = None) -> None:
    db = await aiosqlite.connect(settings.db_path)
    await db.execute(auth._ESQUEMA)
    await db.execute(
        "INSERT INTO web_usuarios (correo, rol, direccion) VALUES (?, ?, ?)",
        (correo, rol, direccion),
    )
    await db.commit()
    await db.close()


async def _token(correo: str, rol: str, direccion: str | None = None) -> dict[str, str]:
    await _autorizar(correo, rol, direccion)
    usuario = auth.Usuario(correo, None, rol, direccion)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {auth.sesion_de(usuario)}"}


# ---------------------------------------------------------------------------
# Cada rol ve solo sus herramientas
# ---------------------------------------------------------------------------

MATRIZ: dict[str, dict[str, set[str]]] = {
    "calidad": {
        "/api/web/calidad/programas": {"calidad", "admin"},
        "/api/web/calidad/alertas": {"calidad", "admin"},
        "/api/web/calidad/a-quien?q=matricula": {"calidad", "admin"},
        "/api/web/calidad/tablero": {"calidad", "admin", "decanatura"},
        "/api/web/usuarios": {"admin"},
    },
    "admision": {
        "/api/web/admision/metricas": {"admision", "admin"},
        "/api/web/admision/chequeo": {"admision", "admin"},
        "/api/web/admision/tablero": {"admision", "admin", "decanatura"},
        "/api/web/usuarios": {"admin"},
    },
    "actas": {
        "/api/web/actas/casos": {"administrativa", "comite"},
        "/api/web/actas/documentos": {"administrativa"},
        "/api/web/actas/tablero": {"decanatura", "admin"},
        "/api/web/usuarios": {"admin"},
    },
}


@pytest.mark.parametrize("servicio", sorted(MATRIZ))
async def test_cada_rol_ve_solo_sus_herramientas(
    servicio: str, cliente: Cliente
) -> None:
    c = cliente(servicio)
    roles = auth.ROLES_POR_SERVICIO[servicio]
    for i, rol in enumerate(roles):
        direccion = DIR if rol in ("administrativa", "comite") else None
        cab = await _token(f"u{i}@unal.edu.co", rol, direccion)
        for ruta, permitidos in MATRIZ[servicio].items():
            r = c.get(ruta, headers=cab)
            if rol in permitidos:
                assert r.status_code == 200, (rol, ruta, r.text)
            else:
                assert r.status_code == 403, (rol, ruta, r.status_code)


@pytest.mark.parametrize("servicio", sorted(MATRIZ))
def test_sin_sesion_no_hay_acceso(servicio: str, cliente: Cliente) -> None:
    c = cliente(servicio)
    for ruta in MATRIZ[servicio]:
        assert c.get(ruta).status_code == 401


async def test_rol_de_otro_servicio_no_entra(cliente: Cliente) -> None:
    """Un rol de calidad guardado en la base de actas no da acceso."""
    c = cliente("actas")
    cab = await _token("intrusa@unal.edu.co", "calidad")
    assert c.get("/api/web/actas/casos", headers=cab).status_code == 403


async def test_permiso_retirado_corta_la_sesion(cliente: Cliente) -> None:
    c = cliente("calidad")
    cab = await _token("ana@unal.edu.co", "calidad")
    admin = {
        "Authorization": f"Bearer {auth.sesion_de(auth.Usuario('admin@unal.edu.co', None, 'admin', None))}"
    }
    assert (
        c.delete("/api/web/usuarios/ana@unal.edu.co", headers=admin).status_code == 200
    )
    assert c.get("/api/web/calidad/programas", headers=cab).status_code == 403


# ---------------------------------------------------------------------------
# Aislamiento entre servicios
# ---------------------------------------------------------------------------

OTRAS = {
    "calidad": ["/api/web/actas/casos", "/api/web/admision/metricas"],
    "admision": ["/api/web/actas/casos", "/api/web/calidad/programas"],
    "actas": ["/api/web/calidad/programas", "/api/web/admision/metricas"],
}


@pytest.mark.parametrize("servicio", sorted(OTRAS))
async def test_un_backend_no_tiene_rutas_de_otro(
    servicio: str, cliente: Cliente
) -> None:
    c = cliente(servicio)
    cab = await _token("admin@unal.edu.co", "admin")
    for ruta in OTRAS[servicio]:
        assert c.get(ruta, headers=cab).status_code == 404


async def test_sesion_de_otro_servicio_se_rechaza(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "bot_servicio", "calidad")
    token = auth.sesion_de(auth.Usuario("admin@unal.edu.co", None, "admin", None))
    c = cliente("admision")
    r = c.get(
        "/api/web/admision/metricas", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 401


@pytest.mark.parametrize("servicio", sorted(MATRIZ))
async def test_ningun_endpoint_abre_otra_base(
    servicio: str, cliente: Cliente, monkeypatch: pytest.MonkeyPatch
) -> None:
    abiertas: list[Path] = []
    original = aiosqlite.connect

    def espia(ruta: Any, *a: Any, **kw: Any) -> Any:
        abiertas.append(Path(ruta).resolve())
        return original(ruta, *a, **kw)

    c = cliente(servicio)
    cab = await _token("admin@unal.edu.co", "admin")
    monkeypatch.setattr(aiosqlite, "connect", espia)
    rutas = [*MATRIZ[servicio], f"/api/web/{servicio}/tablero"]
    for ruta in rutas:
        c.get(ruta, headers=cab)
    assert abiertas
    assert set(abiertas) == {settings.db_path.resolve()}


PROHIBIDOS = {
    "calidad.py": (
        "app.servicios.admision",
        "app.servicios.actas",
        "app.services",
        "app.db",
    ),
    "admision.py": (
        "app.servicios.calidad",
        "app.servicios.actas",
        "app.services",
        "app.db",
    ),
    "actas.py": ("app.servicios.calidad", "app.servicios.admision"),
}


@pytest.mark.parametrize("archivo", sorted(PROHIBIDOS))
def test_modulo_web_no_importa_otro_servicio(archivo: str) -> None:
    arbol = ast.parse((RAIZ / "app" / "api" / "web" / archivo).read_text())
    modulos = [
        n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) and n.module
    ] + [a.name for n in ast.walk(arbol) if isinstance(n, ast.Import) for a in n.names]
    for m in modulos:
        assert not m.startswith(PROHIBIDOS[archivo]), m


# ---------------------------------------------------------------------------
# Ingreso
# ---------------------------------------------------------------------------


def test_sin_client_id_no_hay_ingreso_google(cliente: Cliente) -> None:
    r = cliente("calidad").post("/api/web/sesion", json={"credencial": "x"})
    assert r.status_code == 503


async def test_ingreso_dev_solo_en_local(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = cliente("calidad")
    await _autorizar("ana@unal.edu.co", "calidad")
    assert (
        c.post("/api/web/sesion/dev", json={"correo": "ana@unal.edu.co"}).status_code
        == 404
    )
    monkeypatch.setattr(web_settings, "auth_dev", True)
    r = c.post("/api/web/sesion/dev", json={"correo": "ana@unal.edu.co"})
    assert r.status_code == 200 and r.json()["rol"] == "calidad"
    assert (
        c.post("/api/web/sesion/dev", json={"correo": "otro@unal.edu.co"}).status_code
        == 403
    )
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    assert (
        c.post("/api/web/sesion/dev", json={"correo": "ana@unal.edu.co"}).status_code
        == 404
    )


async def test_admin_solo_autoriza_correos_institucionales(cliente: Cliente) -> None:
    c = cliente("actas")
    cab = await _token("admin@unal.edu.co", "admin")
    malo = {"correo": "x@gmail.com", "rol": "administrativa", "direccion": DIR}
    assert c.post("/api/web/usuarios", json=malo, headers=cab).status_code == 400
    sin_area = {"correo": "x@unal.edu.co", "rol": "administrativa"}
    assert c.post("/api/web/usuarios", json=sin_area, headers=cab).status_code == 400
    ajeno = {"correo": "x@unal.edu.co", "rol": "calidad"}
    assert c.post("/api/web/usuarios", json=ajeno, headers=cab).status_code == 400
    bueno = {**malo, "correo": "x@unal.edu.co"}
    assert c.post("/api/web/usuarios", json=bueno, headers=cab).status_code == 200


# ---------------------------------------------------------------------------
# Actas: área y recomendación
# ---------------------------------------------------------------------------


async def test_actas_area_y_recomendacion(cliente: Cliente) -> None:
    from app.core.programas import DIRECCIONES

    c = cliente("actas")
    adm = await _token("adm@unal.edu.co", "administrativa", DIR)
    r = c.post("/api/web/actas/casos", data={"texto": "Correo ficticio"}, headers=adm)
    assert r.status_code == 200
    caso = r.json()["id"]
    ruta = f"/api/web/actas/casos/{caso}"
    assert c.get(ruta, headers=adm).json()["sentido"] == "pendiente"

    r = c.post(f"{ruta}/recomendacion", json={"sentido": "aprobar"}, headers=adm)
    assert r.json()["sentido_texto"] == "Recomendar aprobar"

    comite = await _token("dir@unal.edu.co", "comite", DIR)
    assert c.get(ruta, headers=comite).status_code == 200
    r = c.post(f"{ruta}/recomendacion", json={"sentido": "no_aprobar"}, headers=comite)
    assert r.status_code == 403
    r = c.post(
        f"{ruta}/concepto",
        json={"miembro": "Prof. Ficticio", "texto": "De acuerdo"},
        headers=comite,
    )
    assert r.status_code == 200

    otra = next((d for d in DIRECCIONES if d != DIR), None)
    if otra:
        ajena = await _token("otra@unal.edu.co", "administrativa", otra)
        assert c.get(ruta, headers=ajena).status_code == 404


# ---------------------------------------------------------------------------
# Admisión: admitidos sin cuenta
# ---------------------------------------------------------------------------


class ModeloFalso:
    async def responder(self, fuentes: str, pregunta: str) -> RespuestaPregunta:
        return RespuestaPregunta(
            respuesta="Se sube en PDF.", cubierta=True, citas=["Listado ficticio, p. 1"]
        )

    async def revisar(self, *a: Any) -> None:
        return None


async def test_admitido_con_consentimiento(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.servicios.admision import fuentes

    async def _fuentes(*a: Any) -> str:
        return "Listado ficticio"

    monkeypatch.setattr(fuentes, "cargar", _fuentes)
    admision.usar_modelo(ModeloFalso())  # type: ignore[arg-type]
    try:
        c = cliente("admision")
        assert c.get("/api/web/admision/aviso").status_code == 200
        assert (
            c.post("/api/web/admision/preguntar", json={"texto": "hola"}).status_code
            == 401
        )

        r = c.post(
            "/api/web/admision/consentimiento", json={"acepto": False, "menor": False}
        )
        assert r.json()["token"] is None

        r = c.post(
            "/api/web/admision/consentimiento", json={"acepto": True, "menor": True}
        )
        cab = {"Authorization": f"Bearer {r.json()['token']}"}
        assert r.json()["puede_revisar"] is False
        r = c.post(
            "/api/web/admision/preguntar",
            json={"texto": "¿Cómo subo la cédula?"},
            headers=cab,
        )
        assert r.json()["estado"] == "ok" and r.json()["citas"]
        r = c.post(
            "/api/web/admision/revisar",
            data={"clave": "x"},
            files={"archivo": ("a.png", b"123", "image/png")},
            headers=cab,
        )
        assert r.status_code == 403
        # La sesión de admitido no abre herramientas del personal.
        assert c.get("/api/web/admision/metricas", headers=cab).status_code == 401
        staff = await _token("mj@unal.edu.co", "admision")
        m = c.get("/api/web/admision/metricas", headers=staff).json()["metricas"]
        assert m["consentimientos"] == 1 and m["rechazos"] == 1 and m["preguntas"] == 1
    finally:
        admision.usar_modelo(None)


# ---------------------------------------------------------------------------
# Calidad: importar con vista previa
# ---------------------------------------------------------------------------


async def test_calidad_importa_con_vista_previa(cliente: Cliente) -> None:
    c = cliente("calidad")
    cab = await _token("lili@unal.edu.co", "calidad")
    contenido = xlsx([fila(), fila(codigo="UNO-02")])
    archivo = {"archivo": ("plan.xlsx", contenido, "application/octet-stream")}
    r = c.post("/api/web/calidad/importar", files=archivo, headers=cab)
    assert r.json()["guardado"] is False and len(r.json()["nuevas"]) == 2
    assert c.get("/api/web/calidad/programas", headers=cab).json()["programas"] == []
    r = c.post(
        "/api/web/calidad/importar",
        files=archivo,
        data={"confirmar": "true"},
        headers=cab,
    )
    assert r.json()["guardado"] is True
    plan = c.get("/api/web/calidad/plan?programa=uno", headers=cab).json()
    assert len(plan["tareas"]) == 2
    tarea = plan["tareas"][0]["id"]
    r = c.post(
        "/api/web/calidad/evidencia",
        json={"tarea_id": tarea, "enlace": "ftp://x"},
        headers=cab,
    )
    assert r.status_code == 400
    r = c.post(
        "/api/web/calidad/evidencia",
        json={"tarea_id": tarea, "enlace": "https://ejemplo.org/a"},
        headers=cab,
    )
    assert r.status_code == 200
    r = c.get("/api/web/calidad/reporte?programa=uno", headers=cab)
    assert r.status_code == 200 and r.content[:2] == b"PK"
