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
from app.core.conexion import Conexion
from app.core.config import settings
from app.core.programas import PROGRAMAS
from app.db import repo
from app.db.session import connect
from app.schemas.caso import EstadoCaso, ExtraccionCaso, Sentido, TipoSolicitud
from app.schemas.consejo import ActaLeida, DecisionLeida, Instancia, SentidoConsejo
from app.services import consejo, flujo

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
    "oportunidades": [
        ("admin@unal.edu.co", "Admin Ficticio", "admin", None),
        ("oportunidades@unal.edu.co", "Laura Ficticia", "oportunidades", None),
        ("decana@unal.edu.co", "Decana Ficticia", "decanatura", None),
    ],
}


# (nombre, documento, trámite, objeto, recomendación del comité, hasta dónde
# llega en la línea). Cubre el recorrido completo: prerrevisión (una
# improcedente), comité, Consejo (con una decisión por confirmar) y Secretaría.
_CASOS = [
    (
        "Ana Prueba Uno",
        "1000000001",
        TipoSolicitud.CANCELACION,
        "cancelación de la asignatura Cálculo Ficticio",
        Sentido.PENDIENTE,
        "comite",
    ),
    (
        "Luis Prueba Dos",
        "1000000002",
        TipoSolicitud.INSCRIPCION_EXTEMPORANEA,
        "inscripción extemporánea de Física Ficticia",
        Sentido.APROBAR,
        "decidida",
    ),
    (
        "Sara Prueba Tres",
        "1000000003",
        TipoSolicitud.CARGA_MINIMA,
        "cursar por debajo de la carga mínima",
        Sentido.NO_APROBAR,
        "decidida",
    ),
    (
        "Pedro Prueba Cuatro",
        "1000000004",
        TipoSolicitud.REINGRESO,
        "reingreso al programa",
        Sentido.APROBAR,
        "decidida",
    ),
    (
        "Camila Prueba Cinco",
        "1000000005",
        TipoSolicitud.CANCELACION,
        "cancelación de la asignatura Química Ficticia",
        Sentido.APROBAR,
        "consejo",
    ),
    (
        "Diego Prueba Seis",
        "1000000006",
        TipoSolicitud.INSCRIPCION_EXTEMPORANEA,
        "inscripción extemporánea de Biología Ficticia",
        Sentido.PENDIENTE,
        "comite",
    ),
    (
        "Elena Prueba Siete",
        "1000000007",
        TipoSolicitud.CARGA_MINIMA,
        "cursar por debajo de la carga mínima",
        Sentido.PENDIENTE,
        "improcedente",
    ),
]


_ADMINISTRATIVA = "Marta Ficticia"


async def _fechar(db: Conexion, caso_id: int, accion: flujo.Accion, dia: str) -> None:
    """Corre a una fecha pasada el último evento de esa acción (los datos
    ficticios se cargan todos el mismo día)."""
    await db.execute(
        "UPDATE caso_eventos SET fecha = ? WHERE id = (SELECT MAX(id) FROM"
        " caso_eventos WHERE caso_id = ? AND accion = ?)",
        (f"{dia} 15:00:00", caso_id, accion.value),
    )
    if accion == flujo.Accion.RECOMENDAR:
        await db.execute(
            "UPDATE casos SET recomendado = ? WHERE id = ?",
            (f"{dia} 15:00:00", caso_id),
        )
    await db.commit()


async def _actas(db: Conexion) -> None:
    cur = await db.execute("SELECT COUNT(*) FROM casos")
    fila = await cur.fetchone()
    if fila and fila[0]:
        return
    hoy = date.today()
    inicio = date(hoy.year, 1 if hoy.month <= 6 else 7, 1)

    def dia(atras: int) -> str:
        return max(hoy - timedelta(days=atras), inicio).isoformat()

    decididos: list[int] = []
    en_consejo: list[int] = []
    for nombre, documento, tipo, objeto, sentido, hasta in _CASOS:
        caso_id = await repo.crear_caso(
            db,
            chat_id=0,
            user_id=0,
            direccion="ciencias_naturales",
            canal="web",
            persona=_ADMINISTRATIVA,
        )
        await repo.agregar_texto(
            db, caso_id, f"Correo ficticio de {nombre}: solicito {objeto}."
        )
        await db.execute(
            "UPDATE casos SET creado = ? WHERE id = ?", (f"{dia(24)} 14:00:00", caso_id)
        )
        await _fechar(db, caso_id, flujo.Accion.REGISTRAR, dia(24))
        ext = ExtraccionCaso(
            nombre_estudiante=nombre,
            documento=documento,
            fecha_solicitud=dia(25),
            tipos=[tipo],
            objeto_solicitud=objeto,
            justificacion_breve="Motivo ficticio para pruebas.",
        )
        await repo.guardar_extraccion(db, caso_id, ext, "ing_fisica")
        await flujo.lectura_lista(db, caso_id)
        await _fechar(db, caso_id, flujo.Accion.LECTURA_LISTA, dia(24))
        if sentido is not Sentido.PENDIENTE:
            await flujo.recomendar(
                db,
                caso_id,
                sentido,
                rol=flujo.ADMINISTRATIVA,
                persona=_ADMINISTRATIVA,
                canal="web",
            )
            await _fechar(db, caso_id, flujo.Accion.RECOMENDAR, dia(18))
        if hasta == "improcedente":
            await flujo.prerrevisar(
                db,
                caso_id,
                flujo.Prerrevision.IMPROCEDENTE,
                rol=flujo.ADMINISTRATIVA,
                persona=_ADMINISTRATIVA,
                canal="web",
                nota="Ejemplo ficticio de prerrevisión improcedente.",
            )
        if hasta in ("consejo", "decidida"):
            await flujo.enviar_consejo(
                db,
                [caso_id],
                rol=flujo.ADMINISTRATIVA,
                persona=_ADMINISTRATIVA,
                canal="web",
            )
            await _fechar(db, caso_id, flujo.Accion.ENVIAR_CONSEJO, dia(15))
            (decididos if hasta == "decidida" else en_consejo).append(caso_id)
    assert "ing_fisica" in PROGRAMAS
    await _decisiones_consejo(db, decididos, dia(7))
    await _acta_por_confirmar(db, en_consejo, dia(1))


