"""Acceso a la red del buscador y del verificador, con respeto por los sitios.

- Se identifica con un User-Agent propio (quién consulta y para qué).
- Lee robots.txt antes de cada sitio y no pide lo que este prohíbe. Si
  robots.txt no responde (error de red o 5xx), no se consulta el sitio.
- Respeta Crawl-delay y deja una pausa mínima entre pedidos al mismo sitio.
- No inicia sesión, no resuelve captchas y no reintenta ante 401, 403 o 429:
  lo registra como bloqueo y sigue con la siguiente fuente.

Las pruebas usan un transporte falso (sin red) con la misma interfaz.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.servicios.oportunidades.config import config


@dataclass(frozen=True)
class Respuesta:
    estado: int
    texto: str
    url: str


class Transporte(Protocol):
    async def obtener(self, url: str) -> Respuesta: ...


class Bloqueado(Exception):
    """El sitio no permite la consulta (robots.txt, 401, 403 o 429)."""


class TransporteHttp:
    """Transporte real con httpx. Solo GET, sin cookies ni credenciales."""

    def __init__(self) -> None:
        self._cliente = httpx.AsyncClient(
            timeout=config.timeout_segundos,
            follow_redirects=True,
            headers={"User-Agent": config.user_agent},
        )

    async def obtener(self, url: str) -> Respuesta:
        r = await self._cliente.get(url)
        return Respuesta(r.status_code, r.text, str(r.url))

    async def cerrar(self) -> None:
        await self._cliente.aclose()


class Cortes:
    """Envuelve un transporte: robots.txt, pausas y bloqueos por sitio."""

    def __init__(
        self,
        transporte: Transporte,
        *,
        user_agent: str | None = None,
        pausa: float | None = None,
    ) -> None:
        self._t = transporte
        self._ua = user_agent or config.user_agent
        self._pausa = config.pausa_segundos if pausa is None else pausa
        self._robots: dict[str, RobotFileParser | None] = {}
        self._ultimo: dict[str, float] = {}

    async def _reglas(self, origen: str) -> RobotFileParser | None:
        """None: el sitio no se puede consultar."""
        if origen in self._robots:
            return self._robots[origen]
        parser: RobotFileParser | None = RobotFileParser()
        assert parser is not None
        try:
            r = await self._t.obtener(f"{origen}/robots.txt")
        except (httpx.HTTPError, OSError):
            parser = None
        else:
            if r.estado >= 500 or r.estado in (401, 403):
                # Sin poder leer las reglas (o con acceso negado), no se entra.
                parser = None
            elif r.estado >= 400:
                parser.parse([])  # sin robots.txt: todo permitido
            else:
                parser.parse(r.texto.splitlines())
        self._robots[origen] = parser
        return parser

    async def permitido(self, url: str) -> bool:
        partes = urlsplit(url)
        reglas = await self._reglas(f"{partes.scheme}://{partes.netloc}")
        return reglas is not None and reglas.can_fetch(self._ua, url)

    async def obtener(self, url: str) -> Respuesta:
        partes = urlsplit(url)
        origen = f"{partes.scheme}://{partes.netloc}"
        reglas = await self._reglas(origen)
        if reglas is None or not reglas.can_fetch(self._ua, url):
            raise Bloqueado(f"robots.txt de {partes.netloc} no permite consultar {url}")
        retardo = reglas.crawl_delay(self._ua)
        pausa = max(self._pausa, float(retardo or 0))
        espera = self._ultimo.get(origen, 0.0) + pausa - time.monotonic()
        if espera > 0:
            await asyncio.sleep(espera)
        try:
            r = await self._t.obtener(url)
        finally:
            self._ultimo[origen] = time.monotonic()
        if r.estado in (401, 403, 429):
            raise Bloqueado(f"{partes.netloc} respondió {r.estado}; no se insiste")
        return r
