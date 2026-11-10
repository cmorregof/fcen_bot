"""Adjuntos de un caso: pantallazos, formatos de solicitud y anexos.

Se aceptan PDF, Word (.docx) e imágenes JPG, PNG o WEBP, en la web y en el
bot. El tipo se comprueba por el contenido del archivo, no solo por su
nombre. Qué pasa con cada uno:

- imagen: pantallazo del SIA o de la solicitud; el modelo lo lee.
- formato: formato de solicitud en PDF o Word («FORMATO DE …»); su texto se
  lee aquí, sin el modelo, y entra al caso como un correo pegado
  (app/services/formatos.py).
- pendiente: PDF escaneado; la administrativa dice si es el formato.
- anexo: cualquier otro soporte (certificado, carta…). Se guarda y se lista
  en el caso; al modelo solo le llega su nombre, nunca el contenido.

Ninguno decide nada: el modelo solo extrae datos.

Borrar un adjunto lo elimina del almacenamiento y de la base (puede ser un
dato personal de otra persona) y deja un evento en `caso_eventos` sin el
nombre ni el contenido.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.conexion import Conexion
from app.core.config import settings
from app.db import repo
from app.schemas.caso import Caso
from app.services import flujo, formatos

# Extensión → nombre legible. Es la lista completa de tipos permitidos.
TIPOS: dict[str, str] = {
    ".pdf": "PDF",
    ".docx": "Word",
    ".jpg": "imagen JPG",
    ".png": "imagen PNG",
    ".webp": "imagen WEBP",
}
IMAGENES = frozenset({".jpg", ".png", ".webp"})
MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
TEXTO_PERMITIDOS = "PDF, Word (.docx) o imágenes JPG, PNG o WEBP"

MAX_IMAGEN = 10 * 1024 * 1024
MAX_DOCUMENTO = formatos.MAX_BYTES  # 20 MB, el límite de descarga de Telegram
MAX_POR_CASO = 30

NOMBRE_TIPO = {
    "imagen": "Pantallazo",
    "formato": "Formato de solicitud",
    "pendiente": "PDF escaneado sin clasificar",
    "anexo": "Anexo",
}


class AdjuntoInvalido(ValueError):
    """El archivo no se puede adjuntar; el mensaje es para la persona."""


def detectar(datos: bytes) -> str | None:
    """La extensión según el contenido, o None si no es un tipo permitido."""
    if datos.startswith(b"%PDF-"):
        return ".pdf"
    if datos.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return ".webp"
    if datos.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                if "word/document.xml" in z.namelist():
                    return ".docx"
        except zipfile.BadZipFile:
            return None
    return None


def validar(datos: bytes, nombre: str) -> str:
    """Comprueba tipo y tamaño. Devuelve la extensión o lanza AdjuntoInvalido."""
    ext = detectar(datos)
    if ext is None:
        raise AdjuntoInvalido(
            f"«{nombre}» no se puede adjuntar: solo se aceptan {TEXTO_PERMITIDOS}."
        )
    limite = MAX_IMAGEN if ext in IMAGENES else MAX_DOCUMENTO
    if len(datos) > limite:
        raise AdjuntoInvalido(f"«{nombre}» pesa más de {limite // (1024 * 1024)} MB.")
    return ext


def permitido_por_nombre(nombre: str) -> bool:
    """Para descartar antes de descargar (bot): por la extensión del nombre."""
    ext = Path(nombre).suffix.lower().replace(".jpeg", ".jpg")
    return ext in TIPOS


@dataclass(frozen=True)
class Agregado:
    tipo: str  # imagen, formato, pendiente o anexo
    unico: str
    nombre: str
    nuevo: bool  # False si ya estaba en el caso


def unico_de(datos: bytes) -> str:
    return "web_" + hashlib.sha256(datos).hexdigest()[:24]


async def cupo(db: Conexion, caso_id: int) -> int:
    """Cuántos adjuntos más admite el caso."""
    return MAX_POR_CASO - len(await repo.archivos_de(db, caso_id, derivados=False))


async def agregar(
    db: Conexion,
    caso_id: int,
    datos: bytes,
    nombre: str,
    *,
    unico: str | None = None,
) -> Agregado:
    """Valida, guarda y clasifica un adjunto. `unico` evita duplicados (en
    Telegram, el file_unique_id; en la web, un hash del contenido)."""
    ext = validar(datos, nombre)
    unico = unico or unico_de(datos)
    if await repo.get_archivo(db, caso_id, unico) is not None:
        return Agregado("duplicado", unico, nombre, nuevo=False)
    if await cupo(db, caso_id) <= 0:
        raise AdjuntoInvalido(f"El caso ya tiene {MAX_POR_CASO} adjuntos.")
    carpeta = settings.media_dir / str(caso_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    tipo = "imagen"
    texto = ""
    if ext not in IMAGENES:
        texto = await formatos.texto_de_archivo(datos, ext)
        if formatos.es_formato(texto):
            tipo = "formato"
        elif ext == ".pdf" and not texto.strip():
            # Escaneado: no se puede saber si es el formato o un soporte.
            tipo = "pendiente"
        else:
            tipo = "anexo"
    ruta = carpeta / (
        f"_pendiente_{unico}{ext}" if tipo == "pendiente" else f"{unico}{ext}"
    )
    ruta.write_bytes(datos)
    nuevo = await repo.agregar_archivo(
        db,
        caso_id,
        tipo=tipo,
        ruta=str(ruta),
        nombre=nombre,
        file_unique_id=unico,
        bytes_=len(datos),
    )
    if nuevo and tipo == "formato":
        await repo.agregar_texto(db, caso_id, _bloque_formato(nombre, texto))
    return Agregado(tipo, unico, nombre, nuevo)


def _bloque_formato(nombre: str, texto: str) -> str:
    return f"--- Formato adjunto: {nombre} ---\n{texto}"


async def resolver_pendiente(
    db: Conexion, caso_id: int, unico: str, *, es_formato: bool
) -> str | None:
    """La administrativa dijo si el PDF escaneado es el formato. Si lo es, sus
    páginas se vuelven pantallazos; si no, queda como anexo. Devuelve el
    mensaje para ella, o None si ya no estaba pendiente."""
    archivo = await repo.get_archivo(db, caso_id, unico)
    if archivo is None or archivo[0] != "pendiente" or not archivo[1]:
        return None
    pendiente = Path(archivo[1])
    pdf = pendiente.with_name(pendiente.name.removeprefix("_pendiente_"))
    if pendiente.exists():
        pendiente.replace(pdf)
    if not es_formato:
        await repo.set_tipo_archivo(db, caso_id, unico, tipo="anexo", ruta=str(pdf))
        return f"Queda como anexo del caso #{caso_id}; no se envía al modelo."
    paginas = (
        await formatos.paginas_pdf(pdf, pdf.parent, f"formato_{unico}_")
        if pdf.exists()
        else []
    )
    for i, pagina in enumerate(paginas, 1):
        await repo.agregar_archivo(
            db,
            caso_id,
            tipo="imagen",
            ruta=str(pagina),
            nombre=None,
            file_unique_id=f"{unico}_p{i}",
        )
    await repo.set_tipo_archivo(db, caso_id, unico, tipo="formato", ruta=str(pdf))
    if not paginas:
        return "No pude convertir el PDF; envíe fotos o pantallazos del formato."
    return f"Agregué {len(paginas)} página(s) del formato al caso #{caso_id}."


# ---------------------------------------------------------------------------
# Listar y borrar
# ---------------------------------------------------------------------------


def _ext(archivo: repo.Archivo) -> str:
    return Path(archivo.ruta).suffix.lower() if archivo.ruta else ""


def describir(archivo: repo.Archivo, n: int) -> dict[str, object]:
    """Lo que la ficha muestra de un adjunto."""
    return {
        "id": archivo.id,
        "tipo": archivo.tipo,
        "tipo_texto": NOMBRE_TIPO.get(archivo.tipo, "Anexo"),
        "nombre": archivo.nombre or f"Pantallazo {n}",
        "formato": TIPOS.get(_ext(archivo), ""),
        "bytes": archivo.bytes_,
        "creado": archivo.creado,
        # Ya entró a una lectura del modelo (imagen o texto del formato) o
        # su nombre se le mencionó (anexo).
        "leido": archivo.leido is not None,
        # Se puede descargar si el archivo sigue guardado.
        "descargable": bool(archivo.ruta and Path(archivo.ruta).exists()),
    }


async def listar(db: Conexion, caso_id: int) -> list[dict[str, object]]:
    archivos = await repo.archivos_de(db, caso_id, derivados=False)
    return [describir(a, i) for i, a in enumerate(archivos, 1)]


@dataclass(frozen=True)
class Borrado:
    tipo: str
    leido: bool
    aviso: str | None


def _quitar_texto(texto: str, bloque: str) -> str:
    for candidato in ("\n" + bloque, bloque + "\n", bloque):
        if candidato in texto:
            return texto.replace(candidato, "", 1)
    return texto


async def borrar(
    db: Conexion,
    caso: Caso,
    archivo_id: int,
    *,
    rol: str,
    persona: str | None,
    canal: str,
) -> Borrado:
    """Borra el adjunto del disco y de la base, con sus páginas derivadas y,
    si era un formato, su texto en el caso. Registra el evento sin el nombre
    del archivo. Lanza KeyError si el adjunto no es de ese caso."""
    archivo = await repo.get_archivo_por_id(db, caso.id, archivo_id)
    if archivo is None:
        raise KeyError(archivo_id)
    todos = await repo.archivos_de(db, caso.id, derivados=True)
    paginas = [
        a
        for a in todos
        if a.file_unique_id
        and a.file_unique_id.startswith(f"{archivo.file_unique_id}_p")
    ]
    leido = archivo.leido is not None or any(p.leido for p in paginas)
    texto_restante = False
    if archivo.tipo == "formato":
        ruta = Path(archivo.ruta) if archivo.ruta else None
        if ruta and ruta.exists() and ruta.suffix.lower() in (".pdf", ".docx"):
            texto = await formatos.texto_de_archivo(
                ruta.read_bytes(), ruta.suffix.lower()
            )
            bloque = _bloque_formato(archivo.nombre or "archivo", texto)
            nuevo = _quitar_texto(caso.texto, bloque)
            texto_restante = nuevo == caso.texto and bool(texto.strip())
            if nuevo != caso.texto:
                await repo.set_texto(db, caso.id, nuevo)
        elif f"--- Formato adjunto: {archivo.nombre} ---" in caso.texto:
            texto_restante = True
    for a in [archivo, *paginas]:
        if a.ruta:
            Path(a.ruta).unlink(missing_ok=True)
        await repo.borrar_archivo(db, caso.id, a.id)
    formato = TIPOS.get(_ext(archivo), "archivo")
    detalle = f"{NOMBRE_TIPO.get(archivo.tipo, 'Anexo')} ({formato})"
    if paginas:
        detalle += f" con {len(paginas)} página(s) convertidas"
    if leido:
        detalle += "; ya se había usado en la lectura del caso"
    await flujo.registrar_quitar_adjunto(
        db, caso.id, rol=rol, persona=persona, canal=canal, detalle=detalle
    )
    await db.commit()
    avisos: list[str] = []
    if leido and caso.extraccion is not None:
        avisos.append(
            "Ese archivo ya se había usado al leer el caso: revise los datos "
            "leídos o vuelva a leer el caso."
        )
    if texto_restante:
        avisos.append(
            "El texto de ese formato sigue en el texto del caso: no pude "
            "ubicarlo para quitarlo."
        )
    return Borrado(archivo.tipo, leido, " ".join(avisos) or None)
