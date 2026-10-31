"""Rutas comunes a todos los servicios: sesión y usuarios autorizados."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import practica
from app.api.web import auth
from app.api.web.auth import Db, Rol, Usuario
from app.api.web.config import web_settings
from app.core.config import settings
from app.core.programas import DIRECCIONES

router = APIRouter()


class SesionGoogle(BaseModel):
    credencial: str


class SesionDev(BaseModel):
    correo: str


class RespuestaSesion(BaseModel):
    token: str
    servicio: str
    correo: str
    nombre: str | None
    rol: str
    direccion: str | None


def _respuesta(usuario: Usuario, nombre: str | None) -> RespuestaSesion:
    return RespuestaSesion(
        token=auth.sesion_de(usuario),
        servicio=settings.bot_servicio,
        correo=usuario.correo,
        nombre=usuario.nombre or nombre,
        rol=usuario.rol,
        direccion=usuario.direccion,
    )


@router.post("/sesion")
async def sesion(cuerpo: SesionGoogle, db: Db) -> RespuestaSesion:
    correo, nombre = auth.verificar_google(cuerpo.credencial)
    usuario = await auth.buscar_usuario(db, correo)
    if usuario is None:
        raise HTTPException(403, "Su correo no está autorizado en este servicio.")
    return _respuesta(usuario, nombre)


@router.post("/sesion/dev")
async def sesion_dev(cuerpo: SesionDev, db: Db) -> RespuestaSesion:
    if not web_settings.dev_permitido:
        raise HTTPException(404, "No disponible.")
    usuario = await auth.buscar_usuario(db, cuerpo.correo)
    if usuario is None:
        raise HTTPException(403, "Su correo no está autorizado en este servicio.")
    return _respuesta(usuario, None)


@router.get("/entorno")
async def entorno() -> dict[str, object]:
    """Público: la web lo usa para mostrar el banner del entorno de práctica."""
    return {"servicio": settings.bot_servicio, "practica": settings.memoria_practica}


@router.get("/yo")
async def yo(
    usuario: Annotated[Usuario, Depends(auth.usuario_actual)],
) -> dict[str, object]:
    return {
        "servicio": settings.bot_servicio,
        "correo": usuario.correo,
        "rol": usuario.rol,
        "direccion": usuario.direccion,
    }


# ---------------------------------------------------------------------------
# Usuarios (solo admin)
# ---------------------------------------------------------------------------


class NuevoUsuario(BaseModel):
    correo: str
    nombre: str | None = None
    rol: Rol
    direccion: str | None = None


_Admin = Annotated[Usuario, Depends(auth.requiere("admin"))]


@router.get("/usuarios")
async def listar_usuarios(_: _Admin, db: Db) -> dict[str, object]:
    cur = await db.execute(
        "SELECT correo, nombre, rol, direccion, activo FROM web_usuarios ORDER BY correo"
    )
    return {
        "roles": list(auth.ROLES_POR_SERVICIO[settings.bot_servicio]),
        "direcciones": {k: d.nombre for k, d in DIRECCIONES.items()},
        "usuarios": [
            {
                "correo": f[0],
                "nombre": f[1],
                "rol": f[2],
                "direccion": f[3],
                "activo": bool(f[4]),
            }
            for f in await cur.fetchall()
        ],
    }


@router.post("/usuarios")
async def guardar_usuario(cuerpo: NuevoUsuario, _: _Admin, db: Db) -> dict[str, bool]:
    correo = cuerpo.correo.strip().lower()
    if not correo.endswith("@" + web_settings.dominio):
        raise HTTPException(400, f"El correo debe ser @{web_settings.dominio}.")
    if cuerpo.rol not in auth.ROLES_POR_SERVICIO[settings.bot_servicio]:
        raise HTTPException(400, "Ese rol no existe en este servicio.")
    if cuerpo.rol in ("administrativa", "comite"):
        if cuerpo.direccion not in DIRECCIONES:
            raise HTTPException(400, "Indique el área curricular.")
    else:
        cuerpo.direccion = None
    await db.execute(
        "INSERT INTO web_usuarios (correo, nombre, rol, direccion, activo)"
        " VALUES (?, ?, ?, ?, 1) ON CONFLICT(correo) DO UPDATE SET"
        " nombre=excluded.nombre, rol=excluded.rol,"
        " direccion=excluded.direccion, activo=1",
        (correo, cuerpo.nombre, cuerpo.rol, cuerpo.direccion),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/usuarios/{correo}")
async def retirar_usuario(correo: str, _: _Admin, db: Db) -> dict[str, bool]:
    await db.execute(
        "UPDATE web_usuarios SET activo = 0 WHERE correo = ?", (correo.lower(),)
    )
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Entorno de práctica (solo admin, solo con MEMORIA_PRACTICA=true)
# ---------------------------------------------------------------------------


@router.post("/practica/reiniciar")
async def reiniciar_practica(_: _Admin) -> dict[str, object]:
    """Vuelve a cargar los datos ficticios de este servicio."""
    if not settings.memoria_practica:
        raise HTTPException(404, "No disponible.")
    return await practica.reiniciar()
