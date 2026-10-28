"""Configuración del bot. Todo lo secreto llega por variables de entorno."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Servicio actual del bot (actas, admision, calidad)
    bot_servicio: Literal["actas", "admision", "calidad"] = "actas"

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
    # Solo si la API key no pertenece a un workspace de la Console: el ID del
    # workspace al que se cobra (wrkspc_...).
    anthropic_workspace_id: str = ""
    extraction_model: str = "claude-sonnet-5-5"
    correction_model: str = "claude-sonnet-5-5"
    extraction_max_tokens: int = 8000
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

    # Almacenamiento (por defecto aislados por servicio: data/<servicio>/...)
    db_path: Path = Field(default=Path())
    media_dir: Path = Field(default=Path())
    output_dir: Path = Field(default=Path())

    # Conversión a PDF
    soffice_bin: str = "soffice"
    pdf_timeout_seconds: float = 120.0

    timezone: str = "America/Bogota"
    log_level: str = "INFO"

    @field_validator("periodo_inicio", mode="before")
    @classmethod
    def _fecha_vacia(cls, valor: object) -> object:
        # En .env.example la variable viene vacía: eso es "sin configurar".
        return None if valor == "" else valor

    @model_validator(mode="after")
    def _rutas_por_defecto(self) -> Self:
        # Si no se configuraron o tienen los valores del .env original de un solo servicio:
        if (
            not self.db_path
            or self.db_path == Path()
            or self.db_path == Path("data/fcen.db")
        ):
            self.db_path = Path(f"data/{self.bot_servicio}/fcen.db")
        if (
            not self.media_dir
            or self.media_dir == Path()
            or self.media_dir == Path("data/media")
        ):
            self.media_dir = Path(f"data/{self.bot_servicio}/media")
        if (
            not self.output_dir
            or self.output_dir == Path()
            or self.output_dir == Path("data/out")
        ):
            self.output_dir = Path(f"data/{self.bot_servicio}/out")
        return self


settings = Settings()
