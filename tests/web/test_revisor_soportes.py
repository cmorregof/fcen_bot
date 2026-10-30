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


def _correr(c: TestClient, cab: dict[str, str], estado: dict[str, Any]) -> Any:
    """Confirma la carga y el costo que se vieron, como hace la pantalla."""
    return c.post(
        f"{RUTA}/correr",
        json={
            "confirmo_costo": True,
            "carga_id": estado["carga_id"],
            "costo_usd": estado["estimacion"]["costo_usd"],
        },
        headers=cab,
    )


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

        r = _correr(c, cab, estado)
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
        _correr(c, cab, r.json())
        assert _esperar(c, cab)["estado"] == "terminado"
        assert "registrar_descripcion" not in falso.llamadas[antes:]


async def test_borrar_soportes_y_cache(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
) -> None:
    with cliente("calidad") as c:
        cab = await _token("lili@unal.edu.co", "calidad")
        await _plan_cargado(c, cab)
        r = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        )
        _correr(c, cab, r.json())
        _esperar(c, cab)
        cache = corrida.base() / "cache"

        r = c.delete(RUTA, headers=cab)
        assert r.status_code == 200 and r.json()["estado"] == "vacio"
        assert not (corrida.base() / "actual").exists()
        assert list(cache.glob("*.json"))  # la caché se conserva
        assert r.json()["en_cache"] > 0
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
        r = _correr(c, cab, r.json())
        assert r.status_code == 409 and "tope" in r.json()["detail"]
        assert falso.llamadas == []


async def _llamar(modelo_api: Any, texto: str = "") -> Respuesta:
    resp: Respuesta = await modelo_api.llamar(
        modelo="claude-sonnet-5-5",
        sistema="",
        bloques=[],
        texto=texto,
        salida=BaseModel,
        nombre_herramienta="registrar_cruce",
        esfuerzo="high",
        max_tokens=4000,
    )
    return resp


async def test_con_el_tope_casi_agotado_no_sale_una_peticion_que_lo_pase() -> None:
    """La reserva sale del tamaño real de la petición, no de un número fijo:
    un cruce con unos 1000 documentos generales no cabe en lo que queda."""
    modelo = ModeloFalso()
    uso = Uso()
    uso.sumar("claude-opus-5-5", 200_000, 0)  # 0,80 USD ya gastados
    tope = ClienteConTope(modelo, uso, tope_usd=1.0)
    grande = "[S0001] acta ficticia de una reunión del comité\n" * 1000 * 6
    resp = await _llamar(tope, grande)
    assert not resp.llamada and resp.entrada is None
    assert "tope" in tope.detenido
    assert modelo.llamadas == []
    assert uso.costo() <= 1.0

    # Una petición pequeña sí cabe en lo que queda.
    otro = ClienteConTope(modelo, uso, tope_usd=1.0)
    assert (await _llamar(otro, "corto")).llamada
    assert ClienteConTope.reserva("", [], grande, 4000) > 1.0 - 0.80
    assert ClienteConTope.reserva("", [], "corto", 4000) < 0.2


async def test_la_reserva_cuenta_bloques_y_la_tarifa_mas_cara() -> None:
    pdf = {"type": "document", "source": {"type": "base64", "data": "x"}}
    imagen = {"type": "image", "source": {"type": "base64", "data": "x"}}
    solo_texto = ClienteConTope.reserva("", [], "hola", 0)
    con_pdf = ClienteConTope.reserva("", [pdf], "hola", 0)
    con_imagen = ClienteConTope.reserva("", [imagen], "hola", 0)
    assert con_pdf > con_imagen > solo_texto
    # A la tarifa de entrada de Opus (4 USD/M), con escritura en caché a 1,25x.
    assert con_pdf - solo_texto == pytest.approx(1.25 * 4 * 5000 * 4 / 1e6)


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
    with pytest.raises(ZipNoValido, match="máximo"):
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


def test_carpeta_cuenta_todas_las_entradas(tmp_path: Path) -> None:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as zf:
        for d in ("a/", "a/b/", "a/b/c/"):
            zf.writestr(zipfile.ZipInfo(d), b"")
        zf.writestr("a/b/c/acta.pdf", pdf_ficticio(1))
    origen = tmp_path / "carpetas.zip"
    origen.write_bytes(salida.getvalue())
    with pytest.raises(ZipNoValido, match="entradas"):
        extraer(origen, tmp_path / "d", max_bytes=10**9, max_archivos=2)


