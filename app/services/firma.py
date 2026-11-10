"""Firma del oficio al Consejo y del acta del comité de un programa (fase 3).

Firmar es una acción explícita de una persona autorizada: la administrativa de
la dirección (facultada para firmar en nombre de quien preside el comité) o
admin, siempre de su propia dirección. El modelo no interviene en nada de esto.

Pasos, iguales en el bot (`/firmar <programa>`) y en la web:

1. `preparar`: qué casos entran (los que tienen recomendación del comité),
   cuáles quedan fuera, quién firma, si está su imagen de firma y el radicado
   que se propone. Lo que impide firmar va en `bloqueos`; lo demás, en `avisos`.
2. La persona confirma o corrige el radicado y escribe los datos de la sesión.
3. `firmar`, con confirmación explícita: genera el .docx y el PDF finales
   (`borrador=False`: la imagen de firma la inserta documento._bloque_firma),
   guarda el SHA-256 de cada archivo, registra quién firmó, cuándo, el
   radicado y los casos, y los casos pasan a «en el Consejo» (flujo).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.conexion import Conexion, Fila
from app.core.config import settings
from app.core.programas import PROGRAMAS, Miembro, Programa, integrantes
from app.db import repo
from app.schemas.caso import Caso, Sentido
from app.services import actas_comite, flujo
from app.services.borrador import caso_documento
from app.services.documento import (
    DatosOficio,
    construir_acta,
    construir_oficio,
    fecha_larga,
)
from app.services.firmas import ruta_firma
from app.services.pdf import docx_a_pdf

logger = logging.getLogger(__name__)

# Mz.FCEN.1.065-012-26: prefijo de la dependencia, consecutivo y año.
_RE_RADICADO = re.compile(
    r"^mz\.fcen\.(?P<dep>\d+(?:\.\d+)*)-(?P<num>\d{1,4})-(?P<anio>\d{2})$",
    re.IGNORECASE,
)
_RE_FECHA_DMA = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
_MAX_CAMPO = 200


class FirmaNoPermitida(Exception):
    """No se puede firmar: falta algo, cambió algo o el dato no es válido."""


@dataclass(frozen=True)
class DatosSesion:
    """Lo que el acta y el oficio dicen de la sesión del comité."""

    numero_acta: str
    fecha_sesion: date
    hora: str
    lugar: str


@dataclass(frozen=True)
class Preparacion:
    programa: Programa
    firmante: Miembro | None
    casos: list[Caso]
    pendientes: list[Caso]
    radicado_propuesto: str | None
    tiene_imagen: bool
    bloqueos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    # El número del acta que se propone: el último del programa en el año + 1.
    numero_acta_propuesto: str = ""

    @property
    def caso_ids(self) -> list[int]:
        return [c.id for c in self.casos]


@dataclass(frozen=True)
class ArchivoFirmado:
    documento: str  # «oficio» o «acta»
    formato: str  # «docx» o «pdf»
    ruta: Path
    sha256: str


@dataclass(frozen=True)
class Firma:
    id: int
    direccion: str
    programa: str
    radicado: str
    numero_acta: str
    fecha_sesion: str
    hora: str
    lugar: str
    caso_ids: list[int]
    firmante: str
    firmado_por: str
    rol: str
    canal: str
    con_imagen: bool
    firmado: str
    archivos: list[ArchivoFirmado]

    def archivo(self, documento: str, formato: str) -> ArchivoFirmado | None:
        return next(
            (
                a
                for a in self.archivos
                if a.documento == documento and a.formato == formato
            ),
            None,
        )


def sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def hoy_local() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def firmante_de(programa: Programa) -> Miembro | None:
    """Firma el primer integrante del comité (app/core/programas.py)."""
    if programa.miembros and programa.miembros[0].nombre:
        return programa.miembros[0]
    return None


def programa_de_la_direccion(texto: str, direccion: str) -> Programa | None:
    """El programa por su clave, su nombre o un alias, solo de la dirección."""
    from app.core.programas import normalizar

    buscado = normalizar(texto)
    if not buscado:
        return None
    for programa in PROGRAMAS.values():
        if programa.direccion != direccion:
            continue
        nombres = {programa.clave, normalizar(programa.nombre), *programa.alias}
        if buscado in nombres:
            return programa
    return None


# ---------------------------------------------------------------------------
# Radicado
# ---------------------------------------------------------------------------


def normalizar_radicado(texto: str, hoy: date | None = None) -> str:
    """Mz.FCEN.1.0xx-NNN-AA con el año del oficio; ValueError si no lo es."""
    limpio = "".join(texto.split())
    m = _RE_RADICADO.match(limpio)
    if m is None:
        raise ValueError(
            "El radicado debe tener la forma Mz.FCEN.1.0xx-NNN-AA, "
            "por ejemplo Mz.FCEN.1.065-012-26."
        )
    anio = f"{(hoy or hoy_local()):%y}"
    if m["anio"] != anio:
        raise ValueError(f"El radicado debe ser del año en curso (-{anio}).")
    return f"Mz.FCEN.{m['dep']}-{int(m['num']):03d}-{m['anio']}"


async def _radicados(db: Conexion, direccion: str) -> list[str]:
    cur = await db.execute(
        "SELECT radicado FROM firmas WHERE direccion = ? ORDER BY id",
        (direccion,),
    )
    return [str(r["radicado"]) for r in await cur.fetchall()]


async def proponer_radicado(
    db: Conexion, programa: Programa, hoy: date | None = None
) -> str | None:
    """El siguiente consecutivo de la dirección en el año, con el prefijo del
    programa (o el último que confirmó la dirección). Es solo una propuesta:
    la dirección emite otros oficios por fuera de MemorIA y la persona lo
    confirma o lo corrige al firmar. None si no hay prefijo conocido."""
    anio = f"{(hoy or hoy_local()):%y}"
    ultimo = 0
    prefijo_usado: str | None = None
    for radicado in await _radicados(db, programa.direccion):
        m = _RE_RADICADO.match(radicado)
        if m is None:
            continue
        prefijo_usado = f"Mz.FCEN.{m['dep']}"
        if m["anio"] == anio:
            ultimo = max(ultimo, int(m["num"]))
    prefijo = programa.radicado_prefijo or prefijo_usado
    if prefijo is None:
        return None
    return f"{prefijo}-{ultimo + 1:03d}-{anio}"


async def radicado_usado(db: Conexion, radicado: str) -> bool:
    cur = await db.execute("SELECT 1 FROM firmas WHERE radicado = ?", (radicado,))
    return await cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Datos de la sesión
# ---------------------------------------------------------------------------


def leer_fecha(texto: str) -> date:
    """AAAA-MM-DD o DD/MM/AAAA."""
    limpio = texto.strip()
    m = _RE_FECHA_DMA.match(limpio)
    try:
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
        return date.fromisoformat(limpio)
    except ValueError:
        raise ValueError(
            "La fecha de la sesión debe ser AAAA-MM-DD o DD/MM/AAAA."
        ) from None


def validar_sesion(
    *,
    numero_acta: str,
    fecha_sesion: str | date,
    hora: str,
    lugar: str,
    hoy: date | None = None,
) -> DatosSesion:
    """ValueError con un mensaje para la persona si falta o sobra algo."""
    faltan = [
        nombre
        for nombre, valor in (
            ("número del acta", numero_acta),
            ("fecha de la sesión", str(fecha_sesion)),
            ("hora", hora),
            ("lugar", lugar),
        )
        if not valor.strip()
    ]
    if faltan:
        raise ValueError("Falta: " + ", ".join(faltan) + ".")
    for valor in (numero_acta, hora, lugar):
        if len(valor) > _MAX_CAMPO:
            raise ValueError("Un dato de la sesión es demasiado largo.")
    fecha = fecha_sesion if isinstance(fecha_sesion, date) else leer_fecha(fecha_sesion)
    if fecha > (hoy or hoy_local()):
        raise ValueError("La fecha de la sesión no puede ser posterior a hoy.")
    numero = actas_comite.leer_numero(numero_acta)
    return DatosSesion(
        numero_acta=actas_comite.formato_numero(numero),
        fecha_sesion=fecha,
        hora=" ".join(hora.split()),
        lugar=" ".join(lugar.split()),
    )


# ---------------------------------------------------------------------------
# Preparación (resumen antes de confirmar)
# ---------------------------------------------------------------------------


def _rol_flujo(rol: str) -> str:
    return flujo.ADMIN if rol == flujo.ADMIN else flujo.ADMINISTRATIVA


async def preparar(
    db: Conexion,
    *,
    direccion: str,
    clave: str,
    rol: str = flujo.ADMINISTRATIVA,
    hoy: date | None = None,
) -> Preparacion:
    """Resumen de lo que se va a firmar. No escribe nada."""
    programa = PROGRAMAS.get(clave)
    if programa is None or programa.direccion != direccion:
        raise FirmaNoPermitida("No conozco ese programa en su dirección.")
    del_programa = [
        c
        for c in await repo.casos_listos(db, direccion=direccion)
        if c.programa == clave
    ]
    casos = [
        c
        for c in del_programa
        if c.sentido != Sentido.PENDIENTE and c.extraccion is not None
    ]
    entran = {c.id for c in casos}
    pendientes = [c for c in del_programa if c.id not in entran]
    firmante = firmante_de(programa)
    tiene_imagen = ruta_firma(clave) is not None

    bloqueos: list[str] = []
    if not casos:
        bloqueos.append(
            "No hay casos con recomendación del comité (aprobar o no aprobar)."
        )
    if firmante is None:
        bloqueos.append(
            f"{programa.nombre} no tiene integrantes del comité en "
            "app/core/programas.py: no sé quién firma."
        )
    rol_flujo = _rol_flujo(rol)
    for caso in casos:
        etapa = flujo.Etapa(caso.etapa) if caso.etapa else None
        if etapa != flujo.Etapa.EN_CONSEJO and not flujo.puede(
            flujo.Accion.ENVIAR_CONSEJO, etapa, rol_flujo
        ):
            bloqueos.append(
                f"El caso #{caso.id} está en «{flujo.nombre_etapa(caso.etapa)}» "
                "y no puede ir al Consejo."
            )

    avisos: list[str] = []
    if firmante is not None and not tiene_imagen:
        avisos.append(
            f"Falta la imagen de firma de {firmante.nombre} ({clave}). El oficio "
            "y el acta saldrán con «[falta la imagen de la firma]» en amarillo "
            "(docs/integrantes-y-firmas.md)."
        )
    if pendientes:
        avisos.append(
            "Quedan fuera, sin recomendación del comité o sin ficha leída: "
            + ", ".join(f"#{c.id}" for c in pendientes)
            + "."
        )
    if any(not m.nombre for m in integrantes(programa)):
        avisos.append(
            "Falta el nombre de la representación estudiantil "
            "(REPRESENTANTES_ESTUDIANTILES): el acta lo deja en amarillo."
        )
    if shutil.which(settings.soffice_bin) is None:
        avisos.append("LibreOffice no está disponible: solo saldrá el .docx.")

    anio = (hoy or hoy_local()).year
    numero = await actas_comite.proponer_numero(db, clave, anio)
    return Preparacion(
        numero_acta_propuesto=actas_comite.formato_numero(numero),
        programa=programa,
        firmante=firmante,
        casos=casos,
        pendientes=pendientes,
        radicado_propuesto=await proponer_radicado(db, programa, hoy),
        tiene_imagen=tiene_imagen,
        bloqueos=bloqueos,
        avisos=avisos,
    )


# ---------------------------------------------------------------------------
# Firmar
# ---------------------------------------------------------------------------


def _nombre_archivo(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", texto).strip("_")


async def firmar(
    db: Conexion,
    *,
    direccion: str,
    clave: str,
    radicado: str,
    sesion: DatosSesion,
    caso_ids: list[int],
    persona: str,
    rol: str,
    canal: str,
    hoy: date | None = None,
) -> Firma:
    """Genera los documentos finales y registra la firma. `caso_ids` son los
    que la persona vio en el resumen: si cambiaron, no se firma."""
    hoy = hoy or hoy_local()
    prep = await preparar(db, direccion=direccion, clave=clave, rol=rol, hoy=hoy)
    if prep.bloqueos:
        raise FirmaNoPermitida(prep.bloqueos[0])
    if sorted(caso_ids) != sorted(prep.caso_ids):
        raise FirmaNoPermitida(
            "Los casos del programa cambiaron desde el resumen. Revise de nuevo "
            "antes de firmar."
        )
    try:
        radicado = normalizar_radicado(radicado, hoy)
    except ValueError as exc:
        raise FirmaNoPermitida(str(exc)) from None
    if await radicado_usado(db, radicado):
        raise FirmaNoPermitida(f"El radicado {radicado} ya se usó en otra firma.")
    try:
        numero_acta = actas_comite.leer_numero(sesion.numero_acta)
        await actas_comite.verificar_numero(
            db, prep.programa, numero_acta, sesion.fecha_sesion
        )
    except (ValueError, actas_comite.ActaNoPermitida) as exc:
        raise FirmaNoPermitida(str(exc)) from None
    assert prep.firmante is not None

    programa = prep.programa
    items = [i for c in prep.casos if (i := caso_documento(c, programa)) is not None]
    datos = DatosOficio(
        programa=programa,
        fecha=hoy,
        casos=items,
        radicado=radicado,
        numero_acta=sesion.numero_acta,
        fecha_sesion=fecha_larga(sesion.fecha_sesion),
        elaboro=_iniciales(persona),
        borrador=False,
        hora=sesion.hora,
        lugar=sesion.lugar,
        miembros=integrantes(programa),
    )
    contenidos: dict[str, bytes] = {
        "oficio": construir_oficio(datos, settings.periodo_actual),
        "acta": construir_acta(datos, settings.periodo_actual),
    }

    carpeta = settings.output_dir / "firmados" / f"{hoy:%Y}" / direccion
    carpeta.mkdir(parents=True, exist_ok=True)
    base = _nombre_archivo(f"{radicado}_{programa.nombre}")
    archivos: list[ArchivoFirmado] = []
    escritos: list[Path] = []
    try:
        for documento, docx in contenidos.items():
            nombre = f"{documento.capitalize()}_{base}"
            for formato, contenido in (("docx", docx), ("pdf", await docx_a_pdf(docx))):
                if contenido is None:
                    continue
                ruta = carpeta / f"{nombre}.{formato}"
                try:
                    # Exclusivo: un segundo intento con el mismo radicado no
                    # pisa (ni luego borra) los archivos de la primera firma.
                    with ruta.open("xb") as salida:
                        salida.write(contenido)
                except FileExistsError:
                    raise FirmaNoPermitida(
                        f"Ya existe un documento firmado con el radicado {radicado}."
                    ) from None
                escritos.append(ruta)
                archivos.append(
                    ArchivoFirmado(documento, formato, ruta, sha256(contenido))
                )
        firma_id = await _registrar(
            db,
            direccion=direccion,
            programa=clave,
            radicado=radicado,
            sesion=sesion,
            caso_ids=prep.caso_ids,
            firmante=prep.firmante.nombre,
            persona=persona,
            rol=rol,
            canal=canal,
            con_imagen=prep.tiene_imagen,
            archivos=archivos,
        )
        # El acta del comité queda cerrada con su número; la siguiente empieza
        # con los casos que sigan en el borrador.
        await actas_comite.registrar_cierre(
            db,
            direccion=direccion,
            programa=clave,
            numero=numero_acta,
            fecha_sesion=sesion.fecha_sesion,
            caso_ids=prep.caso_ids,
            persona=persona,
            canal=canal,
            firma_id=firma_id,
        )
        # El oficio firmado es el «oficio del comité al Consejo» de la línea.
        await flujo.enviar_consejo(
            db,
            prep.caso_ids,
            rol=_rol_flujo(rol),
            persona=persona,
            canal=canal,
            detalle=f"Oficio firmado, radicado {radicado}",
            commit=False,
        )
        await db.commit()
    except BaseException:
        await db.rollback()
        for ruta in escritos:
            ruta.unlink(missing_ok=True)
        raise
    firma = await obtener(db, firma_id)
    assert firma is not None
    logger.info(
        "Firma #%s de %s (%s): %s casos", firma.id, clave, radicado, len(caso_ids)
    )
    return firma


def _iniciales(nombre: str | None) -> str:
    partes = [p for p in (nombre or "").split() if p and "@" not in p]
    return "".join(p[0].upper() for p in partes)[:5] or "FCEN"


async def _registrar(
    db: Conexion,
    *,
    direccion: str,
    programa: str,
    radicado: str,
    sesion: DatosSesion,
    caso_ids: list[int],
    firmante: str,
    persona: str,
    rol: str,
    canal: str,
    con_imagen: bool,
    archivos: list[ArchivoFirmado],
) -> int:
    """Sin commit: lo hace firmar junto con el cambio de etapa de los casos."""
    cur = await db.execute(
        "INSERT INTO firmas (direccion, programa, radicado, numero_acta, "
        "fecha_sesion, hora, lugar, caso_ids, firmante, firmado_por, rol, canal, "
        "con_imagen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            direccion,
            programa,
            radicado,
            sesion.numero_acta,
            sesion.fecha_sesion.isoformat(),
            sesion.hora,
            sesion.lugar,
            json.dumps(caso_ids),
            firmante,
            persona,
            rol,
            canal,
            1 if con_imagen else 0,
        ),
    )
    assert cur.lastrowid is not None
    firma_id = int(cur.lastrowid)
    for a in archivos:
        await db.execute(
            "INSERT INTO firma_archivos (firma_id, documento, formato, ruta, sha256) "
            "VALUES (?, ?, ?, ?, ?)",
            (firma_id, a.documento, a.formato, str(a.ruta), a.sha256),
        )
    return firma_id


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


async def _firma(db: Conexion, r: Fila) -> Firma:
    cur = await db.execute(
        "SELECT documento, formato, ruta, sha256 FROM firma_archivos "
        "WHERE firma_id = ? ORDER BY id",
        (int(r["id"]),),
    )
    archivos = [
        ArchivoFirmado(
            str(a["documento"]), str(a["formato"]), Path(a["ruta"]), str(a["sha256"])
        )
        for a in await cur.fetchall()
    ]
    return Firma(
        id=int(r["id"]),
        direccion=str(r["direccion"]),
        programa=str(r["programa"]),
        radicado=str(r["radicado"]),
        numero_acta=str(r["numero_acta"]),
        fecha_sesion=str(r["fecha_sesion"]),
        hora=str(r["hora"]),
        lugar=str(r["lugar"]),
        caso_ids=[int(i) for i in json.loads(r["caso_ids"])],
        firmante=str(r["firmante"]),
        firmado_por=str(r["firmado_por"]),
        rol=str(r["rol"]),
        canal=str(r["canal"]),
        con_imagen=bool(r["con_imagen"]),
        firmado=str(r["firmado"] or ""),
        archivos=archivos,
    )


async def obtener(db: Conexion, firma_id: int) -> Firma | None:
    cur = await db.execute("SELECT * FROM firmas WHERE id = ?", (firma_id,))
    r = await cur.fetchone()
    return await _firma(db, r) if r else None


async def de_la_direccion(
    db: Conexion, direccion: str, limite: int = 50
) -> list[Firma]:
    cur = await db.execute(
        "SELECT * FROM firmas WHERE direccion = ? ORDER BY id DESC LIMIT ?",
        (direccion, limite),
    )
    return [await _firma(db, r) for r in await cur.fetchall()]


def leer_verificado(archivo: ArchivoFirmado) -> bytes:
    """El archivo firmado, solo si su SHA-256 es el registrado al firmar."""
    contenido = archivo.ruta.read_bytes()
    if sha256(contenido) != archivo.sha256:
        raise FirmaNoPermitida(
            f"El archivo {archivo.ruta.name} no coincide con el que se firmó."
        )
    return contenido


# ---------------------------------------------------------------------------
# Datos en espera de confirmación (bot)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pendiente:
    programa: str
    radicado: str
    sesion: DatosSesion
    caso_ids: list[int]


async def guardar_pendiente(db: Conexion, chat_id: int, p: Pendiente) -> None:
    await db.execute(
        """
        INSERT INTO firmas_pendientes (chat_id, programa, radicado, numero_acta,
            fecha_sesion, hora, lugar, caso_ids)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            programa = excluded.programa,
            radicado = excluded.radicado,
            numero_acta = excluded.numero_acta,
            fecha_sesion = excluded.fecha_sesion,
            hora = excluded.hora,
            lugar = excluded.lugar,
            caso_ids = excluded.caso_ids,
            creado = CURRENT_TIMESTAMP
        """,
        (
            chat_id,
            p.programa,
            p.radicado,
            p.sesion.numero_acta,
            p.sesion.fecha_sesion.isoformat(),
            p.sesion.hora,
            p.sesion.lugar,
            json.dumps(p.caso_ids),
        ),
    )
    await db.commit()


async def leer_pendiente(db: Conexion, chat_id: int) -> Pendiente | None:
    cur = await db.execute(
        "SELECT * FROM firmas_pendientes WHERE chat_id = ?", (chat_id,)
    )
    r = await cur.fetchone()
    if r is None:
        return None
    return Pendiente(
        programa=str(r["programa"]),
        radicado=str(r["radicado"]),
        sesion=DatosSesion(
            numero_acta=str(r["numero_acta"]),
            fecha_sesion=date.fromisoformat(str(r["fecha_sesion"])),
            hora=str(r["hora"]),
            lugar=str(r["lugar"]),
        ),
        caso_ids=[int(i) for i in json.loads(r["caso_ids"])],
    )


async def borrar_pendiente(db: Conexion, chat_id: int) -> None:
    await db.execute("DELETE FROM firmas_pendientes WHERE chat_id = ?", (chat_id,))
    await db.commit()
