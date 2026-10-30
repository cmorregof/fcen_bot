"""Orquesta la revisión completa y estima su costo antes de correrla."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.servicios.calidad.soportes import contenido
from app.servicios.calidad.soportes.cliente import ClienteConTope, ClienteModelo
from app.servicios.calidad.soportes.cruce import (
    MODELO_CRUCE,
    cruzar_todas,
    resumir,
)
from app.servicios.calidad.soportes.describir import (
    MODELO_DESCRIPCION,
    Cache,
    clave_descripcion,
    describir_todos,
)
from app.servicios.calidad.soportes.indice import guardar_indice
from app.servicios.calidad.soportes.inventario import inventariar
from app.servicios.calidad.soportes.modelos import (
    PRECIOS_USD_POR_MILLON,
    Accion,
    Archivo,
    Cruce,
    Descripcion,
    Uso,
)
from app.servicios.calidad.soportes.plan_acciones import leer_acciones
from app.servicios.calidad.soportes.salidas import (
    borrador_docx,
    cruce_xlsx,
    inventario_xlsx,
)
from app.servicios.calidad.soportes.sugerencias import reporte_md, sugerir

# Supuestos de la estimación (tokens). Son holgados a propósito.
TOKENS_POR_PAGINA_PDF = 2500
TOKENS_POR_IMAGEN = 1700
TOKENS_FIJOS_DESCRIPCION = 1200  # sistema + herramienta + metadatos
SALIDA_DESCRIPCION = 1200  # incluye razonamiento
TOKENS_POR_DESCRIPCION_EN_CRUCE = 150
SALIDA_CRUCE = 6000
SALIDA_SUGERENCIAS = 4000


@dataclass
class Estimacion:
    archivos_al_modelo: int
    en_cache: int
    tokens_descripcion: tuple[int, int]
    tokens_cruce: tuple[int, int]

    @property
    def costo(self) -> float:
        p_d = PRECIOS_USD_POR_MILLON[MODELO_DESCRIPCION]
        p_c = PRECIOS_USD_POR_MILLON[MODELO_CRUCE]
        return (
            self.tokens_descripcion[0] * p_d[0] / 1e6
            + self.tokens_descripcion[1] * p_d[1] / 1e6
            + self.tokens_cruce[0] * p_c[0] / 1e6
            + self.tokens_cruce[1] * p_c[1] / 1e6
        )


def estimar(
    archivos: list[Archivo], acciones: list[Accion], cache: Cache
) -> Estimacion:
    por_codigo = {acc.codigo: acc for acc in acciones}
    al_modelo = 0
    en_cache = 0
    ent = sal = 0
    for a in archivos:
        if a.tipo not in ("pdf", "imagen", "xlsx", "docx"):
            continue
        if cache.leer(
            clave_descripcion(a, MODELO_DESCRIPCION, por_codigo.get(a.accion))
        ):
            en_cache += 1
            continue
        al_modelo += 1
        ent += TOKENS_FIJOS_DESCRIPCION
        if a.tipo == "pdf":
            paginas = min(a.paginas or 1, contenido.PAGINAS_PDF)
            ent += paginas * TOKENS_POR_PAGINA_PDF + contenido.CARACTERES_TEXTO // 4
        elif a.tipo == "imagen":
            ent += TOKENS_POR_IMAGEN
        else:
            ent += contenido.CARACTERES_TEXTO // 4
        sal += SALIDA_DESCRIPCION
    generales = sum(1 for a in archivos if not a.accion)
    ent_c = sal_c = 0
    for acc in acciones:
        propios = sum(1 for a in archivos if a.accion == acc.codigo)
        ent_c += 2500 + (propios + generales) * TOKENS_POR_DESCRIPCION_EN_CRUCE
        sal_c += SALIDA_CRUCE
    ent_c += 2500 + len(acciones) * 400  # resumen
    sal_c += SALIDA_CRUCE
    # Sugerencias: una llamada; se supone que todas las acciones quedan sin
    # evidencia (cota alta). Los cruces en caché no se descuentan: la clave
    # depende de las descripciones, que aún no existen.
    ent_c += 2500 + len(acciones) * (400 + 3 * TOKENS_POR_DESCRIPCION_EN_CRUCE)
    sal_c += SALIDA_SUGERENCIAS
    return Estimacion(al_modelo, en_cache, (ent, sal), (ent_c, sal_c))


def excede_tope(est: Estimacion, tope_usd: float) -> str:
    """Mensaje si la estimación pasa del tope; vacío si cabe."""
    if est.costo <= tope_usd:
        return ""
    return (
        f"La estimación ({est.costo:.2f} USD) pasa del tope por corrida "
        f"({tope_usd:.2f} USD). Divida los soportes o pida subir el tope."
    )


# Pasos de una corrida, en orden: (clave, título para la persona).
PASOS: tuple[tuple[str, str], ...] = (
    ("descripcion", "Descripción de cada soporte"),
    ("cruce", "Cruce de cada acción con sus soportes"),
    ("resumen", "Resumen y sugerencias"),
    ("salidas", "Archivos para descargar"),
)


@dataclass
class Informe:
    archivos: list[Archivo]
    acciones: list[Accion]
    descripciones: dict[str, Descripcion]
    cruces: list[Cruce]
    uso: Uso
    segundos: float
    salidas: dict[str, Path] = field(default_factory=dict)
    alertas_resumen: list[str] = field(default_factory=list)
    error_resumen: str = ""
    error_sugerencias: str = ""
    detenida: str = ""  # por el tope, sin créditos o con la clave inválida

    def veredictos(self) -> Counter[str]:
        return Counter(
            c.propuesta.veredicto.value if c.propuesta else "sin propuesta"
            for c in self.cruces
        )

    def resumen(self) -> dict[str, object]:
        """Cifras de la corrida, sin nombres de archivos ni de personas."""
        sin_desc = [d for d in self.descripciones.values() if d.datos is None]
        return {
            "archivos": len(self.archivos),
            "acciones": len(self.acciones),
            "minutos": round(self.segundos / 60, 1),
            "costo_usd": round(self.uso.costo(), 2),
            "veredictos": dict(self.veredictos()),
            "sin_descripcion": len(sin_desc),
            "errores_descripcion": dict(Counter(d.error for d in sin_desc)),
            "alertas": sum(len(c.alertas) for c in self.cruces),
            "sugerencias": sum(1 for c in self.cruces if c.sugerencia),
            "detenida": self.detenida,
            "error_resumen": self.error_resumen,
            "error_sugerencias": self.error_sugerencias,
        }


def preparar(carpeta: Path, plan: Path) -> tuple[list[Archivo], list[Accion]]:
    return inventariar(carpeta), leer_acciones(plan)


async def revisar(
    carpeta: Path,
    plan: Path | None,
    salidas: Path,
    cliente: ClienteModelo,
    programa: str,
    concurrencia: int = 4,
    avisar: Callable[[str], None] | None = None,
    preparado: tuple[list[Archivo], list[Accion]] | None = None,
    *,
    cache: Cache | None = None,
    uso: Uso | None = None,
    tope_usd: float | None = None,
    paso: Callable[[str, int, int], None] | None = None,
) -> Informe:
    """`preparado`: inventario y acciones ya leídos (el script los lee para
    estimar el costo); así no se recorre y se hashea la carpeta dos veces.

    `cache`: por defecto `salidas/.cache`; la web usa una del volumen que
    sobrevive al borrado de los soportes. `tope_usd`: la corrida no gasta más
    de eso (ver `ClienteConTope`). `paso(clave, hechos, total)` informa el
    avance por paso (`PASOS`)."""
    inicio = time.monotonic()
    decir = avisar or (lambda _m: None)
    marcar = paso or (lambda _p, _h, _t: None)
    if preparado is None:
        if plan is None:
            raise ValueError("Falta el plan o el inventario ya preparado.")
        preparado = preparar(carpeta, plan)
    archivos, acciones = preparado
    cache = cache or Cache(salidas / ".cache")
    uso = uso if uso is not None else Uso()
    if tope_usd is not None:
        cliente = ClienteConTope(cliente, uso, tope_usd)
    decir(f"Inventario: {len(archivos)} archivos; plan: {len(acciones)} acciones.")
    marcar("descripcion", 0, len(archivos))

    hechos = [0]

    def progreso_desc(archivo: Archivo, desc: Descripcion) -> None:
        hechos[0] += 1
        estado = "caché" if desc.desde_cache else ("ok" if desc.datos else desc.error)
        decir(f"  [{hechos[0]}/{len(archivos)}] {archivo.id} {archivo.tipo}: {estado}")
        marcar("descripcion", hechos[0], len(archivos))

    por_codigo = {a.codigo: a for a in acciones}
    descripciones = await describir_todos(
        archivos, carpeta, por_codigo, cliente, cache, uso, concurrencia,
        progreso=progreso_desc,
    )  # fmt: skip
    decir(f"Descripciones listas. Costo hasta ahora: {uso.costo():.2f} USD.")
    guardar_indice(cache, programa, descripciones, archivos)

    marcar("cruce", 0, len(acciones))
    cruzadas = [0]

    def progreso_cruce(c: Cruce) -> None:
        estado = c.propuesta.veredicto.value if c.propuesta else f"error: {c.error}"
        decir(f"  Acción {c.accion.codigo}: {estado}")
        cruzadas[0] += 1
        marcar("cruce", cruzadas[0], len(acciones))

    cruces = await cruzar_todas(
        acciones, archivos, descripciones, cliente, cache, uso, concurrencia,
        progreso=progreso_cruce,
    )  # fmt: skip
    marcar("resumen", 0, 2)
    resumen, error_resumen, alertas_resumen = await resumir(
        cruces, archivos, cliente, cache, uso
    )
    marcar("resumen", 1, 2)
    reporte = reporte_md(cruces, archivos, descripciones, programa)
    error_sugerencias = await sugerir(cruces, reporte, cliente, cache, uso)
    marcar("resumen", 2, 2)
    marcar("salidas", 0, 1)
    salidas.mkdir(parents=True, exist_ok=True)
    indice = {a.id: a for a in archivos}
    rutas = {
        "reporte_sin_evidencia": salidas / "reporte_sin_evidencia.md",
        "inventario": salidas / "inventario_soportes.xlsx",
        "cruce": salidas / "cruce_acciones.xlsx",
        "borrador": salidas / "borrador_cierre.docx",
    }

    def escribir() -> None:
        rutas["reporte_sin_evidencia"].write_text(reporte, encoding="utf-8")
        inventario_xlsx(rutas["inventario"], archivos, descripciones)
        cruce_xlsx(rutas["cruce"], cruces)
        borrador_docx(
            rutas["borrador"], programa, cruces, resumen, alertas_resumen, indice
        )

    # openpyxl y python-docx son síncronos: en un hilo.
    await asyncio.to_thread(escribir)
    marcar("salidas", 1, 1)
    return Informe(
        archivos,
        acciones,
        descripciones,
        cruces,
        uso,
        time.monotonic() - inicio,
        rutas,
        alertas_resumen,
        error_resumen,
        error_sugerencias,
        str(getattr(cliente, "detenido", "") or ""),
    )
