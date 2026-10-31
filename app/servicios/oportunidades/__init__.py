"""Servicio de estudiantes y oportunidades (BOT_SERVICIO=oportunidades).

Vigía semanal de ofertas de empleo, prácticas, pasantías, convocatorias y
becas para los programas de la FCEN, con dos agentes —buscador (el modelo lee
las fuentes) y verificador (reglas deterministas)— y revisión humana del
boletín antes de que salga. Se usa desde la web; no tiene bot de Telegram en
esta versión. No guarda datos de estudiantes. Ver docs/oportunidades.md.
"""

from __future__ import annotations

import logging

from app.core.conexion import Conexion
from app.schemas.telegram import Update

logger = logging.getLogger(__name__)

PROPOSITO = (
    "Reunir ofertas de empleo, prácticas, pasantías, convocatorias y becas "
    "para los programas de la FCEN y armar un boletín semanal que una persona "
    "revisa y aprueba."
)


async def manejar_update(db: Conexion, update: Update) -> None:
    """Sin bot de Telegram en esta versión: los updates se ignoran."""
    logger.info("oportunidades: update %s ignorado (sin bot)", update.update_id)
