"""Actas del comité asesor, con su consecutivo.

Cada semana el comité se reúne y su acta se cierra. En pregrado hay un comité
por programa; una dirección con comité único (los posgrados de Ciencias
Exactas) tiene una sola acta para todos sus programas, con la clave de la
dirección en `actas_comite.programa` (app/core/programas.py, `comite_de`). El acta
abierta no se guarda como fila: son los casos del programa que siguen en el
borrador (repo.casos_listos). Al cerrarla, por firma (firma.firmar) o sin firma
en MemorIA (`cerrar_sin_firma`, cuando el acta se firmó por fuera), queda una
fila en `actas_comite` con su número, el año, la fecha de la sesión y los casos
(`acta_comite_casos`); esos casos salen del borrador y los nuevos entran a la
siguiente.

El número siguiente es una propuesta (el último del comité en el año + 1, o
el siguiente a `ultima_acta` si el comité numeró actas por fuera de MemorIA).
La persona lo confirma o lo corrige al cerrar: la dirección puede haber
numerado otras actas por fuera de MemorIA. Un número ya cerrado no se repite.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.core.conexion import Conexion, Fila
from app.core.config import settings
from app.core.programas import Programa, comite_de, integrantes, programas_del_comite
from app.db import repo
from app.schemas.caso import Caso, EstadoCaso, Sentido
from app.services import flujo
from app.services.borrador import caso_documento
from app.services.documento import DatosOficio, construir_acta, fecha_larga

FIRMADA = "firmada"  # cerrada con la firma en MemorIA (firma.firmar)
CERRADA = "cerrada"  # cerrada sin firma en MemorIA (firmada por fuera)

# «019», «19», «Acta 019», «No. 19», «Acta No. 019».
_RE_NUMERO = re.compile(r"^(?:acta\s*)?(?:n[o°º]\.?\s*)?(\d{1,4})$", re.IGNORECASE)


class ActaNoPermitida(Exception):
    """No se puede cerrar el acta: falta algo, cambió algo o el número ya existe."""


@dataclass(frozen=True)
class ActaComite:
    id: int
    direccion: str
    programa: str
    anio: int | None
    numero: int | None  # None: acta histórica, anterior al consecutivo
    fecha_sesion: str | None
    estado: str
    firma_id: int | None
    cerrada_por: str | None
    canal: str
    cerrada: str
    caso_ids: list[int]
    docx_ruta: Path | None
    docx_sha256: str | None

    @property
    def numero_texto(self) -> str | None:
        return formato_numero(self.numero) if self.numero is not None else None


def formato_numero(numero: int) -> str:
    return f"{numero:03d}"


def leer_numero(texto: str) -> int:
    """El número del acta escrito por la persona; ValueError si no lo es."""
    m = _RE_NUMERO.match(" ".join(texto.split()))
    if m is None or int(m[1]) == 0:
        raise ValueError("El número del acta debe ser un número, por ejemplo 019.")
    return int(m[1])


async def ultimo_numero(db: Conexion, programa: str, anio: int) -> int:
    cur = await db.execute(
        "SELECT MAX(numero) AS n FROM actas_comite WHERE programa = ? AND anio = ?",
        (programa, anio),
    )
    r = await cur.fetchone()
    return int(r["n"]) if r and r["n"] is not None else 0


def numero_externo(programa: str, anio: int) -> int:
    """La última acta del año numerada por fuera de MemorIA (programas.py,
    `ultima_acta`); 0 si no hay."""
    comite = comite_de(programa)
    ultima = comite.ultima_acta if comite is not None else None
    return ultima.numero if ultima is not None and ultima.anio == anio else 0


async def proponer_numero(db: Conexion, programa: str, anio: int) -> int:
    """El siguiente del comité en el año. Solo una propuesta."""
    ultimo = await ultimo_numero(db, programa, anio)
    return max(ultimo, numero_externo(programa, anio)) + 1


async def numero_usado(db: Conexion, programa: str, anio: int, numero: int) -> bool:
    cur = await db.execute(
        "SELECT 1 FROM actas_comite WHERE programa = ? AND anio = ? AND numero = ?",
        (programa, anio, numero),
    )
    return await cur.fetchone() is not None


async def verificar_numero(
    db: Conexion, programa: Programa, numero: int, fecha_sesion: date
) -> None:
    externo = numero_externo(programa.clave, fecha_sesion.year)
    if numero <= externo:
        raise ActaNoPermitida(
            f"La última acta de {fecha_sesion.year} del {programa.comite} es la "
            f"{formato_numero(externo)}, numerada por fuera de MemorIA. Use un "
            "número mayor."
        )
    if await numero_usado(db, programa.clave, fecha_sesion.year, numero):
        raise ActaNoPermitida(
            f"El acta {formato_numero(numero)} de {fecha_sesion.year} de "
            f"{programa.nombre} ya está cerrada. Use otro número."
        )


async def registrar_cierre(
    db: Conexion,
    *,
    direccion: str,
    programa: str,
    numero: int,
    fecha_sesion: date,
    caso_ids: list[int],
    persona: str,
    canal: str,
    firma_id: int | None = None,
    docx_ruta: Path | None = None,
    docx_sha256: str | None = None,
) -> int:
    """Guarda el acta cerrada y sus casos. Sin commit: lo hace quien cierra,
    junto con el paso de los casos al Consejo."""
    if not caso_ids:
        raise ActaNoPermitida("El acta no tiene casos.")
    cur = await db.execute(
        "INSERT INTO actas_comite (direccion, programa, anio, numero, fecha_sesion, "
        "estado, firma_id, cerrada_por, canal, docx_ruta, docx_sha256) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            direccion,
            programa,
            fecha_sesion.year,
            numero,
            fecha_sesion.isoformat(),
            FIRMADA if firma_id is not None else CERRADA,
            firma_id,
            persona,
            canal,
            str(docx_ruta) if docx_ruta else None,
            docx_sha256,
        ),
    )
    assert cur.lastrowid is not None
    acta_id = int(cur.lastrowid)
    await _ligar(db, acta_id, caso_ids)
    return acta_id


async def _ligar(db: Conexion, acta_id: int, caso_ids: list[int]) -> None:
    for caso_id in caso_ids:
        await db.execute(
            "INSERT INTO acta_comite_casos (acta_id, caso_id) VALUES (?, ?) "
            "ON CONFLICT (acta_id, caso_id) DO NOTHING",
            (acta_id, caso_id),
        )


# ---------------------------------------------------------------------------
# Acta abierta y cierre sin firma
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActaAbierta:
    programa: Programa
    anio: int
    numero_propuesto: int
    casos: list[Caso]  # con recomendación del comité y ficha leída: entran
    pendientes: list[Caso]  # siguen en el borrador y pasan a la siguiente

    @property
    def caso_ids(self) -> list[int]:
        return [c.id for c in self.casos]


async def abierta(
    db: Conexion, *, direccion: str, clave: str, hoy: date
) -> ActaAbierta:
    """El acta en curso del comité (`clave`: la de un programa o la del comité
    único; en una dirección con comité único, cualquiera de sus programas
    lleva al acta de todo el comité). No escribe nada."""
    programa = comite_de(clave)
    if programa is None or programa.direccion != direccion:
        raise ActaNoPermitida("No conozco ese programa en su dirección.")
    claves = programas_del_comite(programa)
    del_programa = [
        c
        for c in await repo.casos_listos(db, direccion=direccion)
        if c.programa in claves
    ]
    casos = [
        c
        for c in del_programa
        if c.sentido != Sentido.PENDIENTE and c.extraccion is not None
    ]
    entran = {c.id for c in casos}
    return ActaAbierta(
        programa=programa,
        anio=hoy.year,
        numero_propuesto=await proponer_numero(db, programa.clave, hoy.year),
        casos=casos,
        pendientes=[c for c in del_programa if c.id not in entran],
    )


async def cerrar_sin_firma(
    db: Conexion,
    *,
    direccion: str,
    clave: str,
    numero: int,
    fecha_sesion: date,
    caso_ids: list[int],
    persona: str,
    rol: str,
    canal: str,
    hoy: date,
) -> ActaComite:
    """Cierra el acta en curso cuando se firmó por fuera de MemorIA: guarda
    el número, la fecha y el Word del acta (sin imagen de firma), y los casos
    pasan al Consejo. `caso_ids` son los que la persona vio: si cambiaron, no
    se cierra."""
    acta = await abierta(db, direccion=direccion, clave=clave, hoy=hoy)
    if not acta.casos:
        raise ActaNoPermitida(
            "No hay casos con recomendación del comité (aprobar o no aprobar)."
        )
    if sorted(caso_ids) != sorted(acta.caso_ids):
        raise ActaNoPermitida(
            "Los casos del programa cambiaron desde el resumen. Revise de nuevo."
        )
    if fecha_sesion > hoy:
        raise ActaNoPermitida("La fecha de la sesión no puede ser posterior a hoy.")
    programa = acta.programa
    clave = programa.clave
    await verificar_numero(db, programa, numero, fecha_sesion)

    items = [i for c in acta.casos if (i := caso_documento(c, programa)) is not None]
    docx = construir_acta(
        DatosOficio(
            programa=programa,
            fecha=hoy,
            casos=items,
            numero_acta=formato_numero(numero),
            fecha_sesion=fecha_larga(fecha_sesion),
            miembros=integrantes(programa),
        ),
        settings.periodo_actual,
    )
    carpeta = settings.output_dir / "actas" / str(fecha_sesion.year) / direccion
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / (
        f"Acta_{formato_numero(numero)}_{fecha_sesion.year}_{programa.clave}.docx"
    )
    try:
        with ruta.open("xb") as salida:
            salida.write(docx)
    except FileExistsError:
        raise ActaNoPermitida(
            f"Ya existe el acta {formato_numero(numero)} de {fecha_sesion.year}."
        ) from None
    try:
        acta_id = await registrar_cierre(
            db,
            direccion=direccion,
            programa=clave,
            numero=numero,
            fecha_sesion=fecha_sesion,
            caso_ids=acta.caso_ids,
            persona=persona,
            canal=canal,
            docx_ruta=ruta,
            docx_sha256=hashlib.sha256(docx).hexdigest(),
        )
        await flujo.enviar_consejo(
            db,
            acta.caso_ids,
            rol=flujo.ADMIN if rol == flujo.ADMIN else flujo.ADMINISTRATIVA,
            persona=persona,
            canal=canal,
            detalle=f"Acta {formato_numero(numero)} de {fecha_sesion.year} cerrada",
            commit=False,
        )
        await db.commit()
    except BaseException:
        await db.rollback()
        ruta.unlink(missing_ok=True)
        raise
    cerrada = await obtener(db, acta_id)
    assert cerrada is not None
    return cerrada


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


async def _acta(db: Conexion, r: Fila) -> ActaComite:
    cur = await db.execute(
        "SELECT caso_id FROM acta_comite_casos WHERE acta_id = ? ORDER BY caso_id",
        (int(r["id"]),),
    )
    return ActaComite(
        id=int(r["id"]),
        direccion=str(r["direccion"]),
        programa=str(r["programa"]),
        anio=int(r["anio"]) if r["anio"] is not None else None,
        numero=int(r["numero"]) if r["numero"] is not None else None,
        fecha_sesion=str(r["fecha_sesion"]) if r["fecha_sesion"] else None,
        estado=str(r["estado"]),
        firma_id=int(r["firma_id"]) if r["firma_id"] is not None else None,
        cerrada_por=str(r["cerrada_por"]) if r["cerrada_por"] else None,
        canal=str(r["canal"]),
        cerrada=str(r["cerrada"] or ""),
        caso_ids=[int(f["caso_id"]) for f in await cur.fetchall()],
        docx_ruta=Path(r["docx_ruta"]) if r["docx_ruta"] else None,
        docx_sha256=str(r["docx_sha256"]) if r["docx_sha256"] else None,
    )


async def obtener(db: Conexion, acta_id: int) -> ActaComite | None:
    cur = await db.execute("SELECT * FROM actas_comite WHERE id = ?", (acta_id,))
    r = await cur.fetchone()
    return await _acta(db, r) if r else None


async def de_la_direccion(
    db: Conexion, direccion: str, limite: int = 200
) -> list[ActaComite]:
    """Actas cerradas de la dirección: las más recientes primero; las
    históricas sin fecha, al final."""
    cur = await db.execute(
        "SELECT * FROM actas_comite WHERE direccion = ? "
        "ORDER BY COALESCE(fecha_sesion, '') DESC, id DESC LIMIT ?",
        (direccion, limite),
    )
    return [await _acta(db, r) for r in await cur.fetchall()]


def leer_docx(acta: ActaComite) -> bytes:
    """El Word guardado al cerrar, solo si su SHA-256 es el registrado."""
    if acta.docx_ruta is None or acta.docx_sha256 is None:
        raise FileNotFoundError("El acta no tiene Word guardado.")
    contenido = acta.docx_ruta.read_bytes()
    if hashlib.sha256(contenido).hexdigest() != acta.docx_sha256:
        raise ActaNoPermitida(
            f"El archivo {acta.docx_ruta.name} no coincide con el que se guardó."
        )
    return contenido


# ---------------------------------------------------------------------------
# Migración (idempotente, corre al abrir la base)
# ---------------------------------------------------------------------------


async def migrar(db: Conexion, *, tabla_nueva: bool) -> int:
    """Lleva a `actas_comite` lo cerrado antes del consecutivo. Sin commit.

    - Cada firma sin acta queda como acta firmada, con su número solo si era
      un número (no se inventa ninguno).
    - Solo la primera vez (`tabla_nueva`): los casos cerrados que no están en
      ninguna acta (p. ej., /cerrar_acta) quedan en un acta histórica por
      programa, sin número ni fecha.
    """
    n = 0
    cur = await db.execute(
        "SELECT * FROM firmas WHERE id NOT IN "
        "(SELECT firma_id FROM actas_comite WHERE firma_id IS NOT NULL) ORDER BY id"
    )
    for f in await cur.fetchall():
        try:
            numero: int | None = leer_numero(str(f["numero_acta"]))
        except ValueError:
            numero = None
        try:
            fecha: date | None = date.fromisoformat(str(f["fecha_sesion"])[:10])
        except ValueError:
            fecha = None
        anio = fecha.year if fecha else None
        if numero is not None and anio is not None:
            dup = await db.execute(
                "SELECT 1 FROM actas_comite WHERE programa = ? AND anio = ? "
                "AND numero = ?",
                (f["programa"], anio, numero),
            )
            if await dup.fetchone() is not None:
                numero = None  # dos firmas con el mismo número: no se adivina
        ins = await db.execute(
            "INSERT INTO actas_comite (direccion, programa, anio, numero, "
            "fecha_sesion, estado, firma_id, cerrada_por, canal, cerrada) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f["direccion"],
                f["programa"],
                anio,
                numero,
                fecha.isoformat() if fecha else None,
                FIRMADA,
                int(f["id"]),
                f["firmado_por"],
                f["canal"],
                f["firmado"],
            ),
        )
        assert ins.lastrowid is not None
        await _ligar(
            db, int(ins.lastrowid), [int(i) for i in json.loads(f["caso_ids"])]
        )
        n += 1

    if not tabla_nueva:
        return n
    cur = await db.execute(
        "SELECT id, direccion, programa FROM casos WHERE estado = ? "
        "AND programa IS NOT NULL AND id NOT IN "
        "(SELECT caso_id FROM acta_comite_casos) ORDER BY id",
        (EstadoCaso.CERRADO.value,),
    )
    grupos: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in await cur.fetchall():
        grupos[(str(r["direccion"]), str(r["programa"]))].append(int(r["id"]))
    for (direccion, programa), ids in grupos.items():
        ins = await db.execute(
            "INSERT INTO actas_comite (direccion, programa, estado, canal) "
            "VALUES (?, ?, ?, ?)",
            (direccion, programa, CERRADA, "migracion"),
        )
        assert ins.lastrowid is not None
        await _ligar(db, int(ins.lastrowid), ids)
        n += 1
    return n
