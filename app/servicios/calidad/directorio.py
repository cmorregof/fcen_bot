"""Directorio «a quién acudo»: trámite → dependencia → cargo → correo.

Responde solo con lo que está en el YAML. Si el tema no aparece lo dice, en vez
de inventar un responsable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.plan import plegar


@dataclass(frozen=True)
class Tramite:
    tema: str
    palabras_clave: tuple[str, ...]
    dependencia: str
    cargo: str
    correo: str
    vigencia: str


def cargar(ruta: Path | None = None) -> list[Tramite]:
    ruta = ruta or calidad_settings.directorio_path
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return [
        Tramite(
            tema=str(t["tema"]),
            palabras_clave=tuple(str(p) for p in t.get("palabras_clave", [])),
            dependencia=str(t["dependencia"]),
            cargo=str(t["cargo"]),
            correo=str(t.get("correo", "PARA COMPLETAR")),
            vigencia=str(t.get("vigencia", "PARA COMPLETAR")),
        )
        for t in datos.get("tramites", [])
    ]


def _raices(texto: str) -> set[str]:
    return {p[:5] for p in plegar(texto).split() if len(p) >= 4}


def buscar(consulta: str, tramites: list[Tramite], maximo: int = 3) -> list[Tramite]:
    """Ordena por coincidencia de raíces (5 letras) con el tema y las palabras clave."""
    pedidas = _raices(consulta)
    if not pedidas:
        return []
    puntajes: list[tuple[int, int, Tramite]] = []
    for i, t in enumerate(tramites):
        puntaje = 0
        for clave in t.palabras_clave:
            if plegar(clave) in plegar(consulta):
                puntaje += 3
            puntaje += len(pedidas & _raices(clave))
        puntaje += len(pedidas & _raices(t.tema))
        if puntaje:
            puntajes.append((-puntaje, i, t))
    return [t for _, _, t in sorted(puntajes, key=lambda x: x[:2])[:maximo]]
