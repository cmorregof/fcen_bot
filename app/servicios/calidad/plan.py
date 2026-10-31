"""Dominio del plan de mejoramiento: estados, importación e historial.

El plan se lee con `plantilla.leer_plantilla` (plantilla institucional de cinco
hojas). Aquí se guarda: una foto del último plan por programa, una identidad
estable por acción (programa + código), el historial de cortes semestrales y
los soportes que se registran desde el bot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.core.conexion import Conexion
from app.servicios.calidad.config import calidad_settings
from app.servicios.calidad.plantilla import Accion, Corte, Objetivo, Plan, plegar

__all__ = [
    "Estado",
    "PlanGuardado",
    "ResumenImportacion",
    "Soporte",
    "aplicar_importacion",
    "buscar_programa",
    "cargar_plan",
    "calcular_estado",
    "listar_planes",
    "listar_programas",
    "plegar",
    "proximo_corte",
    "proxima_a_vencer",
    "registrar_soporte",
    "resumir",
]


AUSENTE = "no viene en el último archivo"


class Estado(StrEnum):
    NO_FUNCIONO = "no funcionó"
    VENCIDA = "vencida"
    EN_CURSO = "en curso"
    POR_INICIAR = "por iniciar"
    CUMPLIDA = "cumplida"


def calcular_estado(accion: Accion, hoy: date) -> Estado:
    """Regla fija, en este orden:
    1. «NO FUNCIONÓ» escrito a mano en el plan o el cronograma.
    2. Cumplida si el % de avance es 100.
    3. Vencida si la fecha de fin ya pasó y el avance es menor a 100 %.
    4. Por iniciar si la fecha de inicio aún no llega.
    5. En curso en cualquier otro caso."""
    if accion.no_funciono:
        return Estado.NO_FUNCIONO
    if accion.avance is not None and accion.avance >= 100:
        return Estado.CUMPLIDA
    if accion.fecha_fin is not None and accion.fecha_fin < hoy:
        return Estado.VENCIDA
    if accion.fecha_inicio is not None and accion.fecha_inicio > hoy:
        return Estado.POR_INICIAR
    return Estado.EN_CURSO


def proxima_a_vencer(accion: Accion, hoy: date, dias: int | None = None) -> bool:
    plazo = calidad_settings.dias_proxima if dias is None else dias
    return (
        calcular_estado(accion, hoy) in (Estado.EN_CURSO, Estado.POR_INICIAR)
        and accion.fecha_fin is not None
        and 0 <= (accion.fecha_fin - hoy).days <= plazo
    )


def _sumar_meses(f: date, meses: int) -> date:
    total = f.month - 1 + meses
    anio, mes = f.year + total // 12, total % 12 + 1
    return date(anio, mes, min(f.day, 28))


def proximo_corte(plan: Plan, hoy: date) -> tuple[date, bool] | None:
    """El próximo corte con fecha en el plan; si todos pasaron, el último más
    seis meses (los cortes son semestrales). El booleano dice si es estimado."""
    fechas = sorted({k.fecha for a in plan.acciones for k in a.cortes if k.fecha})
    futuras = [f for f in fechas if f > hoy]
    if futuras:
        return futuras[0], False
    if not fechas:
        return None
    siguiente = _sumar_meses(fechas[-1], 6)
    while siguiente <= hoy:
        siguiente = _sumar_meses(siguiente, 6)
    return siguiente, True


# ---------------------------------------------------------------------------
# Lo guardado
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Soporte:
    id: int
    accion_id: int
    tipo: str
    valor: str
    referencia: str | None
    registrado_por: int
    registrado_nombre: str | None
    creado: str


@dataclass(frozen=True)
class CorteGuardado:
    id: int
    rotulo: str
    fecha: date | None
    descripcion: str
    evidencias: str
    importacion_id: int


@dataclass
class PlanGuardado:
    plan: Plan
    importacion_id: int
    archivo: str
    ids: dict[str, int] = field(default_factory=dict)
    cortes: dict[str, list[CorteGuardado]] = field(default_factory=dict)
    soportes: dict[str, list[Soporte]] = field(default_factory=dict)

    @property
    def programa(self) -> str:
        return self.plan.programa

    def accion(self, codigo: str) -> Accion | None:
        codigo = codigo.strip().rstrip(".")
        return next((a for a in self.plan.acciones if a.codigo == codigo), None)


async def listar_programas(db: Conexion) -> list[str]:
    cur = await db.execute("SELECT programa FROM cal_planes ORDER BY programa")
    return [str(r[0]) for r in await cur.fetchall()]


async def buscar_programa(db: Conexion, texto: str) -> str | None:
    """Coincidencia exacta o, si no, por subcadena única (sin tildes)."""
    clave = plegar(texto)
    if not clave:
        return None
    programas = await listar_programas(db)
    for p in programas:
        if plegar(p) == clave:
            return p
    parecidos = [p for p in programas if clave in plegar(p)]
    return parecidos[0] if len(parecidos) == 1 else None


async def cargar_plan(db: Conexion, programa: str) -> PlanGuardado | None:
    clave = plegar(programa)
    cur = await db.execute(
        "SELECT p.datos_json, p.importacion_id, i.archivo FROM cal_planes p "
        "LEFT JOIN cal_importaciones i ON i.id = p.importacion_id "
        "WHERE p.programa_clave = ?",
        (clave,),
    )
    fila = await cur.fetchone()
    if fila is None:
        return None
    guardado = PlanGuardado(
        plan=Plan.model_validate_json(fila["datos_json"]),
        importacion_id=int(fila["importacion_id"]),
        archivo=str(fila["archivo"] or ""),
    )
    cur = await db.execute(
        "SELECT id, codigo FROM cal_acciones WHERE programa_clave = ?", (clave,)
    )
    por_id: dict[int, str] = {}
    for r in await cur.fetchall():
        guardado.ids[str(r["codigo"])] = int(r["id"])
        por_id[int(r["id"])] = str(r["codigo"])
    if not por_id:
        return guardado
    marcas = ",".join("?" * len(por_id))
    cur = await db.execute(
        "SELECT id, accion_id, rotulo, fecha, descripcion, evidencias, importacion_id "
        f"FROM cal_cortes WHERE accion_id IN ({marcas}) ORDER BY fecha, id",
        tuple(por_id),
    )
    for r in await cur.fetchall():
        guardado.cortes.setdefault(por_id[r["accion_id"]], []).append(
            CorteGuardado(
                id=r["id"],
                rotulo=r["rotulo"],
                fecha=date.fromisoformat(r["fecha"]) if r["fecha"] else None,
                descripcion=r["descripcion"],
                evidencias=r["evidencias"],
                importacion_id=r["importacion_id"],
            )
        )
    cur = await db.execute(
        "SELECT id, accion_id, tipo, valor, referencia, registrado_por, "
        f"registrado_nombre, creado FROM cal_soportes WHERE accion_id IN ({marcas}) "
        "ORDER BY id",
        tuple(por_id),
    )
    for r in await cur.fetchall():
        s = Soporte(*tuple(r))
        guardado.soportes.setdefault(por_id[s.accion_id], []).append(s)
    return guardado


async def listar_planes(db: Conexion) -> list[PlanGuardado]:
    planes = [await cargar_plan(db, p) for p in await listar_programas(db)]
    return [p for p in planes if p is not None]


# ---------------------------------------------------------------------------
# Importación
# ---------------------------------------------------------------------------

_COMPARABLES = (
    "descripcion", "indicador", "responsables", "fecha_inicio", "fecha_fin",
    "avance", "evidencias", "marcas",
)  # fmt: skip


def _foto(a: Accion) -> dict[str, object]:
    datos = a.model_dump(mode="json", include=set(_COMPARABLES))
    datos["tareas"] = len(a.tareas)
    return datos


@dataclass
class ResumenImportacion:
    programa: str
    plan_nuevo: bool
    objetivos: int
    acciones: int
    tareas: int
    avance: float | None
    cronogramas: list[int]
    alertas: list[str]
    nuevas: list[str] = field(default_factory=list)
    actualizadas: list[tuple[str, list[str]]] = field(default_factory=list)
    sin_cambios: int = 0
    ausentes: list[str] = field(default_factory=list)
    cortes_nuevos: int = 0
    cortes_cambiados: int = 0


def _clave_corte(k: Corte) -> str:
    return k.fecha.isoformat() if k.fecha else plegar(k.rotulo)


async def resumir(db: Conexion, plan: Plan) -> ResumenImportacion:
    """Qué pasaría al guardar este plan, sin guardar nada."""
    previo = await cargar_plan(db, plan.programa)
    resumen = ResumenImportacion(
        programa=plan.programa,
        plan_nuevo=previo is None,
        objetivos=len(plan.objetivos),
        acciones=len(plan.acciones),
        tareas=len(plan.tareas),
        avance=plan.avance_promedio(),
        cronogramas=plan.cronogramas,
        alertas=plan.alertas,
    )
    antes = {a.codigo: a for a in previo.plan.acciones} if previo else {}
    cortes_previos = previo.cortes if previo else {}
    for a in plan.acciones:
        vieja = antes.get(a.codigo)
        if vieja is None:
            resumen.nuevas.append(a.codigo)
        else:
            f0, f1 = _foto(vieja), _foto(a)
            cambios = [c for c in f1 if f0.get(c) != f1[c]]
            if cambios:
                resumen.actualizadas.append((a.codigo, cambios))
            else:
                resumen.sin_cambios += 1
        guardados = {
            (k.fecha.isoformat() if k.fecha else plegar(k.rotulo)): k
            for k in cortes_previos.get(a.codigo, [])
        }
        for k in a.cortes:
            previo_k = guardados.get(_clave_corte(k))
            if previo_k is None:
                resumen.cortes_nuevos += 1
            elif (previo_k.descripcion, previo_k.evidencias) != (
                k.descripcion,
                k.evidencias,
            ):
                resumen.cortes_cambiados += 1
    codigos = {a.codigo for a in plan.acciones}
    resumen.ausentes = [c for c in antes if c not in codigos]
    return resumen


async def aplicar_importacion(
    db: Conexion,
    plan: Plan,
    *,
    archivo: str,
    usuario_id: int,
    creado: str,
) -> ResumenImportacion:
    """Guarda el plan. Reimportar actualiza por (programa, código de acción),
    nunca duplica, conserva los cortes anteriores y deja en cal_cambios qué
    cambió. Las acciones que ya no vienen se conservan y se reportan."""
    resumen = await resumir(db, plan)
    clave = plegar(plan.programa)
    cur = await db.execute(
        "INSERT INTO cal_importaciones (archivo, usuario_id, creadas, actualizadas, "
        "sin_cambios, creado) VALUES (?, ?, ?, ?, ?, ?)",
        (
            archivo,
            usuario_id,
            len(resumen.nuevas),
            len(resumen.actualizadas),
            resumen.sin_cambios,
            creado,
        ),
    )
    imp = int(cur.lastrowid or 0)
    previo = await cargar_plan(db, plan.programa)
    antes = {a.codigo: a for a in previo.plan.acciones} if previo else {}
    cambios = dict(resumen.actualizadas)

    # Una acción que ya no viene se conserva en la foto para no perder su historial.
    conservadas = [a for c, a in antes.items() if c in resumen.ausentes]
    if conservadas:
        plan = plan.model_copy(deep=True)
        for a in conservadas:
            a = a.model_copy(deep=True)
            if AUSENTE not in a.marcas:
                a.marcas.append(AUSENTE)
            destino = next(
                (o for o in plan.objetivos if o.codigo == a.objetivo_codigo), None
            )
            if destino is None:
                destino = Objetivo(codigo=a.objetivo_codigo, texto="")
                plan.objetivos.append(destino)
            destino.acciones.append(a)

    await db.execute(
        "INSERT INTO cal_planes (programa, programa_clave, datos_json, importacion_id, "
        "actualizado) VALUES (?, ?, ?, ?, ?) ON CONFLICT(programa_clave) DO UPDATE SET "
        "programa=excluded.programa, datos_json=excluded.datos_json, "
        "importacion_id=excluded.importacion_id, actualizado=excluded.actualizado",
        (plan.programa, clave, plan.model_dump_json(), imp, creado),
    )
    for a in plan.acciones:
        cur = await db.execute(
            "INSERT INTO cal_acciones (programa_clave, codigo, importacion_id) "
            "VALUES (?, ?, ?) ON CONFLICT(programa_clave, codigo) DO UPDATE SET "
            "importacion_id=excluded.importacion_id RETURNING id",
            (clave, a.codigo, imp),
        )
        fila = await cur.fetchone()
        accion_id = int(fila[0]) if fila else 0
        if a.codigo in resumen.nuevas:
            await _cambio(db, accion_id, imp, "creada", {})
        elif a.codigo in resumen.ausentes and AUSENTE not in antes[a.codigo].marcas:
            await _cambio(db, accion_id, imp, "ausente", {"archivo": archivo})
        elif a.codigo in cambios:
            f0, f1 = _foto(antes[a.codigo]), _foto(a)
            await _cambio(
                db, accion_id, imp, "actualizada",
                {c: [f0.get(c), f1[c]] for c in cambios[a.codigo]},
            )  # fmt: skip
        for k in a.cortes:
            await _guardar_corte(db, accion_id, imp, k)
    await db.commit()
    return resumen


async def _cambio(
    db: Conexion,
    accion_id: int,
    imp: int,
    tipo: str,
    datos: dict[str, object],
) -> None:
    await db.execute(
        "INSERT INTO cal_cambios (accion_id, importacion_id, tipo, cambios_json) "
        "VALUES (?, ?, ?, ?)",
        (accion_id, imp, tipo, json.dumps(datos, ensure_ascii=False, default=str)),
    )


async def _guardar_corte(db: Conexion, accion_id: int, imp: int, k: Corte) -> None:
    clave = _clave_corte(k)
    cur = await db.execute(
        "SELECT id, descripcion, evidencias FROM cal_cortes "
        "WHERE accion_id = ? AND clave = ?",
        (accion_id, clave),
    )
    previo = await cur.fetchone()
    if previo is None:
        await db.execute(
            "INSERT INTO cal_cortes (accion_id, clave, rotulo, fecha, descripcion, "
            "evidencias, importacion_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                accion_id,
                clave,
                k.rotulo,
                k.fecha.isoformat() if k.fecha else None,
                k.descripcion,
                k.evidencias,
                imp,
            ),
        )
        return
    if (previo["descripcion"], previo["evidencias"]) == (k.descripcion, k.evidencias):
        return
    await _cambio(
        db,
        accion_id,
        imp,
        "corte_cambiado",
        {
            "corte": k.rotulo,
            "descripcion": [previo["descripcion"], k.descripcion],
            "evidencias": [previo["evidencias"], k.evidencias],
        },
    )
    await db.execute(
        "UPDATE cal_cortes SET descripcion = ?, evidencias = ?, importacion_id = ? "
        "WHERE id = ?",
        (k.descripcion, k.evidencias, imp, previo["id"]),
    )


async def registrar_soporte(
    db: Conexion,
    accion_id: int,
    *,
    tipo: str,
    valor: str,
    referencia: str | None,
    usuario_id: int,
    usuario_nombre: str | None,
    creado: str,
) -> None:
    """Un soporte registrado desde el bot queda pendiente de revisión: no cambia
    el % de avance, que solo viene del plan."""
    await db.execute(
        "INSERT INTO cal_soportes (accion_id, tipo, valor, referencia, "
        "registrado_por, registrado_nombre, creado) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (accion_id, tipo, valor, referencia, usuario_id, usuario_nombre, creado),
    )
    await db.commit()