async def _decisiones_consejo(db: Conexion, ids: list[int], fecha: str) -> None:
    """Un acta ficticia del Consejo de Facultad, del semestre en curso, con la
    decisión confirmada de tres casos (Notificaciones, oficio del Consejo y
    datos SUIT)."""
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
        # La línea única registra la decisión con la fecha de la sesión.
        await flujo.transicionar(
            db,
            caso_id,
            flujo.Accion.DECIDIR,
            rol=flujo.ADMIN,
            persona="Admin Ficticio",
            canal="web",
            fecha=fecha,
            detalle=f"Consejo de Facultad: {textos[sentido]} (acta 99)",
            commit=False,
        )
    await db.commit()


async def _acta_por_confirmar(db: Conexion, ids: list[int], fecha: str) -> None:
    """Un acta ficticia ya leída (sin modelo) con la decisión de los casos que
    están en el Consejo, pendiente de que una persona la confirme en
    /actas/consejo."""
    filas = []
    for caso_id in ids:
        caso = await repo.get_caso(db, caso_id)
        assert caso is not None and caso.extraccion is not None
        filas.append(
            (
                caso,
                f"Caso #{caso_id}. {caso.extraccion.nombre_estudiante}, documento "
                f"{caso.extraccion.documento}: SE APRUEBA la solicitud.",
            )
        )
    texto = "ACTA 100 (FICTICIA). Consejo de Facultad.\n" + "\n".join(
        f for _, f in filas
    )
    await consejo.registrar_acta(
        db,
        leida=ActaLeida(
            numero_acta="100",
            fecha_acta=fecha,
            instancia_texto="Consejo de Facultad",
            decisiones=[
                DecisionLeida(
                    nombre_estudiante=c.extraccion.nombre_estudiante
                    if c.extraccion
                    else None,
                    documento=c.extraccion.documento if c.extraccion else None,
                    numero_caso=str(c.id),
                    texto_decision="SE APRUEBA",
                    fragmento=f,
                )
                for c, f in filas
            ],
        ),
        texto=texto,
        direccion=None,
        instancia=Instancia.FACULTAD,
        archivo_nombre="acta_100_ficticia.pdf",
        subido_por="admin@unal.edu.co",
    )


async def _calidad(db: Conexion) -> None:
    from app.servicios.calidad import plan, plantilla, reloj
    from app.servicios.calidad.db import init_calidad

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


async def _admision(db: Conexion) -> None:
    from app.servicios.admision import almacen

    await almacen.asegurar_tablas(db)
    for clave, n in (
        ("consentimientos", 12),
        ("preguntas", 30),
        ("documentos_revisados", 18),
        ("documentos_con_errores", 5),
    ):
        await almacen.contar(db, clave, n)


async def _oportunidades(db: Conexion) -> None:
    from app.services.indicadores import hoy_local
    from app.servicios.oportunidades import practica
    from app.servicios.oportunidades.db import init_oportunidades

    await init_oportunidades(db)
    cur = await db.execute("SELECT COUNT(*) FROM opo_ofertas")
    fila = await cur.fetchone()
    if not (fila and fila[0]):
        await practica.sembrar(db, hoy_local())


async def main() -> None:
    servicio = settings.bot_servicio
    db = await connect()
    try:
        await db.execute(_ESQUEMA)
        for correo, nombre, rol, direccion in USUARIOS[servicio]:
            await db.execute(
                "INSERT INTO web_usuarios (correo, nombre, rol, direccion)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(correo) DO UPDATE SET"
                " nombre = excluded.nombre, rol = excluded.rol,"
                " direccion = excluded.direccion",
                (correo, nombre, rol, direccion),
            )
        await db.commit()
        cargar = {
            "actas": _actas,
            "calidad": _calidad,
            "admision": _admision,
            "oportunidades": _oportunidades,
        }
        await cargar[servicio](db)
    finally:
        await db.close()
    print(f"Datos ficticios cargados en {settings.db_path} ({servicio}).")


if __name__ == "__main__":
    asyncio.run(main())
