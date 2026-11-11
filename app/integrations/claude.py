"""Llamada estructurada a Claude: imágenes + texto -> un objeto Pydantic.

La herramienta se fuerza con `tool_choice`, así que la única salida posible es
el JSON del caso. Si no valida, se devuelve None y quien llama lo reporta.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

_M = TypeVar("_M", bound=BaseModel)


@dataclass(frozen=True)
class Imagen:
    datos: bytes
    media_type: str = "image/jpeg"


@dataclass(frozen=True)
class Resultado:
    objeto: BaseModel | None
    input_tokens: int
    output_tokens: int
    error: str | None = None


def esquema_plano(modelo: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema de Pydantic con los $ref resueltos en línea."""
    esquema = modelo.model_json_schema()
    defs: dict[str, Any] = esquema.pop("$defs", {})

    def resolver(nodo: Any) -> Any:
        if isinstance(nodo, dict):
            ref = nodo.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                base = copy.deepcopy(defs[ref.split("/")[-1]])
                extras = {k: v for k, v in nodo.items() if k != "$ref"}
                base.update(extras)
                return resolver(base)
            return {k: resolver(v) for k, v in nodo.items()}
        if isinstance(nodo, list):
            return [resolver(v) for v in nodo]
        return nodo

    plano: dict[str, Any] = resolver(esquema)
    return plano


def explicar_error(exc: Exception) -> str:
    """Mensaje corto y accionable para los errores de configuración comunes."""
    texto = str(exc)
    if "workspace" in texto:
        return (
            "la API key no pertenece a un workspace de la Console. Crea la key "
            "dentro de un workspace o define ANTHROPIC_WORKSPACE_ID en Railway."
        )
    if "credit balance" in texto:
        return "no quedan créditos en la Console de Anthropic."
    if "authentication" in texto.lower() or "invalid x-api-key" in texto:
        return "la API key no es válida; revisa ANTHROPIC_API_KEY en Railway."
    if "not_found" in texto and "model" in texto:
        return "el modelo configurado no existe; revisa EXTRACTION_MODEL."
    return f"no pude consultar el modelo ({texto[:300]})"


class Estructurador(Protocol):
    async def extraer(
        self,
        *,
        sistema: str,
        texto: str,
        imagenes: list[Imagen],
        modelo_salida: type[BaseModel],
        nombre_herramienta: str,
        modelo: str,
        max_tokens: int,
    ) -> Resultado: ...


class LectorDocumentos(Protocol):
    """Lee un documento (texto, PDF o imágenes) con un nivel de esfuerzo."""

    async def leer_documento(
        self,
        *,
        sistema: str,
        texto: str,
        imagenes: list[Imagen],
        pdf: bytes | None,
        modelo_salida: type[BaseModel],
        nombre_herramienta: str,
        modelo: str,
        max_tokens: int,
        esfuerzo: str,
    ) -> Resultado: ...


