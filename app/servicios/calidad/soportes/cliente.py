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
    # False si la petición no llegó a la API (corrida detenida o error de red):
    # no se cobra y no cuenta como llamada.
    llamada: bool = True
    modelo: str = ""  # el que respondió (puede ser el de respaldo)


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
    """Errores que se repetirían en todas las llamadas: clave, permisos, modelo."""
    import anthropic

    if isinstance(
        exc,
        anthropic.AuthenticationError
        | anthropic.PermissionDeniedError
        | anthropic.NotFoundError,
    ):
        return True
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
            return Respuesta(None, error=self.detenido, llamada=False)
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
            # Solo el tipo: el texto del error puede citar contenido enviado.
            logger.warning("Falló la llamada al modelo: %s", type(exc).__name__)
            return Respuesta(None, error=error, llamada=False)

        uso = resp.usage
        ent = int(getattr(uso, "input_tokens", 0) or 0)
        # La escritura en caché se cobra a 1,25x: se cuenta así en el costo.
        ent += int(1.25 * int(getattr(uso, "cache_creation_input_tokens", 0) or 0))
        ent += int(getattr(uso, "cache_read_input_tokens", 0) or 0)
        sal = int(getattr(uso, "output_tokens", 0) or 0)
        servido = str(getattr(resp, "model", "") or modelo)
        motivo = getattr(resp, "stop_reason", None)
        if motivo == "max_tokens":
            return Respuesta(
                None, ent, sal, "la respuesta quedó cortada", modelo=servido
            )
        if motivo == "refusal":
            return Respuesta(
                None, ent, sal, "el modelo se negó a responder", modelo=servido
            )
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
            return Respuesta(
                None, ent, sal, "el modelo no usó la herramienta", modelo=servido
            )
        return Respuesta(entrada, ent, sal, modelo=servido)


# Cota de tokens de entrada por bloque, holgada. Los bloques salen de
# `contenido.preparar`: PDF de hasta 4 páginas e imágenes de hasta 1568 px.
TOKENS_POR_PAGINA_PDF = 5000  # imagen de la página más su texto
TOKENS_POR_IMAGEN = 3300  # 1568 x 1568 / 750
TOKENS_FIJOS = 2000  # herramienta, esquema y envoltura del mensaje
CARACTERES_POR_TOKEN = 2.5  # el español da unos 3,5: 2,5 sobreestima


def tokens_entrada_maximos(
    sistema: str, bloques: list[dict[str, Any]], texto: str
) -> int:
    """Cota alta de los tokens de entrada de una petición, sin llamar a la API."""
    from app.servicios.calidad.soportes import contenido

    caracteres = len(sistema) + len(texto)
    tokens = TOKENS_FIJOS
    for b in bloques:
        if b.get("type") == "document":
            tokens += contenido.PAGINAS_PDF * TOKENS_POR_PAGINA_PDF
        elif b.get("type") == "image":
            tokens += TOKENS_POR_IMAGEN
        else:
            caracteres += len(str(b.get("text", "")))
    return tokens + int(caracteres / CARACTERES_POR_TOKEN) + 1


class ClienteConTope:
    """Envuelve otro cliente y no deja que la corrida pase de `tope_usd`.

    Antes de cada llamada reserva su costo máximo: los tokens de entrada de la
    petición real (cota alta, ver `tokens_entrada_maximos`) cobrados como
    escritura en caché (1,25x) y la salida completa, a la tarifa del modelo
    más caro (la API puede responder con un modelo de respaldo). Si lo
    gastado más lo reservado por las llamadas en curso supera el tope, no
    llama y detiene la corrida: lo ya descrito queda en la caché.
    """

    def __init__(self, cliente: ClienteModelo, uso: Any, tope_usd: float) -> None:
        self._cliente = cliente
        self._uso = uso  # modelos.Uso; Any para no importar modelos aquí
        self.tope_usd = tope_usd
        self._reservado = 0.0
        self.detenido = ""

    @staticmethod
    def reserva(
        sistema: str, bloques: list[dict[str, Any]], texto: str, max_tokens: int
    ) -> float:
        from app.servicios.calidad.soportes.modelos import PRECIOS_USD_POR_MILLON

        p_in = max(p[0] for p in PRECIOS_USD_POR_MILLON.values())
        p_out = max(p[1] for p in PRECIOS_USD_POR_MILLON.values())
        entrada = tokens_entrada_maximos(sistema, bloques, texto)
        return (1.25 * entrada * p_in + max_tokens * p_out) / 1e6

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
        detenido_abajo = getattr(self._cliente, "detenido", "")
        if detenido_abajo and not self.detenido:
            self.detenido = detenido_abajo
        if self.detenido:
            return Respuesta(None, error=self.detenido, llamada=False)
        reserva = self.reserva(sistema, bloques, texto, max_tokens)
        if self._uso.costo() + self._reservado + reserva > self.tope_usd:
            self.detenido = (
                f"corrida detenida: se alcanzó el tope de {self.tope_usd:.2f} USD"
            )
            return Respuesta(None, error=self.detenido, llamada=False)
        self._reservado += reserva
        try:
            # El que llama registra el uso apenas vuelve, sin otra espera en
            # medio: la reserva se libera y el gasto se suma en el mismo paso.
            return await self._cliente.llamar(
                modelo=modelo,
                sistema=sistema,
                bloques=bloques,
                texto=texto,
                salida=salida,
                nombre_herramienta=nombre_herramienta,
                esfuerzo=esfuerzo,
                max_tokens=max_tokens,
            )
        finally:
            self._reservado -= reserva
