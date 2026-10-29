"""Cruce por acción: indicador vs. descripciones de sus soportes.

El modelo PROPONE un veredicto, una justificación, lo que falta y un % de
avance, con citas [ID] a los archivos. Nada de eso es una decisión: la oficina
de calidad lo aprueba o lo ajusta en `cruce_acciones.xlsx`.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable

from pydantic import ValidationError

from app.servicios.calidad.soportes.cliente import ClienteModelo
from app.servicios.calidad.soportes.describir import Cache
from app.servicios.calidad.soportes.modelos import (
    Accion,
    Archivo,
    Cruce,
    CruceAccion,
    Descripcion,
    ResumenCierre,
    Uso,
)
from app.servicios.calidad.soportes.verificador import (
    citas_en_texto,
    verificar_citas,
    verificar_cruce,
)

MODELO_CRUCE = "claude-opus-5-5"
VERSION_PROMPT = "cruce-v1"

SISTEMA_CRUCE = """Eres asistente de la oficina de calidad académica de una \
facultad universitaria. Preparas una PROPUESTA de cierre de una acción de un plan \
de mejoramiento: comparas el indicador de la acción con los soportes que hay en \
su carpeta. La propuesta la revisan y aprueban la oficina de calidad, el Comité \
Asesor y el Consejo de Facultad; tú no decides.

Reglas:
- Usa solo las descripciones de soportes que se te dan. No supongas que existe \
algo que no está en la lista.
- Cita cada soporte con su ID entre corchetes, p. ej. [S012], en la \
justificación y en el párrafo de cierre. Cita solo IDs de la lista.
- Veredicto: «evidencia suficiente» si los soportes prueban el indicador en el \
periodo; «parcial» si prueban una parte (algunos semestres, sin cifras, sin \
fecha, solo intención); «sin evidencia» si no hay soportes pertinentes.
- El % de avance propuesto refleja lo que prueban los soportes, no lo que \
declara el plan.
- «falta» dice en concreto qué soporte haría falta para probar el indicador.
- El párrafo de cierre va en tercera persona, tono institucional, 3 a 6 frases, \
para el informe de autoevaluación. No afirmes más de lo que prueban los soportes.
- No escribas nombres de personas.
Registra tu propuesta con la herramienta `registrar_cruce`."""

SISTEMA_RESUMEN = """Eres asistente de la oficina de calidad académica de una \
facultad universitaria. Redactas un BORRADOR de resumen general del cierre de un \
plan de mejoramiento para el informe de autoevaluación del programa, a partir de \
las propuestas por acción. No decides: el borrador lo aprueban la oficina de \
calidad, el Comité Asesor y el Consejo de Facultad.