class ClaudeEstructurador:
    def __init__(
        self, api_key: str, timeout_seconds: float, workspace_id: str = ""
    ) -> None:
        cabeceras = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = AsyncAnthropic(
            api_key=api_key, timeout=timeout_seconds, default_headers=cabeceras
        )

    async def extraer(
        self,
        *,
        sistema: str,
        texto: str,
        imagenes: list[Imagen],
        modelo_salida: type[BaseModel],
        nombre_herramienta: str,
        modelo: str,
        max_tokens: int,
    ) -> Resultado:
        return await self._llamar(
            sistema=sistema,
            contenido=[*_bloques_imagen(imagenes), {"type": "text", "text": texto}],
            modelo_salida=modelo_salida,
            nombre_herramienta=nombre_herramienta,
            descripcion="Registra los datos del caso estudiantil.",
            modelo=modelo,
            max_tokens=max_tokens,
        )

    async def leer_documento(
        self,
        *,
        sistema: str,
        texto: str,
        imagenes: list[Imagen],
        pdf: bytes | None,
        modelo_salida: type[BaseModel],
        nombre_herramienta: str,
        modelo: str,
        max_tokens: int,
        esfuerzo: str,
    ) -> Resultado:
        contenido: list[dict[str, Any]] = []
        if pdf is not None:
            contenido.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(pdf).decode("ascii"),
                    },
                }
            )
        contenido.extend(_bloques_imagen(imagenes))
        contenido.append({"type": "text", "text": texto})
        return await self._llamar(
            sistema=sistema,
            contenido=contenido,
            modelo_salida=modelo_salida,
            nombre_herramienta=nombre_herramienta,
            descripcion="Registra el resumen del anexo.",
            modelo=modelo,
            max_tokens=max_tokens,
            extra={"output_config": {"effort": esfuerzo}} if esfuerzo else {},
        )

    async def _llamar(
        self,
        *,
        sistema: str,
        contenido: list[dict[str, Any]],
        modelo_salida: type[BaseModel],
        nombre_herramienta: str,
        descripcion: str,
        modelo: str,
        max_tokens: int,
        extra: dict[str, Any] | None = None,
    ) -> Resultado:
        herramienta = {
            "name": nombre_herramienta,
            "description": descripcion,
            "input_schema": esquema_plano(modelo_salida),
        }
        try:
            crear: Any = self._client.messages.create
            resp = await crear(
                model=modelo,
                max_tokens=max_tokens,
                system=sistema,
                tools=[herramienta],
                # Los modelos recientes no aceptan forzar una herramienta
                # ("tool"/"any"). Con "auto" + la instrucción del sistema el
                # modelo la usa; si responde con texto, se lee el JSON de ahí.
                tool_choice={"type": "auto"},
                messages=[{"role": "user", "content": contenido}],
                **(extra or {}),
            )
        except Exception as exc:  # red, cuota, clave inválida
            logger.warning("Fallo la llamada a Claude: %s", exc)
            return Resultado(None, 0, 0, error=explicar_error(exc))

        uso_in = int(getattr(resp.usage, "input_tokens", 0) or 0)
        uso_out = int(getattr(resp.usage, "output_tokens", 0) or 0)
        motivo = getattr(resp, "stop_reason", None)
        if motivo == "max_tokens":
            # La salida quedó cortada: un JSON parcial podría validar con
            # campos vacíos y parecer un caso completo.
            return Resultado(
                None, uso_in, uso_out, error="La respuesta del modelo quedó incompleta."
            )
        if motivo == "refusal":
            return Resultado(
                None, uso_in, uso_out, error="El modelo no quiso leer este contenido."
            )
        entrada: Any = None
        for bloque in resp.content:
            if getattr(bloque, "type", None) == "tool_use":
                entrada = getattr(bloque, "input", None)
                break
        if entrada is None:
            texto = "".join(
                str(getattr(b, "text", ""))
                for b in resp.content
                if getattr(b, "type", None) == "text"
            )
            entrada = json_del_texto(texto)
        if entrada is None:
            return Resultado(
                None, uso_in, uso_out, error="El modelo no registró el resultado."
            )
        try:
            objeto = modelo_salida.model_validate(entrada)
        except ValidationError as exc:
            logger.warning("Salida del modelo no válida: %s", exc)
            return Resultado(
                None, uso_in, uso_out, error="El modelo devolvió datos no válidos."
            )
        return Resultado(objeto, uso_in, uso_out)


def _bloques_imagen(imagenes: list[Imagen]) -> list[dict[str, Any]]:
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": imagen.media_type,
                "data": base64.b64encode(imagen.datos).decode("ascii"),
            },
        }
        for imagen in imagenes
    ]


def json_del_texto(texto: str) -> Any:
    """El primer objeto JSON del texto (con o sin bloque ```json)."""
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        return None
    try:
        return json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError:
        return None


def validar(resultado: Resultado, tipo: type[_M]) -> _M | None:
    return resultado.objeto if isinstance(resultado.objeto, tipo) else None
