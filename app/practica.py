"""Entorno de práctica: datos ficticios y reinicio.

Solo funciona con MEMORIA_PRACTICA=true. En ese modo la configuración manda la
base a <DATA_DIR>/practica/<servicio>/ (nunca la de producción) y el cliente de
Telegram no envía nada. Todos los nombres, documentos (1000000xxx) y casos son
inventados.

`reiniciar` vacía la base del servicio y la vuelve a llenar, así que correrla
dos veces deja el mismo resultado. Los correos autorizados (web_usuarios) se
conservan: quien se autorizó para una capacitación sigue autorizado.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import aiosqlite

from app.api.web.auth import _ESQUEMA as _ESQUEMA_USUARIOS
from app.api.web.auth import ROLES_POR_SERVICIO
from app.core.config import settings
from app.core.programas import DIRECCIONES, PROGRAMAS
from app.db import repo
from app.db.session import connect
from app.schemas.caso import (
    AsignaturaCuadro,
    AsignaturaSolicitada,
    CuadroEquivalencias,
    CursoInscrito,
    DatosSIA,
    ExtraccionCaso,
    FilaCreditos,
    FilaCuadro,
    Jurado,
    ProyectoTesis,
    Sentido,
    TipoSolicitud,
)

RAIZ = Path(__file__).resolve().parents[1]
PLAN_CALIDAD = RAIZ / "docs" / "calidad" / "plantilla_plan_mejoramiento_beta.xlsx"


class NoEsPractica(RuntimeError):
    """Se intentó sembrar o reiniciar fuera del entorno de práctica."""


def exigir_practica() -> None:
    if not settings.memoria_practica:
        raise NoEsPractica(
            "Esto solo corre con MEMORIA_PRACTICA=true: reiniciar borra la base."
        )


# ---------------------------------------------------------------------------
# Casos de actas
# ---------------------------------------------------------------------------


def _sia(
    plan: str, nombre: str, inscritos: int, cursos: list[tuple[str, str, int]]
) -> DatosSIA:
    filas = [
        ("DISCIPLINAR OBLIGATORIA", 40, 17, 23, inscritos, 17),
        ("FUND. OBLIGATORIA", 66, 60, 6, 0, 60),
        ("LIBRE ELECCIÓN", 34, 8, 26, 0, 8),
        ("TOTAL", 170, 85, 85, inscritos, 85),
    ]
    return DatosSIA(
        plan_codigo=plan,
        plan_nombre=nombre,
        periodo="2026-2S",
        papa=4.1,
        porcentaje_avance=50.0,
        cursos_inscritos=[
            CursoInscrito(
                codigo=c, nombre=n, tipologia="DISCIPLINAR OBLIGATORIA", creditos=cr
            )
            for c, n, cr in cursos
        ],
        resumen_creditos=[
            FilaCreditos(
                tipologia=t,
                exigidos=a,
                aprobados=b,
                pendientes=c,
                inscritos=d,
                cursados=e,
            )
            for t, a, b, c, d, e in filas
        ],
    )


def _correo(*lineas: str) -> str:
    return "\n".join(lineas)


def _casos() -> list[tuple[str, str, str, ExtraccionCaso, Sentido]]:
    """(dirección, programa, texto del correo, extracción, sentido)."""
    carga = _correo(
        "Buen día, comité asesor.",
        "Soy estudiante de Ingeniería Física y solicito cancelar la asignatura",
        "Termodinámica Ficticia y cursar este semestre por debajo de la carga mínima.",
        "Tengo un contrato de trabajo en horario de la mañana que no puedo mover.",
        "Gracias por su atención.",
        "Laura Ficticia Prueba",
    )
    extemporanea = _correo(
        "Cordial saludo.",
        "Pido inscribir de forma extemporánea la asignatura Óptica Ficticia.",
        "No pude hacerlo en las fechas del calendario porque estaba en una",
        "práctica de laboratorio fuera de la ciudad.",
        "Mateo Ficticio Prueba",
    )
    traslado = _correo(
        "Buen día.",
        "Solicito traslado a Ingeniería Física y el reconocimiento de las",
        "asignaturas del cuadro adjunto, que cursé en el programa de origen.",
        "Camila Ficticia Ejemplo",
    )
    tesis = _correo(
        "Respetado comité.",
        "Adjunto el proyecto de trabajo final de la maestría para su inscripción.",
        "Mi director es el profesor Director Ficticio Uno.",
        "Daniel Ficticio Muestra",
    )
    jurados = _correo(
        "Cordial saludo.",
        "Con el aval de mi director, propongo los siguientes jurados para mi",
        "Trabajo de Grado: lista adjunta.",
        "Sofía Ficticia Ensayo",
    )
    pae = _correo(
        "Buen día, comité.",
        "Solicito una práctica académica especial (PAE) en el Laboratorio",
        "Ficticio de Cómputo durante el próximo periodo, como complemento de mi",
        "formación en modelado numérico.",
        "Andrés Ficticio Taller",
    )
    extemporanea_mat = _correo(
        "Buenas tardes.",
        "Solicito inscripción extemporánea de Álgebra Lineal Ficticia, porque",
        "mi cita de matrícula coincidió con una incapacidad médica.",
        "Valentina Ficticia Demo",
    )
    cancelacion = _correo(
        "Buen día.",
        "Solicito cancelar la asignatura Inferencia Ficticia por motivos de",
        "salud que tienen soporte médico.",
        "Julián Ficticio Práctica",
    )

    def ext(
        nombre: str,
        doc: str,
        texto: str,
        tipos: list[TipoSolicitud],
        objeto: str,
        cita: str,
        femenino: bool = False,
        **resto: object,
    ) -> ExtraccionCaso:
        return ExtraccionCaso(
            nombre_estudiante=nombre,
            documento=doc,
            tratamiento="La estudiante" if femenino else "El estudiante",
            fecha_solicitud="2026-10-20",
            tipos=tipos,
            objeto_solicitud=objeto,
            cuerpo_desde_linea=1,
            cuerpo_hasta_linea=len(texto.splitlines()),
            cita_textual=cita,
            justificacion_breve="Motivo ficticio para practicar.",
            **resto,  # type: ignore[arg-type]
        )

    fisica = _sia(
        "4030",
        "INGENIERIA FISICA",
        8,
        [("9000201", "Termodinámica Ficticia", 4), ("9000202", "Mecánica Ficticia", 4)],
    )
    cuadro = CuadroEquivalencias(
        figura="equivalencia",
        origen="Programa Ficticio de Origen",
        destino="Ingeniería Física",
        filas=[
            FilaCuadro(
                origen=AsignaturaCuadro(
                    codigo="9000001",
                    nombre="Cálculo Ficticio",
                    tipologia="FUNDAMENTACIÓN OBLIGATORIA",
                    creditos=4,
                    nota="4.2",
                ),
                destino=AsignaturaCuadro(
                    codigo="9000101",
                    nombre="Cálculo Diferencial Ficticio",
                    tipologia="FUNDAMENTACIÓN OBLIGATORIA",
                    creditos=4,
                    nota="4.2",
                ),
            ),
            FilaCuadro(
                origen=AsignaturaCuadro(
                    codigo="9000002", nombre="Física Ficticia", creditos=3, nota="AP"
                ),
                destino=AsignaturaCuadro(
                    codigo="9000102", nombre="Mecánica Ficticia", creditos=3, nota="AP"
                ),
            ),
        ],
    )
    nombres_jurados = [
        ("Jurado Ficticio Uno", "Profesor asociado, Departamento Ficticio"),
        ("Jurado Ficticio Dos", "Profesora titular, Departamento Ficticio"),
        ("Jurado Ficticio Tres", "Universidad Ficticia del Centro"),
        ("Jurado Ficticio Cuatro", "Universidad Ficticia del Norte"),
        ("Jurado Ficticio Cinco", "Profesor asociado, Departamento Ficticio"),
        ("Jurado Ficticio Seis", "Universidad Ficticia del Sur"),
    ]
    return [
        (
            "ciencias_naturales",
            "ing_fisica",
            carga,
            ext(
                "Laura Ficticia Prueba",
                "1000000001",
                carga,
                [TipoSolicitud.CARGA_MINIMA, TipoSolicitud.CANCELACION],
                "cancelación de la asignatura 9000201 Termodinámica Ficticia y "
                "carga mínima",
                "Tengo un contrato de trabajo en horario de la mañana que no puedo mover.",
                femenino=True,
                asignaturas=[
                    AsignaturaSolicitada(
                        codigo="9000201",
                        nombre="Termodinámica Ficticia",
                        creditos=4,
                        accion="cancelar",
                    )
                ],
                sia=fisica,
            ),
            Sentido.PENDIENTE,
        ),
        (
            "ciencias_naturales",
            "ing_fisica",
            extemporanea,
            ext(
                "Mateo Ficticio Prueba",
                "1000000002",
                extemporanea,
                [TipoSolicitud.INSCRIPCION_EXTEMPORANEA],
                "inscripción extemporánea de la asignatura 9000203 Óptica Ficticia",
                "No pude hacerlo en las fechas del calendario porque estaba en una",
                asignaturas=[
                    AsignaturaSolicitada(
                        codigo="9000203", nombre="Óptica Ficticia", creditos=3
                    )
                ],
                sia=fisica,
            ),
            Sentido.APROBAR,
        ),
        (
            "ciencias_naturales",
            "ing_fisica",
            traslado,
            ext(
                "Camila Ficticia Ejemplo",
                "1000000003",
                traslado,
                [TipoSolicitud.TRASLADO],
                "traslado al programa de Ingeniería Física y reconocimiento de "
                "asignaturas",
                "asignaturas del cuadro adjunto, que cursé en el programa de origen.",
                femenino=True,
                equivalencias=[cuadro],
            ),
            Sentido.PENDIENTE,
        ),
        (
            "ciencias_naturales",
            "mcf",
            tesis,
            ext(
                "Daniel Ficticio Muestra",
                "1000000004",
                tesis,
                [TipoSolicitud.PROYECTO_TESIS],
                "inscripción del proyecto de trabajo final de la Maestría en "
                "Ciencias - Física",
                "Mi director es el profesor Director Ficticio Uno.",
                proyecto=ProyectoTesis(
                    titulo="Modelado numérico de un sistema ficticio",
                    director="Director Ficticio Uno, Departamento Ficticio",
                    linea="Física computacional ficticia",
                ),
            ),
            Sentido.PENDIENTE,
        ),
        (
            "matematicas",
            "ciencias_computacion",
            jurados,
            ext(
                "Sofía Ficticia Ensayo",
                "1000000005",
                jurados,
                [TipoSolicitud.DESIGNACION_JURADOS],
                "designación de jurados para el Trabajo de Grado",
                "Con el aval de mi director, propongo los siguientes jurados para mi",
                femenino=True,
                jurados=[Jurado(nombre=n, vinculacion=v) for n, v in nombres_jurados],
            ),
            Sentido.PENDIENTE,
        ),
        (
            "matematicas",
            "ciencias_computacion",
            pae,
            ext(
                "Andrés Ficticio Taller",
                "1000000006",
                pae,
                [TipoSolicitud.PAE],
                "práctica académica especial (PAE) en el Laboratorio Ficticio de "
                "Cómputo",
                "Solicito una práctica académica especial (PAE) en el Laboratorio",
            ),
            Sentido.NO_APROBAR,
        ),
        (
            "matematicas",
            "matematicas",
            extemporanea_mat,
            ext(
                "Valentina Ficticia Demo",
                "1000000007",
                extemporanea_mat,
                [TipoSolicitud.INSCRIPCION_EXTEMPORANEA],
                "inscripción extemporánea de la asignatura 9000301 Álgebra Lineal "
                "Ficticia",
                "mi cita de matrícula coincidió con una incapacidad médica.",
                femenino=True,
                asignaturas=[
                    AsignaturaSolicitada(
                        codigo="9000301", nombre="Álgebra Lineal Ficticia", creditos=4
                    )
                ],
            ),
            Sentido.PENDIENTE,
        ),
        (
            "matematicas",
            "estadistica",
            cancelacion,
            ext(
                "Julián Ficticio Práctica",
                "1000000008",
                cancelacion,
                [TipoSolicitud.CANCELACION],
                "cancelación de la asignatura 9000302 Inferencia Ficticia",
                "Solicito cancelar la asignatura Inferencia Ficticia por motivos de",
                asignaturas=[
                    AsignaturaSolicitada(
                        codigo="9000302",
                        nombre="Inferencia Ficticia",
                        creditos=3,
                        accion="cancelar",
                    )
                ],
            ),
            Sentido.PENDIENTE,
        ),
    ]


async def _sembrar_actas(db: aiosqlite.Connection) -> int:
    casos = _casos()
    for direccion, programa, texto, extraccion, sentido in casos:
        assert direccion in DIRECCIONES and programa in PROGRAMAS
        assert PROGRAMAS[programa].direccion == direccion
        caso_id = await repo.crear_caso(db, chat_id=0, user_id=0, direccion=direccion)
        await repo.agregar_texto(db, caso_id, texto)
        await repo.guardar_extraccion(db, caso_id, extraccion, programa)
        if sentido is not Sentido.PENDIENTE:
            await repo.set_sentido(db, caso_id, sentido)
    return len(casos)


# ---------------------------------------------------------------------------
# Calidad y admisión
# ---------------------------------------------------------------------------


async def _sembrar_calidad(db: aiosqlite.Connection) -> int:
    from app.servicios.calidad import plan, plantilla, reloj
    from app.servicios.calidad.db import init_calidad

    await init_calidad(db)
    lectura = plantilla.leer_plantilla(PLAN_CALIDAD.read_bytes())
    if lectura.errores or lectura.plan is None:
        raise RuntimeError("; ".join(lectura.errores))
    await plan.aplicar_importacion(
        db,
        lectura.plan,
        archivo=PLAN_CALIDAD.name,
        usuario_id=0,
        creado=reloj.ahora().isoformat(),
    )
    return len(lectura.plan.acciones)


async def _sembrar_admision(db: aiosqlite.Connection) -> int:
    from app.servicios.admision import almacen

    await almacen.asegurar_tablas(db)
    metricas = (
        ("consentimientos", 12),
        ("preguntas", 30),
        ("documentos_revisados", 18),
        ("documentos_con_errores", 5),
    )
    for clave, n in metricas:
        await almacen.contar(db, clave, n)
    # La lista de chequeo sale de config/admision/chequeo.yaml: no es un dato.
    return len(metricas)


_SEMBRAR = {
    "actas": _sembrar_actas,
    "calidad": _sembrar_calidad,
    "admision": _sembrar_admision,
}


# ---------------------------------------------------------------------------
# Reinicio
# ---------------------------------------------------------------------------


async def _vaciar(db: aiosqlite.Connection) -> None:
    """Borra el contenido de todas las tablas menos los correos autorizados."""
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
        " AND name NOT LIKE 'sqlite_%' AND name != 'web_usuarios'"
    )
    tablas = [str(f[0]) for f in await cur.fetchall()]
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        for tabla in tablas:
            await db.execute(f'DELETE FROM "{tabla}"')  # noqa: S608
        await db.execute("DELETE FROM sqlite_sequence")
        await db.commit()
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


def _limpiar_carpeta(carpeta: Path) -> None:
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)


async def reiniciar() -> dict[str, object]:
    """Deja la base del servicio con los datos ficticios de siempre."""
    exigir_practica()
    db = await connect()
    try:
        await db.execute(_ESQUEMA_USUARIOS)
        await _vaciar(db)
        _limpiar_carpeta(settings.media_dir)
        _limpiar_carpeta(settings.output_dir)
        n = await _SEMBRAR[settings.bot_servicio](db)
    finally:
        await db.close()
    return {"ok": True, "servicio": settings.bot_servicio, "registros": n}


# ---------------------------------------------------------------------------
# Asistentes de una capacitación
# ---------------------------------------------------------------------------


async def autorizar_asistentes(archivo: Path) -> int:
    """Autoriza los correos de un CSV (correo,nombre,rol,direccion) en ESTE servicio.

    Las filas cuyo rol no existe en el servicio se ignoran, para poder usar un
    mismo archivo con los tres.
    """
    exigir_practica()
    roles = ROLES_POR_SERVICIO[settings.bot_servicio]
    n = 0
    db = await connect()
    try:
        await db.execute(_ESQUEMA_USUARIOS)
        with archivo.open(encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                correo = (fila.get("correo") or "").strip().lower()
                rol = (fila.get("rol") or "").strip()
                direccion = (fila.get("direccion") or "").strip() or None
                if not correo.endswith("@unal.edu.co") or rol not in roles:
                    continue
                if rol in ("administrativa", "comite"):
                    if direccion not in DIRECCIONES:
                        continue
                else:
                    direccion = None
                await db.execute(
                    "INSERT INTO web_usuarios (correo, nombre, rol, direccion, activo)"
                    " VALUES (?, ?, ?, ?, 1) ON CONFLICT(correo) DO UPDATE SET"
                    " nombre=excluded.nombre, rol=excluded.rol,"
                    " direccion=excluded.direccion, activo=1",
                    (
                        correo,
                        (fila.get("nombre") or "").strip() or None,
                        rol,
                        direccion,
                    ),
                )
                n += 1
        await db.commit()
    finally:
        await db.close()
    return n
