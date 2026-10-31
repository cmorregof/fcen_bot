"""Fuentes, red y modelo FALSOS para el servicio de oportunidades.

Todo es inventado: dominios .invalid, empresas ficticias, sin estudiantes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.services.indicadores import hoy_local
from app.servicios.oportunidades import buscador
from app.servicios.oportunidades.config import config
from app.servicios.oportunidades.fuentes import Fuente
from app.servicios.oportunidades.lector import Lectura
from app.servicios.oportunidades.modelo import OfertaLeida
from app.servicios.oportunidades.transporte import Cortes, Respuesta

HOY = hoy_local()


def dia(n: int) -> date:
    return HOY + timedelta(days=n)


FUENTES_YAML = """
fuentes:
  - clave: portal_alfa
    nombre: Portal Alfa (ficticio)
    url: https://alfa.invalid/ofertas
    activa: true
    tipos: [practica, empleo]
  - clave: portal_beta
    nombre: Portal Beta (ficticio, robots lo prohíbe)
    url: https://beta.invalid/empleos
    activa: true
  - clave: portal_gamma
    nombre: Portal Gamma (ficticio, responde 403)
    url: https://gamma.invalid/
    activa: true
  - clave: portal_apagado
    nombre: Portal apagado
    url: https://apagado.invalid/
    activa: false
excluidas:
  - nombre: Portal privado ficticio
    motivo: sus términos prohíben la extracción
"""

PAGINA_ALFA = """
<html><head><title>Ofertas</title><script>var x = 1;</script></head><body>
<h1>Ofertas vigentes</h1>
<div><a href="/ofertas/101">Practicante de estadística</a> — Empresa Ficticia Uno.
Contacto: persona.ficticia@ejemplo.invalid, cel. 300 123 4567. Salario $ 2.500.000.</div>
<div><a href="https://alfa.invalid/ofertas/102">Analista junior</a> — Empresa Ficticia Dos</div>
<div><a href="/ofertas/103">Pasantía vencida</a></div>
</body></html>
"""


class TransporteFalso:
    """Sin red: responde lo que esté en ``paginas`` y 404 a lo demás."""

    def __init__(self, paginas: dict[str, tuple[int, str]] | None = None) -> None:
        self.paginas: dict[str, tuple[int, str]] = {
            "https://alfa.invalid/robots.txt": (
                200,
                "User-agent: *\nDisallow: /privado/\n",
            ),
            "https://alfa.invalid/ofertas": (200, PAGINA_ALFA),
            "https://alfa.invalid/ofertas/101": (200, "ok"),
            "https://alfa.invalid/ofertas/102": (200, "ok"),
            "https://alfa.invalid/ofertas/103": (404, "no"),
            "https://beta.invalid/robots.txt": (200, "User-agent: *\nDisallow: /\n"),
            "https://gamma.invalid/robots.txt": (404, ""),
            "https://gamma.invalid/": (403, "prohibido"),
            **(paginas or {}),
        }
        self.pedidos: list[str] = []

    async def obtener(self, url: str) -> Respuesta:
        self.pedidos.append(url)
        estado, texto = self.paginas.get(url, (404, ""))
        return Respuesta(estado, texto, url)


def leida(**cambios: object) -> OfertaLeida:
    base: dict[str, object] = {
        "titulo": "Practicante de estadística",
        "entidad": "Empresa Ficticia Uno",
        "tipo": "practica",
        "url": "https://alfa.invalid/ofertas/101",
        "resumen": "Apoyo en análisis de datos. Escribir a persona.ficticia@ejemplo.invalid",
        "requisitos": "Estudiante de 7.º semestre o más",
        "programas": ["estadistica"],
        "fecha_cierre": dia(20),
        "modalidad": "hibrida",
        "lugar": "Manizales",
    }
    base.update(cambios)
    return OfertaLeida.model_validate(base)


def ofertas_alfa() -> list[OfertaLeida]:
    return [
        leida(),
        leida(
            titulo="Analista junior",
            entidad="Empresa Ficticia Dos",
            tipo="empleo",
            url="https://alfa.invalid/ofertas/102",
            programas=["ciencias_computacion", "no_existe"],
            fecha_cierre=dia(30),
        ),
        leida(
            titulo="Pasantía vencida",
            entidad="Empresa Ficticia Tres",
            tipo="pasantia",
            url="https://alfa.invalid/ofertas/103",
            fecha_cierre=dia(-3),
        ),
        # Enlace inventado por el modelo: no está en la página.
        leida(
            titulo="Beca inventada",
            entidad="Fundación Ficticia",
            tipo="beca",
            url="https://otro.invalid/beca",
            programas=["mcf"],
            fecha_cierre=dia(40),
        ),
    ]


@dataclass
class LectorFalso:
    por_fuente: dict[str, list[OfertaLeida]] = field(default_factory=dict)
    tokens_in: int = 8_000
    tokens_out: int = 1_500
    lecturas: list[str] = field(default_factory=list)
    textos: list[str] = field(default_factory=list)

    async def leer(self, *, fuente: Fuente, url: str, texto: str, hoy: date) -> Lectura:
        self.lecturas.append(fuente.clave)
        self.textos.append(texto)
        return Lectura(
            list(self.por_fuente.get(fuente.clave, [])), self.tokens_in, self.tokens_out
        )


@pytest.fixture
def fuentes_falsas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ruta = tmp_path / "oportunidades.yaml"
    ruta.write_text(FUENTES_YAML, encoding="utf-8")
    monkeypatch.setattr(config, "fuentes_path", ruta)
    monkeypatch.setattr(config, "pausa_segundos", 0.0)
    monkeypatch.setattr(config, "tope_usd_corrida", 1.0)
    return ruta


@dataclass
class Falsos:
    transporte: TransporteFalso
    lector: LectorFalso


@pytest.fixture
def falsos(fuentes_falsas: Path, monkeypatch: pytest.MonkeyPatch) -> Falsos:
    f = Falsos(TransporteFalso(), LectorFalso({"portal_alfa": ofertas_alfa()}))
    monkeypatch.setattr(buscador, "crear_transporte", lambda: f.transporte)
    monkeypatch.setattr(buscador, "crear_lector", lambda: f.lector)
    return f


def cortes(t: TransporteFalso) -> Cortes:
    return Cortes(t, pausa=0.0)
