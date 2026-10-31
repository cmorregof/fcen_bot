"""Cliente mínimo de Google Drive (API v3 por HTTP, sin librerías de Google).

Usa OAuth con el refresh token de una cuenta @unal.edu.co y el alcance
`drive.file`: la aplicación solo ve las carpetas y archivos que ella misma
creó. Por eso la carpeta raíz (DRIVE_CARPETA_ID) la crea
`scripts/drive_autorizar.py` con la misma autorización. Ver
docs/respaldo-drive.md.

Sin las cuatro variables DRIVE_*, `obtener()` devuelve None y nada se sube.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings

ALCANCE = "https://www.googleapis.com/auth/drive.file"
URL_TOKEN = "https://oauth2.googleapis.com/token"
_API = "https://www.googleapis.com/drive/v3/files"
_SUBIDA = "https://www.googleapis.com/upload/drive/v3/files"
MIME_CARPETA = "application/vnd.google-apps.folder"
# Unidades compartidas: hoy no se usan, pero así la carpeta puede vivir en una
# de la Vicedecanatura sin cambiar el código.
_TODAS = {"supportsAllDrives": "true"}


class ErrorDrive(RuntimeError):
    """Drive respondió con un error o no se pudo conectar."""


@dataclass(frozen=True)
class ArchivoDrive:
    id: str
    nombre: str
    carpeta: bool = False


class ClienteDrive(Protocol):
    """Lo poco que MemorIA necesita de Drive. Las pruebas usan uno falso."""

    async def listar(self, padre: str) -> list[ArchivoDrive]: ...

    async def crear_carpeta(self, nombre: str, padre: str) -> str: ...

    async def subir(
        self, nombre: str, padre: str, contenido: bytes, mime: str
    ) -> str: ...

    async def reemplazar(
        self, archivo_id: str, contenido: bytes, mime: str
    ) -> None: ...

    async def descargar(self, archivo_id: str) -> bytes: ...

    async def a_papelera(self, archivo_id: str) -> None: ...


def configurado() -> bool:
    """Las cuatro credenciales presentes y fuera del entorno de práctica."""
    return bool(
        settings.drive_client_id
        and settings.drive_client_secret
        and settings.drive_refresh_token
        and settings.drive_carpeta_id
        and not settings.memoria_practica
    )


def obtener() -> ClienteDrive | None:
    if not configurado():
        return None
    return ClienteDriveHttp(
        settings.drive_client_id,
        settings.drive_client_secret,
        settings.drive_refresh_token,
    )


async def carpeta(cliente: ClienteDrive, padre: str, ruta: list[str]) -> str:
    """Id de la carpeta `padre/ruta[0]/ruta[1]/...`; crea las que falten."""
    actual = padre
    for nombre in ruta:
        existente = next(
            (
                a
                for a in await cliente.listar(actual)
                if a.carpeta and a.nombre == nombre
            ),
            None,
        )
        actual = (
            existente.id if existente else await cliente.crear_carpeta(nombre, actual)
        )
    return actual


class ClienteDriveHttp:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        timeout: float = 120.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timeout = timeout
        self._token = ""
        self._vence = 0.0

    async def _acceso(self, http: httpx.AsyncClient) -> dict[str, str]:
        if not self._token or time.monotonic() > self._vence:
            r = await http.post(
                URL_TOKEN,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                },
            )
            if r.status_code != 200:
                # El cuerpo trae el motivo (invalid_grant, …), nunca el token.
                raise ErrorDrive(f"Google no renovó el acceso: {r.text[:300]}")
            datos = r.json()
            self._token = str(datos["access_token"])
            self._vence = time.monotonic() + int(datos.get("expires_in", 3600)) - 60
        return {"Authorization": f"Bearer {self._token}"}

    async def _pedir(
        self,
        metodo: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json: object = None,
        contenido: bytes | None = None,
        cabeceras: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            h = {**await self._acceso(http), **(cabeceras or {})}
            try:
                r = await http.request(
                    metodo,
                    url,
                    params={**_TODAS, **(params or {})},
                    json=json,
                    content=contenido,
                    headers=h,
                )
            except httpx.HTTPError as exc:
                raise ErrorDrive(f"Sin conexión con Drive: {exc}") from exc
        if r.status_code >= 400:
            raise ErrorDrive(f"Drive respondió {r.status_code}: {r.text[:300]}")
        return r

    async def listar(self, padre: str) -> list[ArchivoDrive]:
        archivos: list[ArchivoDrive] = []
        pagina = ""
        while True:
            params = {
                "q": f"'{padre}' in parents and trashed = false",
                "fields": "nextPageToken, files(id, name, mimeType)",
                "pageSize": "1000",
                "includeItemsFromAllDrives": "true",
            }
            if pagina:
                params["pageToken"] = pagina
            datos = (await self._pedir("GET", _API, params=params)).json()
            archivos += [
                ArchivoDrive(f["id"], f["name"], f["mimeType"] == MIME_CARPETA)
                for f in datos.get("files", [])
            ]
            pagina = datos.get("nextPageToken", "")
            if not pagina:
                return archivos

    async def crear_carpeta(self, nombre: str, padre: str) -> str:
        r = await self._pedir(
            "POST",
            _API,
            params={"fields": "id"},
            json={"name": nombre, "mimeType": MIME_CARPETA, "parents": [padre]},
        )
        return str(r.json()["id"])

    async def _subida_reanudable(
        self,
        metodo: str,
        url: str,
        metadatos: dict[str, object],
        contenido: bytes,
        mime: str,
    ) -> str:
        # Reanudable en un solo PUT: sirve igual para 10 kB que para 200 MB.
        inicio = await self._pedir(
            metodo,
            url,
            params={"uploadType": "resumable", "fields": "id"},
            json=metadatos,
            cabeceras={"X-Upload-Content-Type": mime},
        )
        destino = inicio.headers["Location"]
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            try:
                r = await http.put(
                    destino, content=contenido, headers={"Content-Type": mime}
                )
            except httpx.HTTPError as exc:
                raise ErrorDrive(f"Sin conexión con Drive: {exc}") from exc
        if r.status_code >= 400:
            raise ErrorDrive(f"Drive respondió {r.status_code}: {r.text[:300]}")
        return str(r.json()["id"])

    async def subir(self, nombre: str, padre: str, contenido: bytes, mime: str) -> str:
        return await self._subida_reanudable(
            "POST", _SUBIDA, {"name": nombre, "parents": [padre]}, contenido, mime
        )

    async def reemplazar(self, archivo_id: str, contenido: bytes, mime: str) -> None:
        await self._subida_reanudable(
            "PATCH", f"{_SUBIDA}/{archivo_id}", {}, contenido, mime
        )

    async def descargar(self, archivo_id: str) -> bytes:
        r = await self._pedir("GET", f"{_API}/{archivo_id}", params={"alt": "media"})
        return r.content

    async def a_papelera(self, archivo_id: str) -> None:
        # Papelera y no borrado: Drive la vacía a los 30 días y se puede
        # recuperar mientras tanto.
        await self._pedir("PATCH", f"{_API}/{archivo_id}", json={"trashed": True})