Reglas:
- Dos a cuatro párrafos, tercera persona, tono institucional.
- Di con franqueza qué acciones tienen evidencia suficiente, cuáles parcial y \
cuáles no tienen evidencia.
- Cita soportes con su ID entre corchetes, p. ej. [S012], solo de los que se te dan.
- No escribas nombres de personas.
Registra el resumen con la herramienta `registrar_resumen`."""


def linea_soporte(archivo: Archivo, desc: Descripcion | None) -> str:
    meta = [archivo.tipo]
    if archivo.paginas and archivo.tipo == "pdf":
        meta.append(f"{archivo.paginas} pág.")
    if archivo.fecha:
        meta.append(f"fecha en metadatos {archivo.fecha}")
    if archivo.dentro_de_zip:
        meta.append(f"dentro de {archivo.dentro_de_zip}")
    cabeza = f"[{archivo.id}] {archivo.nombre} ({', '.join(meta)})"
    if desc is None or desc.datos is None:
        motivo = desc.error if desc else "sin descripción"
        return f"{cabeza}\n    Sin descripción del modelo: {motivo}."
    d = desc.datos
    partes = [
        cabeza,
        f"    Qué es: {d.que_es}",
        f"    Fecha del documento: {d.fecha_documento or 'no aparece'}",
        f"    Qué podría probar: {d.que_prueba}",
    ]
    if d.ilegible_o_incompleto:
        partes.append("    ⚠ Se ve ilegible o incompleto.")
    if d.observacion:
        partes.append(f"    Observación: {d.observacion}")
    return "\n".join(partes)


def texto_cruce(
    accion: Accion,
    soportes: list[Archivo],
    generales: list[Archivo],
    descripciones: dict[str, Descripcion],
) -> str:
    partes = [
        f"Acción {accion.codigo}",
        f"Aspecto a mejorar: {accion.aspecto}",
        f"Objetivo: {accion.objetivo}",
        f"Acción: {accion.descripcion}",
        f"Indicador de cumplimiento (meta): {accion.indicador}",
        f"Periodo de ejecución: {accion.inicio} a {accion.fin}",
        "",
        f"Soportes en la carpeta de la acción ({len(soportes)}):",
    ]
    if soportes:
        partes += [linea_soporte(a, descripciones.get(a.id)) for a in soportes]
    else:
        partes.append("(la carpeta no tiene soportes)")
    if generales:
        partes += [
            "",
            "Documentos generales del plan (pueden citarse si mencionan esta acción):",
        ]
        partes += [linea_soporte(a, descripciones.get(a.id)) for a in generales]
    partes += ["", "Prepara la propuesta de cierre de esta acción."]
    return "\n".join(partes)


def _clave(modelo: str, version: str, texto: str) -> str:
    return (
        "cruce-"
        + hashlib.sha256(f"{modelo}|{version}|{texto}".encode()).hexdigest()[:32]
    )


async def cruzar_accion(
    accion: Accion,
    inventario: list[Archivo],
    descripciones: dict[str, Descripcion],
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso,
    modelo: str = MODELO_CRUCE,
) -> Cruce:
    soportes = [a for a in inventario if a.accion == accion.codigo]
    generales = [a for a in inventario if not a.accion and a.tipo != "zip"]
    texto = texto_cruce(accion, soportes, generales, descripciones)
    clave = _clave(modelo, VERSION_PROMPT, texto)
    indice = {a.id: a for a in inventario}

    propuesta: CruceAccion | None = None
    guardado = cache.leer(clave)
    if guardado and guardado.get("datos"):
        try:
            propuesta = CruceAccion.model_validate(guardado["datos"])
        except ValidationError:
            propuesta = None
    error = ""
    if propuesta is None:
        resp = await cliente.llamar(
            modelo=modelo,
            sistema=SISTEMA_CRUCE,
            bloques=[],
            texto=texto,
            salida=CruceAccion,
            nombre_herramienta="registrar_cruce",
            esfuerzo="high",
            max_tokens=16000,
        )
        uso.sumar(modelo, resp.tokens_entrada, resp.tokens_salida)
        if resp.entrada is None:
            error = resp.error
        else:
            try:
                propuesta = CruceAccion.model_validate(resp.entrada)
                cache.guardar(clave, {"datos": propuesta.model_dump(mode="json")})
            except ValidationError:
                error = "el modelo devolvió datos no válidos"
    cruce = Cruce(accion, propuesta, error)
    verificar_cruce(cruce, indice)
    return cruce


async def cruzar_todas(
    acciones: list[Accion],
    inventario: list[Archivo],
    descripciones: dict[str, Descripcion],
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso,
    concurrencia: int = 4,
    modelo: str = MODELO_CRUCE,
    progreso: Callable[[Cruce], None] | None = None,
) -> list[Cruce]:
    semaforo = asyncio.Semaphore(concurrencia)

    async def una(accion: Accion) -> Cruce:
        async with semaforo:
            cruce = await cruzar_accion(
                accion, inventario, descripciones, cliente, cache, uso, modelo
            )
        if progreso:
            progreso(cruce)
        return cruce

    return list(await asyncio.gather(*(una(a) for a in acciones)))


def texto_resumen(cruces: list[Cruce]) -> str:
    partes = ["Propuestas por acción:"]
    for c in cruces:
        a = c.accion
        if c.propuesta is None:
            partes.append(
                f"- Acción {a.codigo} ({a.descripcion}): sin propuesta ({c.error})."
            )
            continue
        p = c.propuesta
        partes.append(
            f"- Acción {a.codigo} ({a.descripcion}). Indicador: {a.indicador}. "
            f"Veredicto propuesto: {p.veredicto.value}; avance propuesto "
            f"{p.avance_propuesto} %. Justificación: {p.justificacion} "
            f"Falta: {p.falta or 'nada'}"
        )
    partes.append("\nRedacta el resumen general del cierre del plan.")
    return "\n".join(partes)


async def resumir(
    cruces: list[Cruce],
    inventario: list[Archivo],
    cliente: ClienteModelo,
    cache: Cache,
    uso: Uso,
    modelo: str = MODELO_CRUCE,
) -> tuple[ResumenCierre | None, str, list[str]]:
    """Devuelve (resumen, error, alertas de citas)."""
    texto = texto_resumen(cruces)
    clave = _clave(modelo, VERSION_PROMPT + "-resumen", texto)
    resumen: ResumenCierre | None = None
    guardado = cache.leer(clave)
    if guardado and guardado.get("datos"):
        try:
            resumen = ResumenCierre.model_validate(guardado["datos"])
        except ValidationError:
            resumen = None
    error = ""
    if resumen is None:
        resp = await cliente.llamar(
            modelo=modelo,
            sistema=SISTEMA_RESUMEN,
            bloques=[],
            texto=texto,
            salida=ResumenCierre,
            nombre_herramienta="registrar_resumen",
            esfuerzo="medium",
            max_tokens=12000,
        )
        uso.sumar(modelo, resp.tokens_entrada, resp.tokens_salida)
        if resp.entrada is None:
            return None, resp.error, []
        try:
            resumen = ResumenCierre.model_validate(resp.entrada)
            cache.guardar(clave, {"datos": resumen.model_dump(mode="json")})
        except ValidationError:
            return None, "el modelo devolvió datos no válidos", []
    estados = verificar_citas(
        citas_en_texto(resumen.resumen), {a.id: a for a in inventario}
    )
    alertas = [f"Cita {e.cita}: {e.nota}" for e in estados if not e.valida]
    return resumen, error, alertas
