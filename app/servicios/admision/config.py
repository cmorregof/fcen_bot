"""Configuración propia del servicio de admisión (variables ADMISION_*)."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[3]


class AdmisionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="ADMISION_", extra="ignore"
    )

    # Carpeta con el listado y la guía (PDF/TXT/MD). Va fuera del repositorio.
    insumos_dir: Path = Path("~/fcen_insumos/admision")
    # Contacto de la responsable cuando algo no está en las fuentes.
    contacto: str = "la responsable del proceso en la Facultad"
    # IDs de Telegram autorizados para /metricas, separados por comas.
    admin_ids: str = ""
    modelo: str = "claude-sonnet-5-5"
    max_tokens: int = 1200
    timeout_segundos: float = 90.0

    # Reglas de archivo
    max_bytes: int = 10_000_000
    max_paginas: int = 12
    lado_minimo_px: int = 600
    # Lado mayor de las imágenes antes de enviarlas al modelo.
    lado_maximo_px: int = 1568

    chequeo_path: Path = RAIZ / "config" / "admision" / "chequeo.yaml"
    aviso_path: Path = RAIZ / "docs" / "admision" / "aviso_datos.md"

    @field_validator("insumos_dir", mode="after")
    @classmethod
    def _expandir(cls, valor: Path) -> Path:
        return valor.expanduser()

    @property
    def admins(self) -> frozenset[int]:
        return frozenset(
            int(p) for p in self.admin_ids.replace(";", ",").split(",") if p.strip().isdigit()
        )


config = AdmisionSettings()
