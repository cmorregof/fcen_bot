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
from tests.calidad.conftest import ALFA

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
        "/api/web/admision/insumos": {"admision", "admin"},
        "/api/web/admision/tablero": {"admision", "admin", "decanatura"},
        "/api/web/usuarios": {"admin"},
    },
    "actas": {
        "/api/web/actas/casos": {"administrativa", "comite"},
        "/api/web/actas/documentos": {"administrativa"},
        "/api/web/actas/consejo": {"administrativa", "admin"},
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


@pytest.mark.parametrize(
    "variable",
    ["RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID"],
)
async def test_ingreso_dev_bloqueado_con_cualquier_variable_de_railway(
    variable: str, cliente: Cliente, monkeypatch: pytest.MonkeyPatch
) -> None:
    for v in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_ENVIRONMENT_NAME",
        "RAILWAY_ENVIRONMENT_ID",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(web_settings, "auth_dev", True)
    monkeypatch.setenv(variable, "x")
    c = cliente("calidad")
    await _autorizar("ana@unal.edu.co", "calidad")
    assert (
        c.post("/api/web/sesion/dev", json={"correo": "ana@unal.edu.co"}).status_code
        == 404
    )


async def test_admitidos_tienen_limite_por_hora(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.web import admision as web_admision
    from app.servicios.admision import fuentes

    async def _fuentes(*a: Any) -> str:
        return "Listado ficticio"

    monkeypatch.setattr(fuentes, "cargar", _fuentes)
    monkeypatch.setitem(web_admision.LIMITES_POR_HORA, "preguntar", 2)
    web_admision.reiniciar_limites()
    admision.usar_modelo(ModeloFalso())  # type: ignore[arg-type]
    try:
        c = cliente("admision")
        r = c.post(
            "/api/web/admision/consentimiento", json={"acepto": True, "menor": False}
        )
        cab = {"Authorization": f"Bearer {r.json()['token']}"}
        # El proxy de Railway añade la IP real al final de X-Forwarded-For.
        ip_a = {**cab, "X-Forwarded-For": "10.0.0.1, 203.0.113.7"}
        ip_b = {**cab, "X-Forwarded-For": "198.51.100.9"}
        pregunta = {"texto": "¿Cómo subo la cédula?"}
        for _ in range(2):
            ok = c.post("/api/web/admision/preguntar", json=pregunta, headers=ip_a)
            assert ok.status_code == 200
        r = c.post("/api/web/admision/preguntar", json=pregunta, headers=ip_a)
        assert r.status_code == 429
        # Otra IP no queda bloqueada por la primera.
        r = c.post("/api/web/admision/preguntar", json=pregunta, headers=ip_b)
        assert r.status_code == 200
    finally:
        admision.usar_modelo(None)
        web_admision.reiniciar_limites()


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
    archivo = {"archivo": ("plan.xlsx", ALFA.read_bytes(), "application/octet-stream")}
    r = c.post("/api/web/calidad/importar", files=archivo, headers=cab)
    assert r.json()["guardado"] is False and r.json()["acciones"] == 7
    assert c.get("/api/web/calidad/programas", headers=cab).json()["programas"] == []
    r = c.post(
        "/api/web/calidad/importar",
        files=archivo,
        data={"confirmar": "true"},
        headers=cab,
    )
    assert r.json()["guardado"] is True
    plan = c.get("/api/web/calidad/plan?programa=alfa", headers=cab).json()
    assert plan["acciones"] == 7 and plan["conteo"]["vencida"] >= 1
    assert plan["reprogramadas"] >= 1
    codigo = plan["objetivos"][0]["acciones"][0]["codigo"]
    pedido = {"programa": "alfa", "codigo": codigo, "enlace": "ftp://x"}
    r = c.post("/api/web/calidad/evidencia", json=pedido, headers=cab)
    assert r.status_code == 400
    pedido["enlace"] = "https://ejemplo.org/a"
    r = c.post("/api/web/calidad/evidencia", json=pedido, headers=cab)
    assert r.status_code == 200
    r = c.post(
        "/api/web/calidad/evidencia",
        json={**pedido, "codigo": "9.9.9"},
        headers=cab,
    )
    assert r.status_code == 404
    plan = c.get("/api/web/calidad/plan?programa=alfa", headers=cab).json()
    assert (
        plan["objetivos"][0]["acciones"][0]["soportes"][0]["valor"] == pedido["enlace"]
    )
    tablero = c.get("/api/web/calidad/tablero", headers=cab).json()
    assert tablero["por_programa"][0]["acciones"] == 7


def test_token_de_google_invalido_responde_401_no_500(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ejecuta el transporte real de google-auth (antes faltaba `requests`)."""
    from google.oauth2 import id_token

    def _invalido(*a: Any, **kw: Any) -> dict[str, Any]:
        raise ValueError("token inválido")

    monkeypatch.setattr(web_settings, "google_client_id", "cliente.apps.example")
    monkeypatch.setattr(id_token, "verify_oauth2_token", _invalido)
    r = cliente("calidad").post("/api/web/sesion", json={"credencial": "falso"})
    assert r.status_code == 401


async def test_ip_falsa_al_comienzo_de_x_forwarded_for_no_salta_el_limite(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.web import admision as web_admision
    from app.servicios.admision import fuentes

    async def _fuentes(*a: Any) -> str:
        return "Listado ficticio"

    monkeypatch.setattr(fuentes, "cargar", _fuentes)
    monkeypatch.setitem(web_admision.LIMITES_POR_HORA, "preguntar", 2)
    web_admision.reiniciar_limites()
    admision.usar_modelo(ModeloFalso())  # type: ignore[arg-type]
    try:
        c = cliente("admision")
        r = c.post(
            "/api/web/admision/consentimiento", json={"acepto": True, "menor": False}
        )
        cab = {"Authorization": f"Bearer {r.json()['token']}"}
        codigos = [
            c.post(
                "/api/web/admision/preguntar",
                json={"texto": "¿Cómo subo la cédula?"},
                headers={**cab, "X-Forwarded-For": f"192.0.2.{i}, 203.0.113.7"},
            ).status_code
            for i in range(3)
        ]
        assert codigos == [200, 200, 429]
    finally:
        admision.usar_modelo(None)
        web_admision.reiniciar_limites()


def test_limites_por_hora_salen_de_la_configuracion() -> None:
    from app.api.web import admision as web_admision
    from app.servicios.admision.config import config

    assert web_admision.LIMITES_POR_HORA == {
        "consentimiento": config.limite_consentimiento_hora,
        "preguntar": config.limite_preguntar_hora,
        "revisar": config.limite_revisar_hora,
    }


def test_aviso_lleva_seccion_tipo_y_condicion(cliente: Cliente) -> None:
    docs = cliente("admision").get("/api/web/admision/aviso").json()["documentos"]
    paes = next(d for d in docs if d["clave"] == "certificado_paes")
    assert paes["tipo"] == "condicional"
    assert paes["condicion"] == "Solo admitidos PAES"
    assert paes["seccion"] == "DOCUMENTOS PERSONALES (OBLIGATORIOS)"
    assert {d["tipo"] for d in docs} == {"obligatorio", "condicional", "opcional"}
    # El público no recibe los puntos de chequeo, solo la lista.
    assert all("chequeo" not in d for d in docs)


async def test_responsable_sube_insumos_al_volumen(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.servicios.admision import fuentes
    from app.servicios.admision.config import config

    carpeta = tmp_path / "insumos"
    monkeypatch.setattr(config, "insumos_dir", carpeta)
    olvidos: list[bool] = []
    monkeypatch.setattr(fuentes, "olvidar", lambda: olvidos.append(True))
    c = cliente("admision")
    cab = await _token("adm@unal.edu.co", "admision")
    nombre = fuentes.INSUMOS_ESPERADOS[1]

    pdf = b"%PDF-1.4 ficticio"
    r = c.post(
        "/api/web/admision/insumos",
        files={"archivo": (nombre, pdf, "application/pdf")},
        headers=cab,
    )
    assert r.status_code == 200
    assert (carpeta / nombre).read_bytes() == pdf
    assert olvidos == [True]
    cuerpo = r.json()
    assert nombre not in cuerpo["faltan"]
    assert len(cuerpo["faltan"]) == len(fuentes.INSUMOS_ESPERADOS) - 1
    assert [a["nombre"] for a in cuerpo["archivos"]] == [nombre]
    assert not [p for p in carpeta.iterdir() if p.name.startswith(".")]

    # La caché OCR de un PDF escaneado también se puede subir.
    r = c.post(
        "/api/web/admision/insumos",
        files={"archivo": ("Escaneado.ocr.txt", b"texto", "text/plain")},
        headers=cab,
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    ("nombre", "datos"),
    [
        ("cedula.jpg", b"\xff\xd8\xff"),  # solo PDF, TXT o MD
        (".oculto.pdf", b"%PDF-1.4"),
        ("listado.pdf", b"no es un pdf"),
        ("notas.txt", b"\xff\xfe\x00"),  # no es UTF-8
    ],
)
async def test_insumo_no_valido_se_rechaza(
    nombre: str,
    datos: bytes,
    cliente: Cliente,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.servicios.admision.config import config

    carpeta = tmp_path / "insumos"
    monkeypatch.setattr(config, "insumos_dir", carpeta)
    c = cliente("admision")
    cab = await _token("adm@unal.edu.co", "admision")
    r = c.post(
        "/api/web/admision/insumos", files={"archivo": (nombre, datos)}, headers=cab
    )
    assert r.status_code == 400
    assert not carpeta.exists() or list(carpeta.iterdir()) == []


async def test_ruta_en_el_nombre_del_insumo_no_sale_de_la_carpeta(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.servicios.admision.config import config

    carpeta = tmp_path / "insumos"
    monkeypatch.setattr(config, "insumos_dir", carpeta)
    c = cliente("admision")
    cab = await _token("adm@unal.edu.co", "admision")
    r = c.post(
        "/api/web/admision/insumos",
        files={"archivo": ("../../fuera.pdf", b"%PDF-1.4")},
        headers=cab,
    )
    assert r.status_code == 200
    assert (carpeta / "fuera.pdf").exists()
    assert not (tmp_path / "fuera.pdf").exists()


async def test_admitido_no_puede_subir_insumos(
    cliente: Cliente, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.servicios.admision.config import config

    carpeta = tmp_path / "insumos"
    monkeypatch.setattr(config, "insumos_dir", carpeta)
    c = cliente("admision")
    r = c.post(
        "/api/web/admision/consentimiento", json={"acepto": True, "menor": False}
    )
    cab = {"Authorization": f"Bearer {r.json()['token']}"}
    r = c.post(
        "/api/web/admision/insumos",
        files={"archivo": ("x.pdf", b"%PDF-1.4")},
        headers=cab,
    )
    assert r.status_code in (401, 403)
    assert not carpeta.exists() or list(carpeta.iterdir()) == []
