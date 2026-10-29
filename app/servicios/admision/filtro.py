"""Filtro de credenciales: el bot nunca pide ni acepta correo ni contraseña.

Se aplica antes de enviar cualquier texto al modelo. El texto original no se
guarda en ningún lado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PALABRA = re.compile(
    r"(?i)\b(contrase[nñ]a|clave|password|passwd|pwd|pass|usuario|user|login)\b"
)
_CONECTOR = re.compile(r"(?i)(?:\b(?:es|era|son|ser[ií]a)\b|[:=])")
_OMITIDO = "[omitido]"


def _parece_secreto(resto: str) -> bool:
    """¿Lo que sigue a la palabra clave trae un valor? Ante la duda, sí."""
    if _CONECTOR.search(resto):
        return True
    return any(re.search(r"[\d\W_]", t.strip("?,.;")) for t in resto.split())


def _fin_del_tramo(texto: str, desde: int) -> int:
    """Hasta el fin de la línea o hasta una nueva pregunta (¿)."""
    cortes = [c for c in (texto.find("\n", desde), texto.find("¿", desde)) if c != -1]
    return min(cortes) if cortes else len(texto)


@dataclass(frozen=True)
class Filtrado:
    texto: str
    credenciales: bool


def filtrar(texto: str) -> Filtrado:
    """Omite correos y todo lo que siga a «contraseña», «clave» o «usuario»."""
    texto, n_correos = _CORREO.subn("[correo omitido]", texto)
    salida: list[str] = []
    pos = 0
    omitio = False
    while (m := _PALABRA.search(texto, pos)) is not None:
        fin = _fin_del_tramo(texto, m.end())
        resto = texto[m.end() : fin]
        if _parece_secreto(resto):
            salida.append(texto[pos : m.end()] + " " + _OMITIDO + " ")
            pos = fin
            omitio = True
        else:
            salida.append(texto[pos : m.end()])
            pos = m.end()
    salida.append(texto[pos:])
    return Filtrado("".join(salida).strip(), n_correos > 0 or omitio)


def tiene_contenido(texto: str) -> bool:
    """True si, tras filtrar, queda algo que valga la pena preguntar al modelo."""
    limpio = re.sub(r"\[(?:correo omitido|omitido)\]", " ", texto)
    limpio = re.sub(
        r"(?i)\b(contrase[nñ]a|clave|password|passwd|pwd|pass|es|mi|la|correo|usuario|user|login)\b",
        " ",
        limpio,
    )
    return len(re.findall(r"\w", limpio)) >= 10
