from __future__ import annotations

from app.servicios.calidad import directorio
from tests.calidad.conftest import Chat_


def test_el_directorio_de_ejemplo_no_trae_datos_reales() -> None:
    tramites = directorio.cargar()
    assert len(tramites) >= 8
    for t in tramites:
        assert "PARA COMPLETAR" in t.dependencia and "PARA COMPLETAR" in t.cargo
        assert t.correo == "PARA COMPLETAR"


def test_busca_por_tema_y_palabras_clave() -> None:
    tramites = directorio.cargar()
    assert directorio.buscar("evidencias del plan de mejoramiento", tramites)[
        0
    ].tema.startswith("Seguimiento del plan")
    assert directorio.buscar("quiero cancelar una asignatura", tramites)[
        0
    ].tema.startswith("Solicitudes estudiantiles")
    assert directorio.buscar("jurados del trabajo de grado", tramites)[
        0
    ].tema.startswith("Trabajo de grado")


def test_tema_desconocido_no_devuelve_nada() -> None:
    assert directorio.buscar("zzz qqq", directorio.cargar()) == []


async def test_a_quien_responde_cadena_completa(chat: Chat_) -> None:
    texto = await chat.texto("/a_quien acreditación")
    assert "Dependencia:" in texto and "Cargo:" in texto and "Correo:" in texto
    assert "PARA COMPLETAR" in texto


async def test_a_quien_no_inventa_responsable(chat: Chat_) -> None:
    texto = await chat.texto("/a_quien horario del casino")
    assert "no te indico un responsable" in texto
    assert "Dependencia:" not in texto
