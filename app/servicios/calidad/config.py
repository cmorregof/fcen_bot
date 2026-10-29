"""Configuración propia del servicio de calidad (variables CALIDAD_*)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[3]


class CalidadSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CALIDAD_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    # Código que envía cada persona con /start para registrarse.
    invite_code: str = ""
    max_users: int = 10
    # Una tarea sin evidencia vence "pronto" si su fecha límite cae en este plazo.
    dias_proxima: int = 28
    directorio_path: Path = RAIZ / "config" / "calidad" / "directorio.yaml"
    # El envío real de la alerta quincenal sigue apagado hasta que se active.
    alertas_activas: bool = Field(default=False, validation_alias="ALERTAS_ACTIVAS")


calidad_settings = CalidadSettings()
