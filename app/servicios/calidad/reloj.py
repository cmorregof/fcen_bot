"""Fecha y hora actuales, en un solo lugar para poder fijarlas en las pruebas."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def ahora() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def hoy() -> date:
    return ahora().date()