# ---------------------------------------------------------------------------
# Zip anidados y archivos grandes (bombas dentro de la carpeta)
# ---------------------------------------------------------------------------


def _zip_de(miembros: dict[str, bytes]) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zf:
        for nombre, datos in miembros.items():
            zf.writestr(nombre, datos)
    return salida.getvalue()


def test_zip_anidado_grande_no_se_abre(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.servicios.calidad.soportes import inventario

    monkeypatch.setattr(inventario, "MAX_BYTES_ARCHIVO", 1_000_000)
    monkeypatch.setattr(inventario, "MAX_BYTES_ANIDADOS", 1_500_000)
    carpeta = tmp_path / "c" / "ACCIÓN 1.1.1"
    carpeta.mkdir(parents=True)
    # 2 MB de ceros comprimen a pocos KB: el zip interno parece inofensivo.
    (carpeta / "interno.zip").write_bytes(
        _zip_de(
            {
                "enorme.pdf": b"\0" * 2_000_000,
                "uno.pdf": b"\0" * 900_000,
                "dos.pdf": b"\0" * 900_000,
            }
        )
    )
    leidos: list[int] = []
    original = inventario.leer_miembro
    monkeypatch.setattr(
        inventario,
        "leer_miembro",
        lambda zf, info, *a: leidos.append(info.file_size) or original(zf, info, *a),
    )
    archivos = {a.nombre: a for a in inventario.inventariar(tmp_path / "c")}
    assert "límite" in archivos["enorme.pdf"].nota
    assert archivos["enorme.pdf"].tipo == "otro"
    # El presupuesto común deja leer uno de los dos de 900 KB, no los dos.
    assert sum(1 for n in ("uno.pdf", "dos.pdf") if "límite" in archivos[n].nota) == 1
    assert sum(leidos) <= 1_500_000


def test_miembro_que_pasa_del_tope_se_corta(tmp_path: Path) -> None:
    from app.servicios.calidad.soportes.inventario import (
        ArchivoMuyGrande,
        leer_miembro,
    )

    with zipfile.ZipFile(io.BytesIO(_zip_de({"x.pdf": b"\0" * 300_000}))) as zf:
        with pytest.raises(ArchivoMuyGrande):
            leer_miembro(zf, zf.infolist()[0], 100_000)


def test_archivo_grande_y_office_bomba_no_se_abren(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.servicios.calidad.soportes import inventario

    monkeypatch.setattr(inventario, "MAX_BYTES_ARCHIVO", 1_000_000)
    monkeypatch.setattr(inventario, "MAX_BYTES_XLSX", 1_000_000)
    carpeta = tmp_path / "c"
    carpeta.mkdir()
    (carpeta / "grande.pdf").write_bytes(b"%PDF" + b"\0" * 1_500_000)
    (carpeta / "bomba.xlsx").write_bytes(_zip_de({"xl/hoja.xml": b"\0" * 3_000_000}))
    abiertos: list[str] = []
    monkeypatch.setattr(
        inventario, "_fecha_office", lambda d, t: abiertos.append(t) or None
    )
    archivos = {a.nombre: a for a in inventario.inventariar(carpeta)}
    assert archivos["grande.pdf"].tipo == "otro" and archivos["grande.pdf"].sha256
    assert archivos["bomba.xlsx"].tipo == "otro"
    assert abiertos == []


# ---------------------------------------------------------------------------
# La confirmación queda atada a la carga vista
# ---------------------------------------------------------------------------


async def test_iniciar_corre_solo_la_carga_que_se_vio(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
) -> None:
    with cliente("calidad") as c:
        cab = await _token("lili@unal.edu.co", "calidad")
        await _plan_cargado(c, cab)
        vista_a = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        ).json()
        # Otra persona sube otra carga antes de que A pulse «Iniciar».
        vista_b = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        ).json()
        assert vista_a["carga_id"] != vista_b["carga_id"]
        r = _correr(c, cab, vista_a)
        assert r.status_code == 409 and "cambiaron" in r.json()["detail"]
        # Sin id de carga no corre.
        r = c.post(f"{RUTA}/correr", json={"confirmo_costo": True}, headers=cab)
        assert r.status_code == 400
        # Si el costo subió desde que lo vio, tampoco: debe confirmar otra vez.
        vista_b["estimacion"]["costo_usd"] = 0.0
        r = _correr(c, cab, vista_b)
        assert r.status_code == 409 and "subió" in r.json()["detail"]
        assert falso.llamadas == []
        assert c.get(RUTA, headers=cab).json()["estado"] == "cargado"


