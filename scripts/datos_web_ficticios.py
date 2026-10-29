"""Carga datos ficticios para probar la web en local.

Se corre una vez por servicio, con el BOT_SERVICIO de ese servicio, y solo
escribe en la base de ese servicio:

    BOT_SERVICIO=calidad uv run python scripts/datos_web_ficticios.py

Todos los nombres, correos y casos son inventados.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.api.web.auth import _ESQUEMA
from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.db import repo
from app.db.session import connect
from app.schemas.caso import ExtraccionCaso, Sentido, TipoSolicitud

RAIZ = Path(__file__).resolve().parents[1]

# (correo, nombre, rol, área curricular)
USUARIOS = {
    "actas": [
        ("admin@unal.edu.co", "Admin Ficticio", "admin", None),
        (
            "administrativa@unal.edu.co",
            "Marta Ficticia",
            "administrativa",
            "ciencias_naturales",
        ),
        ("comite@unal.edu.co", "Prof. Ficticio", "comite", "ciencias_naturales"),
        ("decana@unal.edu.co", "Decana Ficticia", "decanatura", None),
    ],
    "calidad": [
        ("admin@unal.edu.co", "Admin Ficticio", "admin", None),
        ("calidad@unal.edu.co", "Lucía Ficticia", "calidad", None),
        ("decana@unal.edu.co", "Decana Ficticia", "decanatura", None),
    ],
    "admision": [
        ("admin@unal.edu.co", "Admin Ficticio", "admin", None),
        ("admision@unal.edu.co", "María Ficticia", "admision", None),
        ("decana@unal.edu.co", "Decana Ficticia", "decanatura", None),
    ],
}


async def _actas(db: object) -> None:
    import aiosqlite

    assert isinstance(db, aiosqlite.Connection)
    cur = await db.execute("SELECT COUNT(*) FROM casos")
    fila = await cur.fetchone()
    if fila and fila[0]:
        return
    casos = [
        (
            "Ana Prueba Uno",
            TipoSolicitud.CANCELACION,
            "cancelación de la asignatura Cálculo Ficticio",
            Sentido.PENDIENTE,
        ),
        (
            "Luis Prueba Dos",
            TipoSolicitud.INSCRIPCION_EXTEMPORANEA,
            "inscripción extemporánea de Física Ficticia",
            Sentido.APROBAR,
        ),
        (
            "Sara Prueba Tres",
            TipoSolicitud.CARGA_MINIMA,
            "cursar por debajo de la carga mínima",
            Sentido.NO_APROBAR,
        ),
    ]
    for nombre, tipo, objeto, sentido in casos:
        caso_id = await repo.crear_caso(
            db, chat_id=0, user_id=0, direccion="ciencias_naturales"
        )
        await repo.agregar_texto(
            db, caso_id, f"Correo ficticio de {nombre}: solicito {objeto}."
        )
        ext = ExtraccionCaso(
            nombre_estudiante=nombre,
            documento="1000000000",
            tipos=[tipo],
            objeto_solicitud=objeto,
            justificacion_breve="Motivo ficticio para pruebas.",
        )
        await repo.guardar_extraccion(db, caso_id, ext, "ing_fisica")
        await repo.set_sentido(db, caso_id, sentido)
    assert "ing_fisica" in PROGRAMAS


async def _calidad(db: object) -> None:
    import aiosqlite

    from app.servicios.calidad import operaciones
    from app.servicios.calidad.db import init_calidad

    assert isinstance(db, aiosqlite.Connection)
    await init_calidad(db)
    contenido = (
        RAIZ / "docs" / "calidad" / "plantilla_plan_mejoramiento.xlsx"
    ).read_bytes()
    vista = await operaciones.previsualizar(db, contenido)
    if vista.errores:
        raise SystemExit("\n".join(vista.errores))
    await operaciones.guardar_plan(
        db, vista.filas, archivo="plantilla ficticia", usuario_id=0
    )


async def _admision(db: object) -> None:
    import aiosqlite

    from app.servicios.admision import almacen

    assert isinstance(db, aiosqlite.Connection)
    await almacen.asegurar_tablas(db)
    for clave, n in (
        ("consentimientos", 12),
        ("preguntas", 30),
        ("documentos_revisados", 18),
        ("documentos_con_errores", 5),
    ):
        await almacen.contar(db, clave, n)


async def main() -> None:
    servicio = settings.bot_servicio
    db = await connect()
    try:
        await db.execute(_ESQUEMA)
        for correo, nombre, rol, direccion in USUARIOS[servicio]:
            await db.execute(
                "INSERT OR REPLACE INTO web_usuarios (correo, nombre, rol, direccion)"
                " VALUES (?, ?, ?, ?)",
                (correo, nombre, rol, direccion),
            )
        await db.commit()
        await {"actas": _actas, "calidad": _calidad, "admision": _admision}[servicio](
            db
        )
    finally:
        await db.close()
    print(f"Datos ficticios cargados en {settings.db_path} ({servicio}).")


if __name__ == "__main__":
    asyncio.run(main())
