"""Configuración de la web (variables WEB_*). Los secretos solo por entorno."""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="WEB_", extra="ignore"
    )

    # Client ID del cliente OAuth de Google (tipo «aplicación web»).
    google_client_id: str = ""
    # Dominio permitido para el personal.
    dominio: str = "unal.edu.co"
    # Firma las sesiones propias de este backend.
    session_secret: str = ""
    session_horas: int = 8
    admitido_horas: int = 2
    # Correos que son admin de este servicio aunque no estén en la tabla.
    admins: str = ""
    # Orígenes del frontend, separados por comas.
    origins: str = "http://localhost:3000"
    # Entrada sin Google para correr en local. Nunca se activa en Railway.
    auth_dev: bool = False

    @property
    def lista_admins(self) -> frozenset[str]:
        return frozenset(
            c.strip().lower()
            for c in self.admins.replace(";", ",").split(",")
            if c.strip()
        )

    @property
    def lista_origins(self) -> list[str]:
        return [o.strip() for o in self.origins.split(",") if o.strip()]

    @property
    def dev_permitido(self) -> bool:
        return self.auth_dev and not os.environ.get("RAILWAY_ENVIRONMENT")


web_settings = WebSettings()
