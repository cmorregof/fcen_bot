"""Cliente mínimo de la Bot API de Telegram. Solo E/S, sin lógica."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any

import httpx

from app.core.config import settings

_LIMITE = 4096
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)(?:\s[^>]*)?>")


def _base() -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}"


def _file_base() -> str:
    return f"https://api.telegram.org/file/bot{settings.telegram_bot_token}"


def trozos_html(texto: str, limite: int = _LIMITE - 64) -> list[str]:
    """Parte un mensaje largo por párrafos y cierra/reabre etiquetas abiertas."""
    if len(texto) <= limite:
        return [texto]
    crudos: list[str] = []
    actual = ""
    for bloque in texto.split("\n"):
        candidato = bloque if not actual else f"{actual}\n{bloque}"
        if len(candidato) <= limite:
            actual = candidato
            continue
        if actual:
            crudos.append(actual)
        while len(bloque) > limite:
            corte = _corte_seguro(bloque, limite)
            crudos.append(bloque[:corte])
            bloque = bloque[corte:]
        actual = bloque
    if actual:
        crudos.append(actual)

    balanceados: list[str] = []
    abiertas: list[tuple[str, str]] = []
    for trozo in crudos:
        prefijo = "".join(tag for _, tag in abiertas)
        for m in _TAG_RE.finditer(trozo):
            cierre, nombre = bool(m.group(1)), m.group(2).lower()
            if cierre:
                for i in range(len(abiertas) - 1, -1, -1):
                    if abiertas[i][0] == nombre:
                        del abiertas[i]
                        break
            else:
                abiertas.append((nombre, m.group(0)))
        sufijo = "".join(f"</{n}>" for n, _ in reversed(abiertas))
        balanceados.append(f"{prefijo}{trozo}{sufijo}")
    return balanceados


def _corte_seguro(texto: str, limite: int) -> int:
    """Posición de corte que no parte una entidad (&amp;) ni una etiqueta (<b>)."""
    corte = limite
    for abre, cierra in (("&", ";"), ("<", ">")):
        i = texto.rfind(abre, 0, corte)
        if i != -1 and texto.find(cierra, i, corte) == -1:
            corte = i
    return corte if corte > 0 else limite


async def _post(metodo: str, **kwargs: Any) -> dict[str, Any]:
    for intento in range(3):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{_base()}/{metodo}", **kwargs)
            if resp.status_code == 429 and intento < 2:
                espera = 1.0
                with contextlib.suppress(Exception):
                    espera = float(resp.json()["parameters"]["retry_after"])
                await asyncio.sleep(espera)
                continue
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data
        except httpx.RequestError:
            if intento >= 2:
                raise
            await asyncio.sleep(0.5 * (intento + 1))
    raise RuntimeError(f"Telegram {metodo}: sin respuesta")


async def send_message(
    chat_id: int,
    texto: str,
    *,
    botones: list[list[dict[str, str]]] | None = None,
    responder_a: int | None = None,
    forzar_respuesta: bool = False,
) -> int | None:
    """Envía texto HTML. Los botones van en el último trozo. Devuelve su id."""
    trozos = trozos_html(texto)
    ultimo_id: int | None = None
    for i, trozo in enumerate(trozos):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": trozo,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if botones and i == len(trozos) - 1:
            payload["reply_markup"] = {"inline_keyboard": botones}
        elif forzar_respuesta and i == len(trozos) - 1:
            payload["reply_markup"] = {"force_reply": True}
        if responder_a and i == 0:
            payload["reply_parameters"] = {
                "message_id": responder_a,
                "allow_sending_without_reply": True,
            }
        data = await _post("sendMessage", json=payload)
        ultimo_id = int(data.get("result", {}).get("message_id", 0)) or None
    return ultimo_id


async def editar_botones(
    chat_id: int, message_id: int, botones: list[list[dict[str, str]]] | None
) -> None:
    with contextlib.suppress(httpx.HTTPStatusError):
        await _post(
            "editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": botones or []},
            },
        )


async def responder_callback(callback_id: str, texto: str | None = None) -> None:
    payload: dict[str, Any] = {"callback_query_id": callback_id}
    if texto:
        payload["text"] = texto[:200]
    with contextlib.suppress(httpx.HTTPStatusError):
        await _post("answerCallbackQuery", json=payload)


async def send_document(
    chat_id: int,
    *,
    nombre: str,
    contenido: bytes,
    mime: str,
    caption: str | None = None,
) -> None:
    data: dict[str, str] = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1024]
        data["parse_mode"] = "HTML"
    await _post(
        "sendDocument",
        data=data,
        files={"document": (nombre, contenido, mime)},
    )


async def descargar_archivo(file_id: str, *, max_bytes: int = 15_000_000) -> bytes:
    meta = await _post("getFile", json={"file_id": file_id})
    ruta = str(meta.get("result", {}).get("file_path", ""))
    if not ruta:
        raise RuntimeError("Telegram no devolvió la ruta del archivo")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{_file_base()}/{ruta}")
        resp.raise_for_status()
    if len(resp.content) > max_bytes:
        raise RuntimeError("El archivo supera el tamaño permitido")
    return resp.content


async def set_webhook(url: str, secret: str) -> dict[str, Any]:
    return await _post(
        "setWebhook",
        json={
            "url": url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        },
    )
