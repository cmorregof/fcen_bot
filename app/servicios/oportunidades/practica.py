"""Datos ficticios del entorno de práctica (MEMORIA_PRACTICA=true)."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.conexion import Conexion
from app.servicios.oportunidades import almacen, verificador
from app.servicios.oportunidades.db import init_oportunidades
from app.servicios.oportunidades.texto import clave_texto

_ENTIDADES = (
    {"nombre": "Empresa Ficticia Alfa S.A.S.", "tipo": "empresa", "aliada": True,
     "sector": "Analítica de datos", "convenio": "Convenio de prácticas (ficticio)"},
    {"nombre": "Instituto Ficticio Beta", "tipo": "entidad_publica",
     "sector": "Investigación"},
)  # fmt: skip


def _ofertas(hoy: date) -> list[almacen.NuevaOferta]:
    def oferta(
        titulo: str,
        entidad: str,
        tipo: str,
        programas: list[str],
        dias: int | None,
        dudas: list[str] | None = None,
    ) -> almacen.NuevaOferta:
        return almacen.NuevaOferta(
            fuente="manual",
            url=f"https://ejemplo.invalid/ofertas/{clave_texto(titulo).replace(' ', '-')}",
            titulo=titulo,
            entidad=entidad,
            tipo=tipo,
            programas=programas,
            areas=[],
            resumen="Oferta ficticia para practicar la revisión.",
            requisitos="Estudiante de los últimos semestres (dato ficticio).",
            fecha_cierre=(hoy + timedelta(days=dias)).isoformat() if dias else None,
            modalidad="hibrida",
            lugar="Manizales",
            dudas=dudas or [],
        )

    return [
        oferta("Practicante de analítica", "Empresa Ficticia Alfa S.A.S.",
               "practica", ["estadistica", "matematicas"], 20),
        oferta("Pasantía en óptica", "Instituto Ficticio Beta", "pasantia",
               ["ing_fisica"], 15),
        oferta("Beca de maestría", "Fundación Ficticia Gamma", "beca", [], None,
               ["No es claro a qué programas aplica."]),
    ]  # fmt: skip


async def sembrar(db: Conexion, hoy: date) -> int:
    await init_oportunidades(db)
    for datos in _ENTIDADES:
        await almacen.guardar_entidad(db, dict(datos), "práctica")
    ids = [await almacen.insertar(db, o, "práctica") for o in _ofertas(hoy)]
    await db.commit()
    for oferta_id in ids:
        await verificador.revisar(db, oferta_id, hoy, None)
    return len(ids) + len(_ENTIDADES)
