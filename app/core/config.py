"""Configuración del bot. Todo lo secreto llega por variables de entorno."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    # Código que una administrativa envía con /start para registrarse.
    invite_code: str = ""
    max_users: int = 4

    # Rutas internas (cron de GitHub Actions)
    internal_cron_secret: str = ""

    # Claude
    anthropic_api_key: str = ""
    extraction_model: str = "claude-sonnet-5-5"
    correction_model: str = "claude-sonnet-5-5"
    extraction_max_tokens: int = 4000
    extraction_timeout_seconds: float = 90.0
    # Lado mayor de las imágenes antes de enviarlas al modelo (controla tokens).
    max_image_side: int = 1568
    # Precios en USD por millón de tokens, para el comando /costo.
    precio_input_mtok: float = 2.0
    precio_output_mtok: float = 10.0

    # Periodo académico: con la fecha de inicio de clases se calcula la semana
    # en la que llegó cada solicitud (Acuerdo 027 de 2024).
    periodo_actual: str = "2026-2S"
    periodo_inicio: date | None = None

    # Almacenamiento
    db_path: Path = Path("data/fcen.db")
    media_dir: Path = Path("data/media")
    output_dir: Path = Path("data/out")

    # Conversión a PDF
    soffice_bin: str = "soffice"
    pdf_timeout_seconds: float = 120.0

    timezone: str = "America/Bogota"
    log_level: str = "INFO"


settings = Settings()
