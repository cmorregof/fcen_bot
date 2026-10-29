from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from app.integrations import telegram
from app.servicios.admision import almacen, filtro, fuentes
from app.servicios.admision.config import config
from app.servicios.admision.modelo import (
    INSTRUCCIONES,
    ItemChequeo,
    RespuestaPregunta,
    RevisionDocumento,
    _sistema,
)
from tests.admision.conftest import ADMIN, Chatbot, ModeloFalso, imagen_legible
from tests.conftest import TelegramFalso


@pytest.fixture(autouse=True)
def descarga_imagen(tg: TelegramFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    async def descargar(file_id: str, **kw: object) -> bytes:
        return imagen_legible()

    monkeypatch.setattr(telegram, "descargar_archivo", descargar)


async def volcado(db: aiosqlite.Connection) -> str:
    """Todo el contenido de todas las tablas del servicio, como texto."""
    partes: list[str] = []
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for (tabla,) in await cur.fetchall():
        cur2 = await db.execute(f"SELECT * FROM {tabla}")
        partes.append(f"{tabla}: {await cur2.fetchall()!r}")
    return "\n".join(partes)


# --- consentimiento y menores -------------------------------------------


async def test_start_muestra_aviso_pendiente_de_aval(
    bot: Chatbot, tg: TelegramFalso
) -> None:
    await bot.texto("/start")
    m = tg.mensajes[0]
    assert "PENDIENTE DE AVAL DE LA FACULTAD" in m["texto"]
    assert "No reemplazo la revisión oficial" in m["texto"]
    etiquetas = [b["text"] for fila in m["botones"] for b in fila]
    assert etiquetas == ["Acepto", "No acepto"]


async def test_sin_aceptar_no_responde_preguntas(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.texto("¿Qué documentos necesito?")
    assert modelo.preguntas == []
    assert "/start" in tg.textos()[-1]


async def test_no_acepto_no_habilita_nada(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.texto("/start")
    await bot.boton("adm:noacepto")
    await bot.foto("documento de identidad")
    assert modelo.revisiones == []


async def test_menor_requiere_acudiente_para_revisar(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.texto("/start")
    await bot.boton("adm:acepto")
    await bot.boton("adm:menor:1")
    assert "acudiente" in tg.textos()[-1]

    await bot.foto("documento de identidad")
    assert modelo.revisiones == []
    assert "acudiente" in tg.textos()[-1]

    await bot.boton("adm:acud:1")
    await bot.foto("documento de identidad")
    assert [clave for clave, _ in modelo.revisiones] == ["documento_identidad"]


async def test_menor_sin_acudiente_no_revisa(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.texto("/start")
    await bot.boton("adm:acepto")
    await bot.boton("adm:menor:1")
    await bot.boton("adm:acud:0")
    await bot.foto("documento de identidad")
    assert modelo.revisiones == []


# --- preguntas ----------------------------------------------------------


async def test_pregunta_cubierta_cita_la_seccion(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.texto("¿El documento de identidad va por ambas caras?")
    texto = tg.textos()[-1]
    assert "ambas caras" in texto
    assert "LISTADO_FICTICIO.md, página 1" in texto
    assert "No reemplazo la revisión oficial" in texto
    # el modelo recibió el listado y la guía completos
    assert "Listado FICTICIO" in modelo.fuentes_vistas[0]
    assert "Guía FICTICIA" in modelo.fuentes_vistas[0]


async def test_pregunta_no_cubierta_da_el_contacto(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    modelo.respuesta = RespuestaPregunta(
        cubierta=False, respuesta="Probablemente el 20 de enero.", citas=[]
    )
    await bot.registrar_adulto()
    await bot.texto("¿Hay prórroga para entregar?")
    texto = tg.textos()[-1]
    assert "María Ficticia" in texto
    assert "20 de enero" not in texto  # lo que invente el modelo no llega


async def test_respuesta_sin_cita_se_trata_como_no_cubierta(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    modelo.respuesta = RespuestaPregunta(cubierta=True, respuesta="Sí.", citas=[])
    await bot.registrar_adulto()
    await bot.texto("¿Puedo entregar tarde?")
    assert "María Ficticia" in tg.textos()[-1]


def test_system_prompt_lleva_fuentes_con_cache() -> None:
    sistema = _sistema("TEXTO DE FUENTES")
    assert sistema[0]["text"] == INSTRUCCIONES
    assert "TEXTO DE FUENTES" in sistema[1]["text"]
    assert sistema[1]["cache_control"] == {"type": "ephemeral"}
    assert "Nunca inventes" in INSTRUCCIONES or "Nunca\ninventes" in INSTRUCCIONES


# --- documentos ---------------------------------------------------------


async def test_documento_bien(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    modelo.revision = RevisionDocumento(
        items=[
            ItemChequeo(punto="Se ven las dos caras", estado="ok", detalle="Ok"),
            ItemChequeo(punto="Los datos se leen", estado="ok", detalle="Ok"),
        ]
    )
    await bot.registrar_adulto()
    await bot.foto("documento de identidad")
    texto = tg.textos()[-1]
    assert "✅" in texto and "Por corregir" not in texto
    assert "auténtico" in texto  # el aviso de que no certifica autenticidad
    assert "no puedo decir" in texto
    assert modelo.revisiones[0][0] == "documento_identidad"
    totales = await almacen.totales(bot.db)
    assert totales["documentos_revisados"] == 1
    assert "documentos_con_errores" not in totales


async def test_documento_con_campo_vacio(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    modelo.revision = RevisionDocumento(
        items=[
            ItemChequeo(punto="Es el formato", estado="ok", detalle="Ok"),
            ItemChequeo(
                punto="Todos los campos están diligenciados",
                estado="corregir",
                detalle="Falta el campo de dirección",
                tipo_error="campo_vacio",
            ),
        ]
    )
    await bot.registrar_adulto()
    await bot.foto("formato de matrícula")
    texto = tg.textos()[-1]
    assert "Por corregir" in texto and "Falta el campo de dirección" in texto
    totales = await almacen.totales(bot.db)
    assert totales["error_campo_vacio"] == 1
    assert totales["documentos_con_errores"] == 1


async def test_sin_tipo_pregunta_con_botones_del_listado(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.documento()
    m = tg.mensajes[-1]
    claves = [b["callback_data"] for fila in m["botones"] for b in fila]
    assert "adm:doc:acta_grado" in claves
    assert modelo.revisiones == []
    await bot.boton("adm:doc:acta_grado")
    assert modelo.revisiones[0][0] == "acta_grado"


async def test_reglas_cortan_antes_del_modelo(
    bot: Chatbot,
    tg: TelegramFalso,
    modelo: ModeloFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def basura(file_id: str, **kw: object) -> bytes:
        return b"no soy pdf ni imagen"

    monkeypatch.setattr(telegram, "descargar_archivo", basura)
    await bot.registrar_adulto()
    await bot.foto("documento de identidad")
    assert modelo.revisiones == []
    assert "PDF o fotos" in tg.textos()[-1]
    assert (await almacen.totales(bot.db))["error_formato"] == 1


async def test_archivo_muy_pesado_ni_se_descarga(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.documento("documento de identidad", tamano=config.max_bytes + 1)
    assert modelo.revisiones == []
    assert "pesa demasiado" in tg.textos()[-1]


# --- credenciales -------------------------------------------------------


async def test_contrasena_se_filtra_no_se_guarda_y_se_advierte(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.texto("mi correo es ana.perez@gmail.com y mi contraseña es Secreto123")
    assert "No los compartas" in tg.textos()[-1]
    assert modelo.preguntas == []  # no quedó nada que preguntar
    assert "Secreto123" not in await volcado(bot.db)
    assert "ana.perez" not in await volcado(bot.db)
    assert (await almacen.totales(bot.db))["credenciales_bloqueadas"] == 1


async def test_pregunta_con_contrasena_llega_filtrada_al_modelo(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.texto("mi clave es Abc12345, ¿qué documentos debo subir a la plataforma?")
    assert modelo.preguntas
    assert "Abc12345" not in modelo.preguntas[0]
    assert "No los compartas" in tg.textos()[-2]


async def test_correo_en_la_leyenda_de_una_foto_no_llega_al_modelo(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.foto("documento de identidad, mi correo ana.perez@gmail.com")
    assert modelo.revisiones  # sigue la revisión
    assert any("No los compartas" in t for t in tg.textos())


def test_filtro_unitario() -> None:
    assert filtro.filtrar("hola").credenciales is False
    assert (
        filtro.filtrar("¿cuál es la contraseña de la plataforma?").credenciales is False
    )
    f = filtro.filtrar("password: hunter2 gracias")
    assert f.credenciales and "hunter2" not in f.texto
    f = filtro.filtrar("escríbeme a x.y@z.co")
    assert f.credenciales and "x.y@z.co" not in f.texto


# --- nada del documento queda en disco ni en la base ---------------------


async def test_nada_del_documento_queda_en_disco_ni_en_base(
    bot: Chatbot,
    tg: TelegramFalso,
    modelo: ModeloFalso,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    antes = {p for p in tmp_path.rglob("*")}
    await bot.registrar_adulto()
    await bot.foto("documento de identidad")
    await bot.documento("registro civil")
    assert len(modelo.revisiones) == 2

    nuevos = {p for p in tmp_path.rglob("*")} - antes
    assert all(p.name.startswith("test.db") for p in nuevos), nuevos
    assert not settings.media_dir.exists()

    # la base solo tiene tablas de consentimiento/métricas (+ updates vistos)
    cur = await bot.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tablas = {r[0] for r in await cur.fetchall() if r[0].startswith("admision_")}
    assert tablas == {"admision_consentimiento", "admision_metricas"}
    contenido = await volcado(bot.db)
    assert "F1" not in contenido and "D1" not in contenido  # ni file_id
    assert "casos" not in contenido.replace("casos: []", "")


# --- métricas -----------------------------------------------------------


async def test_metricas_solo_para_autorizados(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.texto("¿ambas caras?")
    await bot.texto("/metricas")
    assert "No tienes permiso" in tg.textos()[-1]
    await bot.texto("/metricas", uid=ADMIN)
    texto = tg.textos()[-1]
    assert "No tienes permiso" not in texto
    assert "preguntas: 1" in texto


# --- fuentes ------------------------------------------------------------


def test_fuentes_marcan_el_origen_para_citar() -> None:
    texto = fuentes.texto_fuentes(config.insumos_dir)
    assert "[LISTADO_FICTICIO.md, página 1]" in texto
    assert "[GUIA_FICTICIA.md, página 1]" in texto


def test_fuentes_sin_carpeta_falla_claro(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fuentes.leer_fuentes(tmp_path / "no-existe")


@pytest.mark.parametrize(
    ("texto", "secreto"),
    [
        ("la contraseña de mi cuenta es perro2026", "perro2026"),
        ("mi contraseña es la 12345", "12345"),
        ("mi usuario es jperez y la clave Abc!2026", "jperez"),
        ("mi usuario es jperez y la clave Abc!2026", "Abc!2026"),
        ("password: hunter2 hunter3", "hunter3"),
        ("mi clave Zeta9981 otra cosa", "Zeta9981"),
        ("usuario jperez\ncontraseña perro 2026", "perro"),
    ],
)
def test_filtro_omite_todo_lo_que_sigue_a_la_palabra_clave(
    texto: str, secreto: str
) -> None:
    f = filtro.filtrar(texto)
    assert f.credenciales
    assert secreto not in f.texto


def test_filtro_conserva_la_pregunta_posterior_y_no_marca_menciones() -> None:
    f = filtro.filtrar("mi clave es Abc12345, ¿qué documentos debo subir?")
    assert f.credenciales and "Abc12345" not in f.texto
    assert "¿qué documentos debo subir?" in f.texto
    assert not filtro.filtrar("¿Cuál es la contraseña de la plataforma?").credenciales
    assert not filtro.filtrar("olvidé mi contraseña").credenciales


async def test_mensaje_solo_con_credenciales_no_llega_al_modelo(
    bot: Chatbot, tg: TelegramFalso, modelo: ModeloFalso
) -> None:
    await bot.registrar_adulto()
    await bot.texto("la contraseña de mi cuenta es perro2026")
    assert modelo.preguntas == []
    assert "No los compartas" in tg.textos()[-1]
    assert "perro2026" not in await volcado(bot.db)
