"""Configuración del bot. Todo lo secreto llega por variables de entorno."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import field_validator, model_validator
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

    # Almacenamiento. Si DB_PATH, MEDIA_DIR u OUTPUT_DIR no se definen, se
    # derivan de DATA_DIR por servicio: <DATA_DIR>/<servicio>/... En Docker,
    # DATA_DIR=/data (el volumen).
    data_dir: Path = Path("data")
    db_path: Path = Path("data/actas/fcen.db")
    media_dir: Path = Path("data/actas/media")
    output_dir: Path = Path("data/actas/out")

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

    @model_validator(mode="before")
    @classmethod
    def _rutas_por_defecto(cls, datos: Any) -> Any:
        if not isinstance(datos, dict):
            return datos
        datos = dict(datos)
        servicio = str(datos.get("bot_servicio") or "actas")
        data_dir = Path(str(datos.get("data_dir") or "data"))
        base = data_dir / servicio
        # Actas ya desplegado guardaba todo en <DATA_DIR>/fcen.db, media y out.
        # Si esa base existe y la nueva no, se sigue usando: así un despliegue
        # no deja huérfanos los casos ni los usuarios registrados.
        if (
            servicio == "actas"
            and not datos.get("db_path")
            and (data_dir / "fcen.db").exists()
            and not (base / "fcen.db").exists()
        ):
            base = data_dir
        for campo, nombre in (
            ("db_path", "fcen.db"),
            ("media_dir", "media"),
            ("output_dir", "out"),
        ):
            if not datos.get(campo):  # ausente o vacío en el .env
                datos[campo] = base / nombre
        return datos

    @model_validator(mode="after")
    def _aislamiento(self) -> Self:
        # Un servicio nunca usa la base de actas (AGENTS.md).
        if self.bot_servicio != "actas":
            legado = {
                self.data_dir / "fcen.db",
                Path("data/fcen.db"),
                Path("/data/fcen.db"),
            }
            if self.db_path in legado or "actas" in self.db_path.parts:
                raise ValueError(
                    f"DB_PATH={self.db_path} es la base de actas; "
                    f"el servicio {self.bot_servicio} necesita la suya."
                )
        return self


settings = Settings()