# ---------------------------------------------------------------------------
# Caché, trabajo síncrono y retención
# ---------------------------------------------------------------------------


def test_clave_de_descripcion_depende_de_la_accion() -> None:
    from app.servicios.calidad.soportes.describir import clave_descripcion
    from app.servicios.calidad.soportes.modelos import Accion, Archivo

    archivo = Archivo(
        id="S001", ruta="x.pdf", nombre="x.pdf", accion="1.1.1",
        tipo="pdf", extension=".pdf", tamano=1, sha256="abc",
    )  # fmt: skip

    def accion(indicador: str) -> Accion:
        return Accion(
            codigo="1.1.1", aspecto="", objetivo="", descripcion="Seminarios",
            indicador=indicador, inicio="", fin="",
        )  # fmt: skip

    alfa = clave_descripcion(archivo, "m", accion("Número de seminarios"))
    beta = clave_descripcion(archivo, "m", accion("Actas aprobadas"))
    assert alfa != beta
    assert alfa == clave_descripcion(archivo, "m", accion("Número de seminarios"))


async def test_pdf_y_salidas_se_preparan_fuera_del_event_loop(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from app.servicios.calidad.soportes import describir, revisor

    hilos: dict[str, set[int]] = {"loop": set(), "preparar": set(), "salidas": set()}
    llamar = falso.llamar

    async def espia(**kw: Any) -> Respuesta:
        hilos["loop"].add(threading.get_ident())
        return await llamar(**kw)

    monkeypatch.setattr(falso, "llamar", espia)
    prep = describir.contenido.preparar
    monkeypatch.setattr(
        describir.contenido,
        "preparar",
        lambda *a: hilos["preparar"].add(threading.get_ident()) or prep(*a),
    )
    inv = revisor.inventario_xlsx
    monkeypatch.setattr(
        revisor,
        "inventario_xlsx",
        lambda *a: hilos["salidas"].add(threading.get_ident()) or inv(*a),
    )
    with cliente("calidad") as c:
        cab = await _token("lili@unal.edu.co", "calidad")
        await _plan_cargado(c, cab)
        r = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        )
        _correr(c, cab, r.json())
        assert _esperar(c, cab)["estado"] == "terminado"
    assert hilos["loop"] and hilos["preparar"] and hilos["salidas"]
    assert not hilos["loop"] & (hilos["preparar"] | hilos["salidas"])


def test_al_arrancar_se_borran_soportes_de_una_corrida_cortada(
    falso: ModeloFalso,
) -> None:
    actual = corrida.base() / "actual"
    (actual / "soportes").mkdir(parents=True)
    (actual / "estado.json").write_text(json.dumps({"estado": "corriendo"}))
    corrida.limpiar(al_arrancar=True)
    assert not (actual / "soportes").exists()

    # Sin estado.json: también se borran soportes y zip a medio subir.
    (actual / "estado.json").unlink()
    (actual / "soportes").mkdir()
    (actual / "subida.zip").write_bytes(b"x")
    corrida.limpiar(al_arrancar=True)
    assert not (actual / "soportes").exists()
    assert not (actual / "subida.zip").exists()


