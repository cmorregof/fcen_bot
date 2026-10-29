"""Sesiones de la web: Google para el personal, sesión anónima para admitidos.

Cada backend firma sus propias sesiones y guarda sus usuarios autorizados en
su propia base (tabla web_usuarios). Ningún servicio consulta a otro.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal

import aiosqlite
from fastapi import Depends, Header, HTTPException

from app.api.web.config import web_settings
from app.core.config import settings
from app.db.session import connect

Rol = Literal["administrativa", "comite", "calidad", "admision", "decanatura", "admin"]

# Roles que tienen sentido en cada servicio. Un rol fuera de esta lista no
# puede registrarse en ese backend.
ROLES_POR_SERVICIO: dict[str, tuple[Rol, ...]] = {
    "actas": ("administrativa", "comite", "decanatura", "admin"),
    "calidad": ("calidad", "decanatura", "admin"),
    "admision": ("admision", "decanatura", "admin"),
}

_SECRETO_DEV = secrets.token_hex(32)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS web_usuarios (
    correo     TEXT PRIMARY KEY,
    nombre     TEXT,
    rol        TEXT NOT NULL,
    direccion  TEXT,
    activo     INTEGER NOT NULL DEFAULT 1,
    creado     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


# ---------------------------------------------------------------------------
# Base de datos del servicio
# ---------------------------------------------------------------------------


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Conexión a la base de ESTE servicio (settings.db_path), nunca otra."""
    db = await connect()
    try:
        await db.execute(_ESQUEMA)
        await db.commit()
        yield db
    finally:
        await db.close()


Db = Annotated[aiosqlite.Connection, Depends(get_db)]


# ---------------------------------------------------------------------------
# Tokens firmados
# ---------------------------------------------------------------------------


def _secreto() -> bytes:
    if web_settings.session_secret:
        return web_settings.session_secret.encode()
    if web_settings.dev_permitido:
        return _SECRETO_DEV.encode()
    raise HTTPException(503, "La web no está configurada en este servicio.")


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def firmar(carga: dict[str, object], horas: int) -> str:
    datos = {
        **carga,
        "srv": settings.bot_servicio,
        "exp": int(time.time()) + horas * 3600,
    }
    cuerpo = _b64(json.dumps(datos, separators=(",", ":")).encode())
    firma = _b64(hmac.new(_secreto(), cuerpo.encode(), hashlib.sha256).digest())
    return f"{cuerpo}.{firma}"


def leer(token: str) -> dict[str, object]:
    try:
        cuerpo, firma = token.split(".")
    except ValueError:
        raise HTTPException(401, "Sesión inválida.") from None
    esperada = _b64(hmac.new(_secreto(), cuerpo.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(firma, esperada):
        raise HTTPException(401, "Sesión inválida.")
    datos: dict[str, object] = json.loads(_de_b64(cuerpo))
    exp = datos.get("exp")
    if not isinstance(exp, int) or exp < time.time():
        raise HTTPException(401, "La sesión venció. Vuelva a ingresar.")
    if datos.get("srv") != settings.bot_servicio:
        raise HTTPException(401, "Esta sesión es de otro servicio.")
    return datos


# ---------------------------------------------------------------------------
# Usuarios autorizados
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usuario:
    correo: str
    nombre: str | None
    rol: Rol
    direccion: str | None


async def buscar_usuario(db: aiosqlite.Connection, correo: str) -> Usuario | None:
    correo = correo.strip().lower()
    cur = await db.execute(
        "SELECT correo, nombre, rol, direccion FROM web_usuarios"
        " WHERE correo = ? AND activo = 1",
        (correo,),
    )
    fila = await cur.fetchone()
    if fila is not None and fila[2] in ROLES_POR_SERVICIO[settings.bot_servicio]:
        return Usuario(fila[0], fila[1], fila[2], fila[3])
    if correo in web_settings.lista_admins:
        return Usuario(correo, None, "admin", None)
    return None


def verificar_google(token: str) -> tuple[str, str | None]:
    """Devuelve (correo, nombre) si el ID token es de Google y del dominio."""
    if not web_settings.google_client_id:
        raise HTTPException(503, "Falta configurar el ingreso con Google.")
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    try:
        datos = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            token, g_requests.Request(), web_settings.google_client_id
        )
    except ValueError:
        raise HTTPException(401, "No se pudo verificar la cuenta de Google.") from None
    correo = str(datos.get("email", "")).lower()
    dominio = web_settings.dominio
    if (
        not datos.get("email_verified")
        or datos.get("hd") != dominio
        or not correo.endswith("@" + dominio)
    ):
        raise HTTPException(403, f"Use su cuenta institucional @{dominio}.")
    return correo, datos.get("name")


def sesion_de(usuario: Usuario) -> str:
    return firmar(
        {
            "tipo": "personal",
            "correo": usuario.correo,
            "rol": usuario.rol,
            "dir": usuario.direccion,
        },
        web_settings.session_horas,
    )


# ---------------------------------------------------------------------------
# Dependencias
# ---------------------------------------------------------------------------


def _token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Ingrese para continuar.")
    return authorization[7:].strip()


async def usuario_actual(
    db: Db, authorization: Annotated[str | None, Header()] = None
) -> Usuario:
    datos = leer(_token(authorization))
    if datos.get("tipo") != "personal":
        raise HTTPException(401, "Ingrese con su cuenta institucional.")
    # Se vuelve a consultar: si un admin retira el permiso, se corta ya.
    usuario = await buscar_usuario(db, str(datos.get("correo", "")))
    if usuario is None:
        raise HTTPException(403, "Su correo ya no está autorizado.")
    return usuario


def requiere(*roles: Rol) -> Callable[..., Awaitable[Usuario]]:
    async def _dep(
        usuario: Annotated[Usuario, Depends(usuario_actual)],
    ) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(403, "Esta herramienta no está habilitada para su rol.")
        return usuario

    return _dep


@dataclass(frozen=True)
class Admitido:
    menor: bool
    acudiente: bool


async def admitido_actual(
    authorization: Annotated[str | None, Header()] = None,
) -> Admitido:
    datos = leer(_token(authorization))
    if datos.get("tipo") != "admitido":
        raise HTTPException(401, "Primero lea y acepte el aviso de datos.")
    return Admitido(bool(datos.get("menor")), bool(datos.get("acudiente")))
