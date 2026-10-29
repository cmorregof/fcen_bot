"""Llamada al modelo con una herramienta estructurada.

Los modelos actuales no aceptan forzar la herramienta; se usa
`tool_choice=auto` con `strict` y la instrucción en el sistema. Si el modelo
contesta en texto, se intenta leer el JSON de ahí.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from app.integrations.claude import esquema_plano, json_del_texto

logger = logging.getLogger(__name__)


@dataclass
class Respuesta:
    entrada: dict[str, Any] | None
    tokens_entrada: int = 0
    tokens_salida: int = 0
    error: str = ""


class ClienteModelo(Protocol):
    async def llamar(
        self,
        *,
        modelo: str,
        sistema: str,
        bloques: list[dict[str, Any]],
        texto: str,
        salida: type[BaseModel],
        nombre_herramienta: str,
        esfuerzo: str,
        max_tokens: int,
    ) -> Respuesta: ...


def herramienta(salida: type[BaseModel], nombre: str) -> dict[str, Any]:
    return {
        "name": nombre,
        "description": "Registra el resultado. Úsala siempre, una sola vez.",
        "input_schema": esquema_plano(salida),
        "strict": True,
    }


def es_fatal(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(
        marca in texto
        for marca in ("credit balance", "invalid x-api-key", "authentication_error")
    )


def error_corto(exc: Exception) -> str:
    texto = str(exc)
    if "credit balance" in texto:
        return "no quedan créditos en la cuenta de la API"
    if "invalid x-api-key" in texto or "authentication_error" in texto:
        return "la API key no es válida"
    return f"{type(exc).__name__}: {texto[:200]}"


class ClienteAnthropic:
    def __init__(
        self, api_key: str, workspace_id: str = "", timeout: float = 300.0
    ) -> None:
        from anthropic import AsyncAnthropic

        cabeceras = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._cliente = AsyncAnthropic(
            api_key=api_key, timeout=timeout, max_retries=4, default_headers=cabeceras
        )
        # Sin créditos o con la clave inválida, las demás llamadas también
        # fallarían: se detiene la corrida en vez de gastar cientos de intentos.
        self.detenido = ""

    async def llamar(
        self,
        *,
        modelo: str,
        sistema: str,
        bloques: list[dict[str, Any]],
        texto: str,
        salida: type[BaseModel],
        nombre_herramienta: str,
        esfuerzo: str,
        max_tokens: int,
    ) -> Respuesta:
        if self.detenido:
            return Respuesta(None, error=self.detenido)
        contenido = [*bloques, {"type": "text", "text": texto}]
        try:
            crear: Any = self._cliente.beta.messages.create
            resp = await crear(
                model=modelo,
                max_tokens=max_tokens,
                system=sistema,
                tools=[herramienta(salida, nombre_herramienta)],
                tool_choice={"type": "auto"},
                output_config={"effort": esfuerzo},
                # Si un clasificador de seguridad rechaza por error, la API
                # reintenta con otro modelo dentro de la misma llamada.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": contenido}],
            )
        except Exception as exc:  # red, cuota, clave inválida
            error = error_corto(exc)
            if es_fatal(exc):
                self.detenido = f"corrida detenida: {error}"
            logger.warning("Falló la llamada al modelo: %s", error)
            return Respuesta(None, error=error)

        uso = resp.usage
        ent = int(getattr(uso, "input_tokens", 0) or 0)
        ent += int(getattr(uso, "cache_creation_input_tokens", 0) or 0)
        ent += int(getattr(uso, "cache_read_input_tokens", 0) or 0)
        sal = int(getattr(uso, "output_tokens", 0) or 0)
        motivo = getattr(resp, "stop_reason", None)
        if motivo == "max_tokens":
            return Respuesta(None, ent, sal, "la respuesta quedó cortada")
        if motivo == "refusal":
            return Respuesta(None, ent, sal, "el modelo se negó a responder")
        entrada: Any = None
        for bloque in resp.content:
            if getattr(bloque, "type", None) == "tool_use":
                entrada = getattr(bloque, "input", None)
                break
        if entrada is None:
            texto_resp = "".join(
                str(getattr(b, "text", ""))
                for b in resp.content
                if getattr(b, "type", None) == "text"
            )
            entrada = json_del_texto(texto_resp)
        if not isinstance(entrada, dict):
            return Respuesta(None, ent, sal, "el modelo no usó la herramienta")
        return Respuesta(entrada, ent, sal)
