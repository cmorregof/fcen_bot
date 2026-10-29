"""Filtro de credenciales: el bot nunca pide ni acepta correo ni contraseña.

Se aplica antes de enviar cualquier texto al modelo. El texto original no se
guarda en ningún lado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CLAVE = re.compile(
    r"(?i)\b(contrase[nñ]a|clave|password|passwd|pwd|pass)\b"
    r"(\s*(?:es|era|:|=|-)?\s*)(\S+)"
)
_RELLENO = {"de", "del", "la", "el", "mi", "para", "en", "que", "no", "es", "es:"}


@dataclass(frozen=True)
class Filtrado:
    texto: str
    credenciales: bool


def _reemplazar_clave(m: re.Match[str]) -> str:
    if m.group(3).lower().strip(".,;:") in _RELLENO and not m.group(2).strip():
        # «la contraseña de la plataforma»: se menciona, no se entrega
        return m.group(0)
    return f"{m.group(1)}{m.group(2)}[omitida]"


def filtrar(texto: str) -> Filtrado:
    sin_correo, n_correos = _CORREO.subn("[correo omitido]", texto)
    sin_clave = _CLAVE.sub(_reemplazar_clave, sin_correo)
    return Filtrado(sin_clave, n_correos > 0 or sin_clave != sin_correo)


def tiene_contenido(texto: str) -> bool:
    """True si, tras filtrar, queda algo que valga la pena preguntar al modelo."""
    limpio = re.sub(r"\[(?:correo omitido|omitida)\]", " ", texto)
    limpio = re.sub(
        r"(?i)\b(contrase[nñ]a|clave|password|passwd|pwd|pass|es|mi|correo|usuario)\b",
        " ",
        limpio,
    )
    return len(re.findall(r"\w", limpio)) >= 10
