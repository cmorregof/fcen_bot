"""Carga datos ficticios para probar la web en local.

Se corre una vez por servicio, con el BOT_SERVICIO de ese servicio, y solo
escribe en la base de ese servicio:

    BOT_SERVICIO=calidad uv run python scripts/datos_web_ficticios.py

Todos los nombres, correos y casos son inventados.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

from app.api.web.auth import _ESQUEMA
from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.db import repo
from app.db.session import connect
from app.schemas.caso import EstadoCaso, ExtraccionCaso, Sentido, TipoSolicitud
from app.schemas.consejo import Instancia, SentidoConsejo

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
        ("secretaria@unal.edu.co", "Sofía Ficticia", "secretaria", None),
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
        (
            "Pedro Prueba Cuatro",
            TipoSolicitud.REINGRESO,
            "reingreso al programa",
            Sentido.APROBAR,
        ),
    ]
    ids: list[int] = []
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
        ids.append(caso_id)
    assert "ing_fisica" in PROGRAMAS
    await _decisiones_consejo(db, ids[1:])


async def _decisiones_consejo(db: object, ids: list[int]) -> None:
    """Un acta ficticia del Consejo de Facultad, del semestre en curso, con la
    decisión confirmada de los casos 2 a 4 (Notificaciones, oficio del
    Consejo y datos SUIT)."""
    import aiosqlite

    assert isinstance(db, aiosqlite.Connection)
    hoy = date.today()
    inicio = date(hoy.year, 1 if hoy.month <= 6 else 7, 1)
    fecha = max(hoy - timedelta(days=7), inicio).isoformat()
    cur = await db.execute(
        "INSERT INTO actas_consejo (direccion, instancia, numero, fecha, texto,"
        " subido_por) VALUES (NULL, ?, '99', ?, 'Acta ficticia.', ?)",
        (Instancia.FACULTAD.value, fecha, "secretaria@unal.edu.co"),
    )
    acta_id = int(cur.lastrowid or 0)
    sentidos = (SentidoConsejo.APROBO, SentidoConsejo.NO_APROBO, SentidoConsejo.APROBO)
    textos = {
        SentidoConsejo.APROBO: "APROBADO",
        SentidoConsejo.NO_APROBO: "NO APROBADO",
    }
    for orden, (caso_id, sentido) in enumerate(zip(ids, sentidos, strict=True), 1):
        await db.execute(
            "INSERT INTO decisiones_consejo (caso_id, acta_id, decision_id,"
            " instancia, sentido, texto_decision, acta_numero, acta_fecha,"
            " fragmento, confirmado_por) VALUES (?, ?, ?, ?, ?, ?, '99', ?, ?, ?)",
            (
                caso_id,
                acta_id,
                orden,
                Instancia.FACULTAD.value,
                sentido.value,
                textos[sentido],
                fecha,
                f"Caso #{caso_id} (ficticio): {textos[sentido]}.",
                "secretaria@unal.edu.co",
            ),
        )
        await db.execute(
            "UPDATE casos SET estado = ? WHERE id = ?",
            (EstadoCaso.DECIDIDO_CONSEJO.value, caso_id),
        )
    await db.commit()


async def _calidad(db: object) -> None:
    import aiosqlite

    from app.servicios.calidad import plan, plantilla, reloj
    from app.servicios.calidad.db import init_calidad

    assert isinstance(db, aiosqlite.Connection)
    await init_calidad(db)
    for nombre in (
        "plantilla_plan_mejoramiento.xlsx",
        "plantilla_plan_mejoramiento_beta.xlsx",
    ):
        lectura = plantilla.leer_plantilla(
            (RAIZ / "docs" / "calidad" / nombre).read_bytes()
        )
        if lectura.errores or lectura.plan is None:
            raise SystemExit("\n".join(lectura.errores))
        await plan.aplicar_importacion(
            db,
            lectura.plan,
            archivo=nombre,
            usuario_id=0,
            creado=reloj.ahora().isoformat(),
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
