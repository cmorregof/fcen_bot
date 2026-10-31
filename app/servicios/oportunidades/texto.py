"""De HTML a texto plano para el modelo, con los enlaces de la página.

Los enlaces se conservan porque el verificador comprueba que el enlace de cada
oferta salga de la página (el modelo no puede inventarlo).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from app.core.programas import normalizar

_OMITIR = {"script", "style", "noscript", "svg", "template", "head"}
_BLOQUE = {
    "p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "td", "th", "dt", "dd",
}  # fmt: skip


class _Lector(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.partes: list[str] = []
        self.enlaces: set[str] = set()
        self._omitir = 0
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _OMITIR:
            self._omitir += 1
        if tag in _BLOQUE:
            self.partes.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href and not href.startswith(("mailto:", "tel:", "javascript:")):
                url = urldefrag(urljoin(self.base, href))[0]
                if urlsplit(url).scheme in ("http", "https"):
                    self._href = url
                    self.enlaces.add(url)

    def handle_endtag(self, tag: str) -> None:
        if tag in _OMITIR and self._omitir:
            self._omitir -= 1
        if tag == "a" and self._href:
            self.partes.append(f" <{self._href}>")
            self._href = None

    def handle_data(self, data: str) -> None:
        if not self._omitir:
            self.partes.append(data)


def a_texto(html: str, base: str) -> tuple[str, set[str]]:
    lector = _Lector(base)
    lector.feed(html)
    lector.close()
    texto = "".join(lector.partes)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)
    return texto.strip(), lector.enlaces


_CORREO = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# Celulares (3xx xxx xxxx) y fijos (60x xxx xxxx) de Colombia, con o sin +57.
_TELEFONO = re.compile(
    r"(?<!\d)(?<!\d\.)(?:\+?57[ -]?)?(?:3\d{2}|\(?60\d\)?)[ -]?\d{3}[ -]?\d{4}(?!\d|\.\d)"
)


def sin_contactos(texto: str) -> str:
    """Quita correos y teléfonos: no se guardan datos de contacto de personas."""
    texto = _CORREO.sub("[contacto en la fuente]", texto)
    return _TELEFONO.sub("[contacto en la fuente]", texto)


def clave_url(url: str) -> str:
    """URL normalizada para encontrar duplicados."""
    partes = urlsplit(url.strip())
    host = (partes.hostname or "").lower().removeprefix("www.")
    ruta = partes.path.rstrip("/") or "/"
    consulta = "&".join(
        sorted(
            p
            for p in partes.query.split("&")
            if p and not p.lower().startswith(("utm_", "fbclid", "gclid"))
        )
    )
    return urlunsplit(("", host, ruta, consulta, ""))[2:]


def clave_texto(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalizar(texto)).strip()
