"""Configuración propia del servicio de oportunidades (variables OPORTUNIDADES_*)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[3]


class OportunidadesSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPORTUNIDADES_", env_file=".env", extra="ignore"
    )

    # Lista de fuentes (la edita quien administre el servicio).
    fuentes_path: Path = RAIZ / "config" / "oportunidades.yaml"
    # El cron semanal no hace nada si esto es false. Apagado hasta que la
    # Decanatura apruebe las fuentes.
    vigia_activa: bool = False
    # Modelo que lee las páginas. Vacío: EXTRACTION_MODEL.
    modelo: str = ""
    max_tokens: int = 4000
    # Tope del texto de cada página que se manda al modelo (unas 8 000 tokens).
    max_caracteres_pagina: int = 30_000
    # Ninguna corrida gasta más de esto en la API (USD).
    tope_usd_corrida: float = 1.0
    # Identificación honesta ante los sitios: quién consulta y para qué.
    user_agent: str = (
        "MemorIA-FCEN/0.1 (UNAL Manizales; vigia de oportunidades; "
        "+https://memoria-fcen.vercel.app)"
    )
    timeout_segundos: float = 20.0
    # Pausa mínima entre dos pedidos al mismo sitio. Si robots.txt pide un
    # Crawl-delay mayor, se usa ese.
    pausa_segundos: float = 5.0
    # Una oferta que cierra antes de esto no entra al boletín.
    dias_minimos_cierre: int = 2


config = OportunidadesSettings()
