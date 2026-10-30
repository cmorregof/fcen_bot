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

    # Revisor de soportes desde la web. Apagado hasta que exista el aval de
    # tratamiento de datos: los soportes traen nombres y listados.
    revisor_activo: bool = False
    # Ninguna corrida gasta más de esto en la API (USD).
    revisor_tope_usd: float = 10.0
    # Tamaño máximo del zip que se sube y de lo que trae descomprimido (MB).
    revisor_max_mb: int = 500
    revisor_max_descomprimido_mb: int = 2000
    revisor_max_archivos: int = 5000
    # Días que se guardan salidas y caché en el volumen.
    revisor_retencion_dias: int = 30
    # Carpeta del volumen para soportes, salidas y caché. Vacía: junto a la
    # base del servicio (en Railway, /data/calidad/revisor).
    revisor_dir: Path | None = None


calidad_settings = CalidadSettings()
