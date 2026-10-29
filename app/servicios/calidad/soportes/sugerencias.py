"""Sugerencias para las acciones que quedaron «sin evidencia».

Se arma un reporte en Markdown con lo que Sonnet describió de cada soporte y lo
que propuso el cruce. Con ese reporte, Opus (esfuerzo medio) hace UNA sola
llamada para todas las acciones: dónde buscar el soporte que falta y qué acción
poner en el próximo plan. Las sugerencias van aparte: no son evidencia ni
cambian el veredicto.
"""

from __future__ import annotations

import hashlib

from pydantic import ValidationError

from app.servicios.calidad.soportes.cliente import ClienteModelo
from app.servicios.calidad.soportes.cruce import linea_soporte
from app.servicios.calidad.soportes.describir import Cache
from app.servicios.calidad.soportes.modelos import (
    Archivo,
    Cruce,
    Descripcion,
    SugerenciasCierre,
    Uso,
    Veredicto,
)

MODELO_SUGERENCIAS = "claude-opus-5-5"
VERSION_PROMPT = "sug-v1"

SISTEMA_SUGERENCIAS = """Eres asistente de la oficina de calidad académica de \
una facultad universitaria. Te dan un reporte de las acciones de un plan de \
mejoramiento para las que no se encontró evidencia. Para cada una propones:

1. «donde_buscar»: qué soportes de la época podrían existir y dónde buscarlos \
en una universidad pública colombiana (actas de comité o consejo, correos \
institucionales, afiches o piezas de difusión, sistemas académicos, informes de \
gestión, páginas web archivadas). Concreto y por semestre si aplica.
2. «accion_proximo_plan»: si la acción de verdad no se hizo, una acción concreta \
y medible para el próximo plan, con un indicador verificable y el soporte que \
debería quedar archivado.

Reglas:
- Son sugerencias: no afirmes que algo se hizo ni que no se hizo.
- No inventes nombres de dependencias, sistemas o normas que no conozcas con \
certeza; si dudas, descríbelos de forma genérica.
- No escribas nombres de personas.
- Una sugerencia por cada acción del reporte, con su código.
Registra las sugerencias con la herramienta `registrar_sugerencias`."""


def reporte_md(
    cruces: list[Cruce],
    inventario: list[Archivo],
    descripciones: dict[str, Descripcion],
    programa: str,
) -> str:
    """Reporte en Markdown de las acciones sin evidencia (lo describió Sonnet)."""
    sin = [
        c
        for c in cruces
        if c.propuesta and c.propuesta.veredicto == Veredicto.SIN_EVIDENCIA
    ]
    partes = [
        f"# Acciones sin evidencia — {programa}",
        "",
        "Reporte armado con las descripciones de los soportes (Sonnet) y la "
        "propuesta del cruce (Opus). Es insumo para las sugerencias.",
    ]
    for c in sin:
        a, p = c.accion, c.propuesta
        assert p is not None
        partes += [
            "",
            f"## Acción {a.codigo}. {a.descripcion}",
            f"- **Aspecto:** {a.aspecto}",
            f"- **Objetivo:** {a.objetivo}",
            f"- **Indicador:** {a.indicador}",
            f"- **Periodo de ejecución:** {a.inicio} a {a.fin}",
            "",
            "### Soportes en la carpeta",
        ]
        soportes = [x for x in inventario if x.accion == a.codigo]
        if soportes:
            partes += [linea_soporte(x, descripciones.get(x.id)) for x in soportes]
        else:
            partes.append("(la carpeta no tiene soportes)")
        partes += [
            "",
            "### Por qué quedó sin evidencia (propuesta del cruce)",
            p.justificacion,
            "",
            "### Lo que falta",
            p.falta or "(no se indicó)",
        ]
    return "\n".join(partes) + "\n"


async def sugerir(
    cruces: list[Cruce],
    reporte: str,
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso,
    modelo: str = MODELO_SUGERENCIAS,
) -> str:
    """Pone la sugerencia en cada cruce sin evidencia. Devuelve un error o ""."""
    sin = {
        c.accion.codigo: c
        for c in cruces
        if c.propuesta and c.propuesta.veredicto == Veredicto.SIN_EVIDENCIA
    }
    if not sin:
        return ""
    texto = reporte + "\nPropón las sugerencias para cada acción del reporte."
    clave = (
        "sug-"
        + hashlib.sha256(
            f"{modelo}|{VERSION_PROMPT}|{SISTEMA_SUGERENCIAS}|{texto}".encode()
        ).hexdigest()[:32]
    )
    datos: SugerenciasCierre | None = None
    guardado = cache.leer(clave)
    if guardado and guardado.get("datos"):
        try:
            datos = SugerenciasCierre.model_validate(guardado["datos"])
        except ValidationError:
            datos = None
    if datos is None:
        resp = await cliente.llamar(
            modelo=modelo,
            sistema=SISTEMA_SUGERENCIAS,
            bloques=[],
            texto=texto,
            salida=SugerenciasCierre,
            nombre_herramienta="registrar_sugerencias",
            esfuerzo="medium",
            max_tokens=12000,
        )
        uso.registrar(modelo, resp)
        if resp.entrada is None:
            return resp.error
        try:
            datos = SugerenciasCierre.model_validate(resp.entrada)
        except ValidationError:
            return "el modelo devolvió datos no válidos"
        cache.guardar(clave, {"datos": datos.model_dump(mode="json")})
    for s in datos.sugerencias:
        cruce = sin.get(s.accion.strip())
        if cruce is not None:
            cruce.sugerencia = s
    faltan = [k for k, c in sin.items() if c.sugerencia is None]
    return f"sin sugerencia para: {', '.join(faltan)}" if faltan else ""