def test_retencion_borra_lo_viejo(
    falso: ModeloFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setattr(calidad_settings, "revisor_retencion_dias", 30)
    actual = corrida.base() / "actual"
    (actual / "salidas").mkdir(parents=True)
    (actual / "estado.json").write_text(json.dumps({"estado": "terminado"}))
    cache = corrida.base() / "cache"
    cache.mkdir()
    (cache / "vieja.json").write_text("{}")
    (cache / "nueva.json").write_text("{}")
    hace_40_dias = time.time() - 40 * 86400
    os.utime(cache / "vieja.json", (hace_40_dias, hace_40_dias))
    corrida.limpiar()
    assert actual.exists() and (cache / "vieja.json").exists() is False
    assert (cache / "nueva.json").exists()
    os.utime(actual / "estado.json", (hace_40_dias, hace_40_dias))
    corrida.limpiar()
    assert not actual.exists()


async def test_apagado_purga_el_volumen(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (corrida.base() / "cache").mkdir(parents=True)
    (corrida.base() / "cache" / "x.json").write_text("{}")
    monkeypatch.setattr(calidad_settings, "revisor_activo", False)
    corrida.limpiar(al_arrancar=True)
    assert not corrida.base().exists()
    (corrida.base() / "cache").mkdir(parents=True)
    c = cliente("calidad")
    cab = await _token("lili@unal.edu.co", "calidad")
    assert c.get(RUTA, headers=cab).status_code == 403
    assert not corrida.base().exists()


async def test_el_log_de_un_fallo_no_trae_nombres(
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def falla(**kw: Any) -> Respuesta:
        raise RuntimeError("Zoila Ficticia Pérez - acta_ficticia.pdf")

    monkeypatch.setattr(falso, "llamar", falla)
    with cliente("calidad") as c:
        cab = await _token("lili@unal.edu.co", "calidad")
        await _plan_cargado(c, cab)
        r = c.post(
            f"{RUTA}/soportes?programa=alfa", content=zip_ficticio(), headers=cab
        )
        _correr(c, cab, r.json())
        estado = _esperar(c, cab)
    assert estado["estado"] == "fallido"
    assert "RuntimeError" in caplog.text
    assert "Zoila" not in caplog.text and "acta_ficticia" not in caplog.text
    assert "Zoila" not in json.dumps(estado)
    assert not estado["soportes_presentes"]


# ---------------------------------------------------------------------------
# Segunda revisión: presupuesto de Office, carpeta dedicada y cerrojo
# ---------------------------------------------------------------------------


def test_muchos_office_moderados_agotan_el_presupuesto_comun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.servicios.calidad.soportes import inventario

    monkeypatch.setattr(inventario, "MAX_BYTES_ANIDADOS", 2_500_000)
    abiertos: list[str] = []
    monkeypatch.setattr(
        inventario, "_fecha_office", lambda d, t: abiertos.append(t) or None
    )
    monkeypatch.setattr(
        "app.servicios.calidad.soportes.contenido.conteos_xlsx", lambda d: ""
    )
    carpeta = tmp_path / "c"
    carpeta.mkdir()
    # Cada xlsx pesa unos KB y declara 1 MB de XML: cabe por documento.
    office = _zip_de({"xl/hoja.xml": b"\0" * 1_000_000})
    for i in range(2):
        (carpeta / f"suelto{i}.xlsx").write_bytes(office)
    # Y otros dos dentro de un zip: también descuentan del mismo presupuesto.
    (carpeta / "interno.zip").write_bytes(
        _zip_de({f"dentro{i}.xlsx": office for i in range(2)})
    )
    archivos = inventario.inventariar(carpeta)
    xlsx = [a for a in archivos if a.extension == ".xlsx"]
    rechazados = [a for a in xlsx if "límite" in a.nota]
    assert len(xlsx) == 4
    assert len(abiertos) == 2 and len(rechazados) == 2


def test_docx_tiene_un_tope_mas_bajo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.servicios.calidad.soportes import inventario

    assert inventario.MAX_BYTES_DOCX < inventario.MAX_BYTES_XLSX
    monkeypatch.setattr(inventario, "MAX_BYTES_DOCX", 500_000)
    monkeypatch.setattr(inventario, "_fecha_office", lambda d, t: None)
    monkeypatch.setattr(
        "app.servicios.calidad.soportes.contenido.conteos_xlsx", lambda d: ""
    )
    carpeta = tmp_path / "c"
    carpeta.mkdir()
    office = _zip_de({"word/document.xml": b"\0" * 1_000_000})
    (carpeta / "acta.docx").write_bytes(office)
    (carpeta / "lista.xlsx").write_bytes(office)
    archivos = {a.nombre: a for a in inventario.inventariar(carpeta)}
    assert archivos["acta.docx"].tipo == "otro"
    assert archivos["lista.xlsx"].tipo == "xlsx"


@pytest.mark.parametrize("donde", ["db", "data_dir"])
async def test_carpeta_no_dedicada_no_se_borra(
    donde: str,
    cliente: Cliente,  # noqa: F811
    falso: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.core.config import settings

    if donde == "db":
        carpeta = settings.db_path.parent
    else:
        carpeta = tmp_path / "data"
        monkeypatch.setattr(settings, "data_dir", carpeta)
    (carpeta / "cache").mkdir(parents=True, exist_ok=True)
    (carpeta / "cache" / "x.json").write_text("{}")
    otro = carpeta / "fcen-ficticio.db"
    otro.write_text("base")
    monkeypatch.setattr(calidad_settings, "revisor_dir", carpeta)

    c = cliente("calidad")
    cab = await _token("lili@unal.edu.co", "calidad")
    # Encendido: la API se niega a usar esa carpeta.
    assert c.get(RUTA, headers=cab).status_code == 503
    # Apagado y al arrancar: no se borra nada.
    monkeypatch.setattr(calidad_settings, "revisor_activo", False)
    corrida.limpiar(al_arrancar=True)
    assert c.get(RUTA, headers=cab).status_code == 403
    assert otro.exists() and (carpeta / "cache" / "x.json").exists()
    assert settings.db_path.exists()


def test_apagado_borra_solo_lo_propio(
    falso: ModeloFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    raiz = corrida.base()
    (raiz / "actual" / "salidas").mkdir(parents=True)
    (raiz / "cache").mkdir()
    (raiz / "ajeno.txt").write_text("no es del revisor")
    monkeypatch.setattr(calidad_settings, "revisor_activo", False)
    corrida.limpiar()
    assert not (raiz / "actual").exists() and not (raiz / "cache").exists()
    assert (raiz / "ajeno.txt").exists()


def test_limpiar_toma_el_cerrojo(
    falso: ModeloFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual = corrida.base() / "actual"
    (actual / "soportes").mkdir(parents=True)
    # Con una carga en curso, la limpieza no toca nada.
    monkeypatch.setattr(corrida, "_ocupado", True)
    corrida.limpiar(al_arrancar=True)
    assert (actual / "soportes").exists()
    monkeypatch.setattr(corrida, "_ocupado", False)

    # Mientras limpia, nadie más puede tomar el cerrojo.
    durante: list[bool] = []
    original = corrida._limpiar
    monkeypatch.setattr(
        corrida,
        "_limpiar",
        lambda *a: durante.append(corrida._tomar()) or original(*a),
    )
    corrida.limpiar(al_arrancar=True)
    assert durante == [False]
    assert not (actual / "soportes").exists()
    assert corrida._tomar()  # y lo suelta al terminar
    corrida._soltar()


def test_carga_sin_lanzar_se_borra_al_dia(
    falso: ModeloFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setattr(calidad_settings, "revisor_retencion_carga_horas", 24)
    actual = corrida.base() / "actual"
    (actual / "soportes").mkdir(parents=True)
    estado = actual / "estado.json"
    hace_dos_dias = time.time() - 2 * 86400

    estado.write_text(json.dumps({"estado": "terminado"}))
    os.utime(estado, (hace_dos_dias, hace_dos_dias))
    corrida.limpiar()
    assert actual.exists()  # salidas: retención de 30 días

    estado.write_text(json.dumps({"estado": "cargado"}))
    os.utime(estado, (hace_dos_dias, hace_dos_dias))
    corrida.limpiar()
    assert not actual.exists()


async def test_el_cliente_real_registra_solo_el_tipo_del_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.servicios.calidad.soportes.cliente import ClienteAnthropic

    class Mensajes:
        async def create(self, **kw: Any) -> Any:
            raise ValueError("Zoila Ficticia Pérez - acta_ficticia.pdf")

    class Beta:
        messages = Mensajes()

    class Falso:
        beta = Beta()

    from app.servicios.calidad.soportes.modelos import DescripcionArchivo

    real = ClienteAnthropic("clave-ficticia")
    real._cliente = Falso()  # type: ignore[assignment]
    resp = await real.llamar(
        modelo="m", sistema="s", bloques=[], texto="t", salida=DescripcionArchivo,
        nombre_herramienta="h", esfuerzo="low", max_tokens=10,
    )  # fmt: skip
    assert resp.entrada is None
    assert "ValueError" in caplog.text and "Zoila" not in caplog.text
