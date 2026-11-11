"""API web del servicio de actas. Solo se monta con BOT_SERVICIO=actas.

La administrativa y el comité ven solo los casos de su área curricular. El
comité nunca aprueba: se registra «Recomendar aprobar» o «Recomendar no
aprobar», y decide el Consejo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.core import solicitudes
from app.core.programas import (
    DIRECCIONES,
    PROGRAMAS,
    comite_de,
    integrantes_con_nombre,
    programas_de,
    programas_del_comite,
)
from app.db import repo
from app.schemas.caso import TITULOS_TIPO, Caso, EstadoCaso, Sentido
from app.schemas.consejo import (
    ETIQUETA_SENTIDO_CONSEJO,
    NOMBRE_INSTANCIA,
    Cruce,
    EstadoDecision,
    Instancia,
)
from app.services import (
    actas_comite,
    adjuntos,
    borrador,
    casos,
    consejo,
    firma,
    flujo,
    indicadores,
    oficio_consejo,
    suit,
)
from app.services.drive import cliente as drive

router = APIRouter(prefix="/actas")

_Administrativa = Annotated[Usuario, Depends(auth.requiere("administrativa"))]
_Area = Annotated[Usuario, Depends(auth.requiere("administrativa", "comite"))]
_Lectura = Annotated[Usuario, Depends(auth.requiere("decanatura", "admin"))]
_ActaConsejo = Annotated[Usuario, Depends(auth.requiere("administrativa", "admin"))]
# Oficio, acta y firma: la administrativa o admin, siempre de su dirección.
_Firma = Annotated[Usuario, Depends(auth.requiere("administrativa", "admin"))]

# Adjuntos por envío; el tope por caso y por archivo está en
# app/services/adjuntos.py.
_MAX_POR_ENVIO = 20

ETIQUETA_SENTIDO = {
    Sentido.APROBAR: "Recomendar aprobar",
    Sentido.NO_APROBAR: "Recomendar no aprobar",
    Sentido.PENDIENTE: "Pendiente",
}


def _direccion(usuario: Usuario) -> str:
    if usuario.direccion not in DIRECCIONES:
        raise HTTPException(403, "Su usuario no tiene área curricular asignada.")
    return usuario.direccion


async def _caso_del_area(db: Db, caso_id: int, usuario: Usuario) -> Caso:
    caso = await repo.get_caso(db, caso_id)
    if caso is None or caso.direccion != _direccion(usuario):
        raise HTTPException(404, "No encontré ese caso en su área.")
    return caso


def _resumen(caso: Caso) -> dict[str, object]:
    ext = caso.extraccion
    return {
        "id": caso.id,
        "estado": caso.estado.value,
        "sentido": caso.sentido.value,
        "sentido_texto": ETIQUETA_SENTIDO[caso.sentido],
        "programa": PROGRAMAS[caso.programa].nombre
        if caso.programa in PROGRAMAS
        else None,
        "estudiante": ext.nombre_estudiante if ext else None,
        "objeto": ext.objeto_solicitud if ext else None,
        "creado": caso.creado,
        "consejo": _consejo(caso),
        "etapa": caso.etapa,
        "etapa_texto": flujo.nombre_etapa(caso.etapa),
        # Bandeja de la administrativa (marca aparte de la etapa).
        "archivado": caso.archivado,
        "archivable": caso.archivado is None
        and caso.etapa in {e.value for e in flujo.TERMINADAS},
    }


def _consejo(caso: Caso) -> dict[str, object] | None:
    """Decisión del Consejo confirmada desde su acta; sin acta, None."""
    d = caso.consejo
    if d is None:
        return None
    return {
        **d.model_dump(mode="json"),
        "instancia_texto": NOMBRE_INSTANCIA[d.instancia],
        "sentido_texto": ETIQUETA_SENTIDO_CONSEJO[d.sentido],
    }


def _ruta(caso: Caso) -> dict[str, object]:
    """Quién recomienda y quién decide, según config/solicitudes.yaml."""
    tipos = caso.extraccion.tipos if caso.extraccion else []
    config = solicitudes.actual()
    return {
        "recomienda": "Comité asesor",
        "decide": solicitudes.texto_decide(tipos),
        "por_confirmar": any(r.por_confirmar for r, _ in solicitudes.decisores(tipos)),
        "fuera_de_facultad": solicitudes.fuera_de_facultad(tipos),
        "tramites": [
            {
                "tipo": t.value,
                "titulo": TITULOS_TIPO[t],
                "decide": config.ruta(t).nombre_decide,
                "por_confirmar": config.ruta(t).por_confirmar,
                "acto": config.ruta(t).nombre_acto,
                "nota": config.ruta(t).nota,
            }
            for t in tipos
        ],
    }


def _detalle(caso: Caso) -> dict[str, object]:
    analisis = casos.analizar(caso)
    return {
        **_resumen(caso),
        "programa_clave": caso.programa,
        "extraccion": caso.extraccion.model_dump(mode="json")
        if caso.extraccion
        else None,
        "ruta": _ruta(caso),
        "alertas": [a.model_dump() for a in analisis.alertas] if analisis else [],
        "cifras": {
            "creditos_inscritos": analisis.creditos_inscritos,
            "creditos_tras_solicitud": analisis.creditos_tras_solicitud,
            "papa": analisis.papa,
            "porcentaje_avance": analisis.porcentaje_avance,
            "semana": analisis.semana,
        }
        if analisis
        else None,
        "nota_comite": caso.nota_comite,
        "conceptos": [c.model_dump() for c in caso.conceptos],
        "miembros": [
            m.nombre for m in integrantes_con_nombre(comite_de(caso.programa))
        ],
        "programas": [
            {"clave": p.clave, "nombre": p.nombre} for p in programas_de(caso.direccion)
        ],
        "imagenes": len(caso.imagenes),
        "anexos": caso.anexos_archivos,
        # Borrador del oficio de notificación del Consejo (docs/oficios-consejo.md).
        "oficio_consejo": oficio_consejo.motivo_sin_oficio(caso) is None,
    }


def _evento(e: flujo.Evento) -> dict[str, object]:
    return {
        "accion": e.accion.value,
        "texto": flujo.NOMBRE_ACCION[e.accion],
        "desde": e.desde.value if e.desde else None,
        "hacia": e.hacia.value,
        "hacia_texto": flujo.NOMBRE_ETAPA[e.hacia],
        "fecha": flujo.hora_local(e.fecha),
        "rol": flujo.NOMBRE_ROL.get(e.rol, e.rol),
        "persona": e.persona,
        "canal": e.canal,
        "detalle": e.detalle,
        "registrado": flujo.hora_local(e.registrado),
    }


async def _linea(db: Db, caso: Caso, rol: str) -> dict[str, object]:
    """La línea única del caso: etapa, historia, siguiente paso y tramos."""
    evs = await flujo.eventos(db, caso.id)
    etapa = await flujo.etapa_de(db, caso.id)
    await db.commit()  # por si la etapa se derivó en esta lectura
    sig = flujo.siguiente(
        etapa,
        leido=caso.extraccion is not None,
        tipos=caso.extraccion.tipos if caso.extraccion else [],
        instancia_decision=caso.consejo.instancia.value if caso.consejo else None,
        archivo_drive=drive.configurado(),
    )
    extraccion = caso.extraccion.model_dump_json() if caso.extraccion else None
    return {
        "etapa": etapa.value,
        "etapa_texto": flujo.NOMBRE_ETAPA[etapa],
        "prerrevision": caso.prerrevision,
        "linea": [_evento(e) for e in evs],
        "siguiente": {"paso": sig.paso, "responsable": sig.responsable}
        if sig
        else None,
        "tramos": [
            {"nombre": t.nombre, "dias": t.dias} for t in flujo.tramos(evs, extraccion)
        ],
        # Qué botones de la línea puede usar la administrativa ahora. Al
        # comité no se le ofrece ninguno: solo consulta y deja conceptos.
        "acciones": [
            a.value
            for a in (
                flujo.Accion.PRERREVISAR_PROCEDENTE,
                flujo.Accion.PRERREVISAR_IMPROCEDENTE,
                flujo.Accion.PRERREVISAR_INCOMPLETO,
                flujo.Accion.COMPLETAR,
                flujo.Accion.RECOMENDAR,
                flujo.Accion.ENVIAR_CONSEJO,
                flujo.Accion.VOLVER_AL_COMITE,
            )
            if rol == flujo.ADMINISTRATIVA and flujo.puede(a, etapa, rol)
        ],
    }


async def _ficha(db: Db, caso: Caso, usuario: Usuario) -> dict[str, object]:
    return {
        **_detalle(caso),
        **await _linea(db, caso, usuario.rol),
        "adjuntos": await adjuntos.listar(db, caso.id),
        "tipos_adjuntos": adjuntos.TEXTO_PERMITIDOS,
    }


def _conflicto(exc: flujo.TransicionNoPermitida) -> HTTPException:
    return HTTPException(409, str(exc))


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------


@router.get("/casos")
async def listar(usuario: _Area, db: Db, archivados: bool = False) -> dict[str, object]:
    """La bandeja: por defecto, los casos activos; con `archivados=true`, los
    que la administrativa sacó de la bandeja."""
    direccion = _direccion(usuario)
    recientes = await repo.casos_recientes(
        db, direccion=direccion, limite=100, archivados=archivados
    )
    return {
        "area": DIRECCIONES[direccion].nombre,
        "casos": [_resumen(c) for c in recientes],
    }


class Seleccion(BaseModel):
    ids: list[int]


# Archivar de la bandeja: la administrativa de su dirección o admin (de
# cualquier dirección). No cambia la etapa (app/services/flujo.py).
_Bandeja = Annotated[Usuario, Depends(auth.requiere("administrativa", "admin"))]


async def _bandeja(cuerpo: Seleccion, usuario: Usuario, db: Db, archivar: bool) -> int:
    if not 1 <= len(cuerpo.ids) <= 200:
        raise HTTPException(400, "Elija entre 1 y 200 casos.")
    operacion = flujo.archivar_de_bandeja if archivar else flujo.desarchivar_de_bandeja
    try:
        return await operacion(
            db,
            cuerpo.ids,
            rol=usuario.rol,
            persona=_persona(usuario),
            canal="web",
            direccion=_alcance(usuario),
        )
    except flujo.TransicionNoPermitida as exc:
        raise _conflicto(exc) from None


@router.post("/casos/archivar")
async def archivar_casos(
    cuerpo: Seleccion, usuario: _Bandeja, db: Db
) -> dict[str, object]:
    """Saca de la bandeja uno o varios casos terminados, sin borrarlos."""
    return {"archivados": await _bandeja(cuerpo, usuario, db, archivar=True)}


@router.post("/casos/desarchivar")
async def desarchivar_casos(
    cuerpo: Seleccion, usuario: _Bandeja, db: Db
) -> dict[str, object]:
    """Devuelve uno o varios casos a la bandeja."""
    return {"desarchivados": await _bandeja(cuerpo, usuario, db, archivar=False)}


async def _leer_adjuntos(archivos: list[UploadFile]) -> list[tuple[bytes, str]]:
    """Lee y valida todo antes de guardar nada: si uno no sirve, no entra
    ninguno y se dice cuál."""
    if len(archivos) > _MAX_POR_ENVIO:
        raise HTTPException(400, f"Adjunte máximo {_MAX_POR_ENVIO} archivos a la vez.")
    leidos: list[tuple[bytes, str]] = []
    for a in archivos:
        nombre = (a.filename or "archivo").rsplit("/", 1)[-1][:200]
        datos = await a.read(adjuntos.MAX_DOCUMENTO + 1)
        try:
            adjuntos.validar(datos, nombre)
        except adjuntos.AdjuntoInvalido as exc:
            raise HTTPException(400, str(exc)) from None
        leidos.append((datos, nombre))
    return leidos


async def _guardar_adjuntos(
    db: Db, caso_id: int, leidos: list[tuple[bytes, str]]
) -> list[adjuntos.Agregado]:
    if len(leidos) > await adjuntos.cupo(db, caso_id):
        raise HTTPException(
            400, f"Un caso admite máximo {adjuntos.MAX_POR_CASO} adjuntos."
        )
    try:
        return [await adjuntos.agregar(db, caso_id, d, n) for d, n in leidos]
    except adjuntos.AdjuntoInvalido as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/casos")
async def crear(
    usuario: _Administrativa,
    db: Db,
    texto: Annotated[str, Form()] = "",
    archivos: Annotated[list[UploadFile] | None, File()] = None,
    imagenes: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, object]:
    """Crea un caso con el texto del correo y sus adjuntos: pantallazos del
    SIA, formatos de solicitud y anexos (PDF, Word o imágenes)."""
    direccion = _direccion(usuario)
    todos = [*(archivos or []), *(imagenes or [])]
    if not texto.strip() and not todos:
        raise HTTPException(400, "Pegue el correo o adjunte al menos un archivo.")
    leidos = await _leer_adjuntos(todos)
    caso_id = await repo.crear_caso(
        db,
        chat_id=0,
        user_id=0,
        direccion=direccion,
        canal="web",
        persona=_persona(usuario),
    )
    if texto.strip():
        await repo.agregar_texto(db, caso_id, texto.strip())
    await _guardar_adjuntos(db, caso_id, leidos)
    return {"id": caso_id}


@router.get("/casos/{caso_id}")
async def ver(caso_id: int, usuario: _Area, db: Db) -> dict[str, object]:
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


_Borrar = Annotated[Usuario, Depends(auth.requiere("administrativa", "admin"))]


@router.post("/casos/{caso_id}/archivos")
async def adjuntar(
    caso_id: int,
    usuario: _Administrativa,
    db: Db,
    archivos: Annotated[list[UploadFile], File()],
) -> dict[str, object]:
    """Agrega adjuntos a un caso ya creado."""
    caso = await _caso_del_area(db, caso_id, usuario)
    if caso.estado in (EstadoCaso.CERRADO, EstadoCaso.DECIDIDO_CONSEJO):
        raise HTTPException(
            409, "El caso ya pasó por el comité; no se le agregan adjuntos."
        )
    if not archivos:
        raise HTTPException(400, "Elija al menos un archivo.")
    agregados = await _guardar_adjuntos(db, caso.id, await _leer_adjuntos(archivos))
    caso = await _caso_del_area(db, caso_id, usuario)
    avisos: list[str] = []
    if any(a.tipo == "pendiente" for a in agregados):
        avisos.append("Hay un PDF escaneado: indique si es el formato.")
    if caso.extraccion is not None and any(
        a.nuevo and a.tipo in ("imagen", "formato") for a in agregados
    ):
        avisos.append("Vuelva a leer el caso para incluir lo nuevo.")
    return {**await _ficha(db, caso, usuario), "aviso": " ".join(avisos) or None}


@router.get("/casos/{caso_id}/archivos/{archivo_id}")
async def descargar_adjunto(
    caso_id: int, archivo_id: int, usuario: _Area, db: Db
) -> Response:
    caso = await _caso_del_area(db, caso_id, usuario)
    archivo = await repo.get_archivo_por_id(db, caso.id, archivo_id)
    if archivo is None or not archivo.ruta or not Path(archivo.ruta).exists():
        raise HTTPException(404, "Ese adjunto no está guardado.")
    ruta = Path(archivo.ruta)
    nombre = archivo.nombre or f"adjunto_{archivo.id}{ruta.suffix}"
    return Response(
        ruta.read_bytes(),
        media_type=adjuntos.MIME.get(ruta.suffix.lower(), "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"
        },
    )


class Clasificacion(BaseModel):
    es_formato: bool


@router.post("/casos/{caso_id}/archivos/{archivo_id}/clasificar")
async def clasificar_adjunto(
    caso_id: int,
    archivo_id: int,
    cuerpo: Clasificacion,
    usuario: _Administrativa,
    db: Db,
) -> dict[str, object]:
    """Un PDF escaneado: la administrativa dice si es el formato de solicitud."""
    caso = await _caso_del_area(db, caso_id, usuario)
    archivo = await repo.get_archivo_por_id(db, caso.id, archivo_id)
    if archivo is None or archivo.file_unique_id is None:
        raise HTTPException(404, "No encontré ese adjunto.")
    mensaje = await adjuntos.resolver_pendiente(
        db, caso.id, archivo.file_unique_id, es_formato=cuerpo.es_formato
    )
    if mensaje is None:
        raise HTTPException(409, "Ese adjunto ya estaba clasificado.")
    return {
        **await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario),
        "aviso": mensaje,
    }


@router.delete("/casos/{caso_id}/archivos/{archivo_id}")
async def borrar_adjunto(
    caso_id: int, archivo_id: int, usuario: _Borrar, db: Db
) -> dict[str, object]:
    """Borra un adjunto equivocado del disco y de la base. Solo la
    administrativa del área del caso o admin. La web pide confirmación antes."""
    if usuario.rol == "admin" and usuario.direccion not in DIRECCIONES:
        caso = await repo.get_caso(db, caso_id)
        if caso is None:
            raise HTTPException(404, "No encontré ese caso.")
    else:
        caso = await _caso_del_area(db, caso_id, usuario)
    try:
        borrado = await adjuntos.borrar(
            db,
            caso,
            archivo_id,
            rol=usuario.rol,
            persona=_persona(usuario),
            canal="web",
        )
    except KeyError:
        raise HTTPException(404, "No encontré ese adjunto en el caso.") from None
    actualizado = await repo.get_caso(db, caso.id)
    assert actualizado is not None
    return {
        **await _ficha(db, actualizado, usuario),
        "aviso": borrado.aviso,
        "borrado_leido": borrado.leido,
    }


@router.post("/casos/{caso_id}/releer")
async def releer(caso_id: int, usuario: _Administrativa, db: Db) -> dict[str, object]:
    """Vuelve a leer con el modelo un caso ya leído (p. ej. tras quitar un
    adjunto). Cambia los datos leídos; nunca la recomendación."""
    caso = await _caso_del_area(db, caso_id, usuario)
    if caso.estado in (
        EstadoCaso.CERRADO,
        EstadoCaso.DECIDIDO_CONSEJO,
        EstadoCaso.DESCARTADO,
    ):
        raise HTTPException(
            409, f"El caso está {caso.estado.value}; ya no se vuelve a leer."
        )
    if not caso.texto.strip() and not caso.imagenes:
        raise HTTPException(400, "El caso está vacío.")
    estaba_listo = caso.estado == EstadoCaso.LISTO
    resultado = await casos.procesar(db, caso)
    if resultado.error is not None:
        if estaba_listo:
            # Se conserva la lectura anterior.
            await repo.set_estado_caso(db, caso.id, EstadoCaso.LISTO)
        raise HTTPException(
            502, f"No pude leer el caso: {resultado.error}. Puede intentarlo de nuevo."
        )
    return await _ficha(db, resultado.caso, usuario)


@router.get("/casos/{caso_id}/oficio-consejo")
async def descargar_oficio_consejo(caso_id: int, usuario: _Area, db: Db) -> Response:
    """Borrador del oficio (o resolución) con que la Secretaría notifica la
    decisión del Consejo de Facultad. Mismos permisos que ver el caso."""
    caso = await _caso_del_area(db, caso_id, usuario)
    motivo = oficio_consejo.motivo_sin_oficio(caso)
    if motivo:
        raise HTTPException(409, motivo)
    docx = oficio_consejo.construir_oficio_consejo(caso, elaboro=usuario.nombre or "")
    return Response(
        docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": "attachment; "
            f'filename="{oficio_consejo.nombre_archivo(caso)}"'
        },
    )


@router.post("/casos/{caso_id}/procesar")
async def procesar(caso_id: int, usuario: _Administrativa, db: Db) -> dict[str, object]:
    caso = await _caso_del_area(db, caso_id, usuario)
    if caso.estado not in (EstadoCaso.ABIERTO, EstadoCaso.ERROR, EstadoCaso.PROCESANDO):
        return await _ficha(db, caso, usuario)
    if not caso.texto.strip() and not caso.imagenes:
        raise HTTPException(400, "El caso está vacío.")
    resultado = await casos.procesar(db, caso)
    if resultado.error is not None:
        raise HTTPException(
            502, f"No pude leer el caso: {resultado.error}. Puede intentarlo de nuevo."
        )
    return await _ficha(db, resultado.caso, usuario)


class Texto(BaseModel):
    texto: str


@router.post("/casos/{caso_id}/correccion")
async def corregir(
    caso_id: int, cuerpo: Texto, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    caso = await _caso_del_area(db, caso_id, usuario)
    if caso.estado != EstadoCaso.LISTO or caso.extraccion is None:
        raise HTTPException(
            409, f"El caso está {caso.estado.value}; no se puede corregir."
        )
    resultado = await casos.corregir(db, caso, cuerpo.texto[:2000])
    if resultado.error is not None:
        raise HTTPException(502, f"No pude aplicar la corrección: {resultado.error}")
    return await _ficha(db, resultado.caso, usuario)


class Recomendacion(BaseModel):
    sentido: Sentido


@router.post("/casos/{caso_id}/recomendacion")
async def recomendar(
    caso_id: int, cuerpo: Recomendacion, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    """Registra lo que recomendó el comité. Lo decide una persona, no el modelo."""
    caso = await _caso_del_area(db, caso_id, usuario)
    try:
        await flujo.recomendar(
            db,
            caso.id,
            cuerpo.sentido,
            rol=usuario.rol,
            persona=_persona(usuario),
            canal="web",
        )
    except flujo.TransicionNoPermitida as exc:
        raise _conflicto(exc) from None
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


class Prerrevision(BaseModel):
    resultado: flujo.Prerrevision
    nota: str = ""


@router.post("/casos/{caso_id}/prerrevision")
async def prerrevision(
    caso_id: int, cuerpo: Prerrevision, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    """Prerrevisión del programa: procedente, improcedente o incompleta."""
    caso = await _caso_del_area(db, caso_id, usuario)
    try:
        await flujo.prerrevisar(
            db,
            caso.id,
            cuerpo.resultado,
            rol=usuario.rol,
            persona=_persona(usuario),
            canal="web",
            nota=cuerpo.nota,
        )
    except flujo.TransicionNoPermitida as exc:
        raise _conflicto(exc) from None
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


@router.post("/casos/{caso_id}/completar")
async def completar(
    caso_id: int, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    """Llegó lo que faltaba: el caso vuelve a la llegada para prerrevisarlo."""
    caso = await _caso_del_area(db, caso_id, usuario)
    try:
        await flujo.completar(
            db, caso.id, rol=usuario.rol, persona=_persona(usuario), canal="web"
        )
    except flujo.TransicionNoPermitida as exc:
        raise _conflicto(exc) from None
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


@router.post("/casos/{caso_id}/enviar-consejo")
async def enviar_consejo(
    caso_id: int, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    """El oficio del comité va al Consejo (en Telegram: «Cerrar»). El caso
    sale del borrador en curso."""
    caso = await _caso_del_area(db, caso_id, usuario)
    try:
        await flujo.enviar_consejo(
            db, [caso.id], rol=usuario.rol, persona=_persona(usuario), canal="web"
        )
    except flujo.TransicionNoPermitida as exc:
        raise _conflicto(exc) from None
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


@router.post("/casos/{caso_id}/volver-al-comite")
async def volver_al_comite(
    caso_id: int, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    """El caso vuelve del Consejo al comité (p. ej., si el Consejo lo aplazó)."""
    caso = await _caso_del_area(db, caso_id, usuario)
    try:
        await flujo.volver_al_comite(
            db, caso.id, rol=usuario.rol, persona=_persona(usuario), canal="web"
        )
    except flujo.TransicionNoPermitida as exc:
        raise _conflicto(exc) from None
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


@router.post("/casos/{caso_id}/nota")
async def nota(
    caso_id: int, cuerpo: Texto, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    caso = await _caso_del_area(db, caso_id, usuario)
    await repo.set_nota(db, caso.id, cuerpo.texto.strip()[:1500] or None)
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


class Programa(BaseModel):
    programa: str


@router.post("/casos/{caso_id}/programa")
async def fijar_programa(
    caso_id: int, cuerpo: Programa, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    caso = await _caso_del_area(db, caso_id, usuario)
    if cuerpo.programa not in {p.clave for p in programas_de(caso.direccion)}:
        raise HTTPException(400, "Ese programa no es de su área.")
    await repo.set_programa(db, caso.id, cuerpo.programa)
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


class NuevoConcepto(BaseModel):
    miembro: str
    texto: str


@router.post("/casos/{caso_id}/concepto")
async def concepto(
    caso_id: int, cuerpo: NuevoConcepto, usuario: _Area, db: Db
) -> dict[str, object]:
    """Concepto de un miembro del comité. Va al acta, no al oficio."""
    caso = await _caso_del_area(db, caso_id, usuario)
    miembro = cuerpo.miembro.strip()
    if not miembro or not cuerpo.texto.strip():
        raise HTTPException(400, "Indique el miembro del comité y su concepto.")
    await repo.guardar_concepto(
        db,
        caso.id,
        miembro=miembro,
        tratamiento=casos.tratamiento_de(caso, miembro),
        texto=cuerpo.texto.strip()[:4000],
    )
    return await _ficha(db, await _caso_del_area(db, caso_id, usuario), usuario)


# ---------------------------------------------------------------------------
# Oficio y acta
# ---------------------------------------------------------------------------


@router.get("/documentos")
async def documentos(usuario: _Firma, db: Db) -> dict[str, object]:
    """Comités con casos listos para el borrador de oficio y acta: uno por
    programa en pregrado; uno para toda la dirección si tiene comité único."""
    listos = await repo.casos_listos(db, direccion=_direccion(usuario))
    comites = {
        comite.clave: comite
        for c in listos
        if c.programa in PROGRAMAS and (comite := comite_de(c.programa)) is not None
    }
    anio = firma.hoy_local().year
    salida = []
    for clave in sorted(comites):
        comite = comites[clave]
        del_comite = [c for c in listos if c.programa in programas_del_comite(comite)]
        salida.append(
            {
                "clave": clave,
                "nombre": comite.nombre,
                "comite": comite.comite,
                # En un comité único, los programas cuyos casos entran.
                "programas": [
                    PROGRAMAS[p].nombre for p in comite.programas if p in PROGRAMAS
                ],
                # El acta en curso: el número es una propuesta (último + 1).
                "acta_propuesta": actas_comite.formato_numero(
                    await actas_comite.proponer_numero(db, clave, anio)
                ),
                "anio": anio,
                "casos": len(del_comite),
                "con_recomendacion": sum(
                    1 for c in del_comite if c.sentido != Sentido.PENDIENTE
                ),
            }
        )
    return {
        "programas": salida,
        "sin_programa": [c.id for c in listos if c.programa not in PROGRAMAS],
    }


@router.get("/documentos/{programa}/{tipo}")
async def descargar(programa: str, tipo: str, usuario: _Firma, db: Db) -> Response:
    if tipo not in ("oficio", "acta"):
        raise HTTPException(404, "Documento desconocido.")
    borradores, _ = await borrador.armar_borradores(
        db,
        direccion=_direccion(usuario),
        elaboro=usuario.nombre,
        solo_con_cambios=False,
    )
    comite = comite_de(programa)
    clave = comite.clave if comite else programa
    elegido = next((b for b in borradores if b.programa.clave == clave), None)
    if elegido is None:
        raise HTTPException(404, "No hay casos listos para ese programa.")
    archivo = elegido.oficio if tipo == "oficio" else elegido.acta
    return Response(
        archivo.docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            # Nombres con tildes (Área…, Matemáticas): RFC 5987.
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(archivo.ruta_docx.name)
        },
    )


# ---------------------------------------------------------------------------
# Firma del oficio y del acta (app/services/firma.py)
# ---------------------------------------------------------------------------

_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


class PedidoFirma(BaseModel):
    radicado: str
    numero_acta: str
    fecha_sesion: str
    hora: str
    lugar: str
    # Los casos que la persona vio en el resumen: si cambiaron, no se firma.
    caso_ids: list[int]
    confirmo: bool = False


def _firma_json(f: firma.Firma) -> dict[str, object]:
    programa = comite_de(f.programa)
    return {
        "id": f.id,
        "programa": f.programa,
        "programa_nombre": programa.nombre if programa else f.programa,
        "radicado": f.radicado,
        "numero_acta": f.numero_acta,
        "fecha_sesion": f.fecha_sesion,
        "hora": f.hora,
        "lugar": f.lugar,
        "caso_ids": f.caso_ids,
        "firmante": f.firmante,
        "firmado_por": f.firmado_por,
        "rol": f.rol,
        "canal": f.canal,
        "con_imagen": f.con_imagen,
        "firmado": f.firmado,
        "archivos": [
            {
                "documento": a.documento,
                "formato": a.formato,
                "nombre": a.ruta.name,
                "sha256": a.sha256,
            }
            for a in f.archivos
        ],
    }


@router.get("/firmar/{programa}")
async def preparar_firma(programa: str, usuario: _Firma, db: Db) -> dict[str, object]:
    """Resumen antes de firmar: no escribe nada."""
    try:
        prep = await firma.preparar(
            db, direccion=_direccion(usuario), clave=programa, rol=usuario.rol
        )
    except firma.FirmaNoPermitida as exc:
        raise HTTPException(404, str(exc)) from None
    return {
        "programa": prep.programa.clave,
        "programa_nombre": prep.programa.comite
        if prep.programa.es_comite_unico
        else prep.programa.nombre,
        "firmante": (
            {
                "nombre": prep.firmante.nombre,
                "cargo": prep.firmante.cargo_bajo_firma,
            }
            if prep.firmante
            else None
        ),
        "firma_en_nombre": _persona(usuario),
        "tiene_imagen": prep.tiene_imagen,
        "radicado_propuesto": prep.radicado_propuesto,
        "numero_acta_propuesto": prep.numero_acta_propuesto,
        "casos": [
            {
                "id": c.id,
                "estudiante": (
                    c.extraccion.nombre_estudiante if c.extraccion else None
                ),
                "sentido": c.sentido.value,
                "sentido_texto": ETIQUETA_SENTIDO[c.sentido],
                # En un comité único, el programa de cada caso.
                "programa": PROGRAMAS[c.programa].nombre
                if prep.programa.es_comite_unico and c.programa in PROGRAMAS
                else None,
            }
            for c in prep.casos
        ],
        "caso_ids": prep.caso_ids,
        "pendientes": [c.id for c in prep.pendientes],
        "bloqueos": prep.bloqueos,
        "avisos": prep.avisos,
    }


@router.post("/firmar/{programa}")
async def firmar(
    programa: str, cuerpo: PedidoFirma, usuario: _Firma, db: Db
) -> dict[str, object]:
    """Firma con confirmación explícita: genera el .docx y el PDF finales,
    registra la firma y los casos pasan al Consejo."""
    if not cuerpo.confirmo:
        raise HTTPException(400, "Falta confirmar la firma.")
    try:
        sesion = firma.validar_sesion(
            numero_acta=cuerpo.numero_acta,
            fecha_sesion=cuerpo.fecha_sesion,
            hora=cuerpo.hora,
            lugar=cuerpo.lugar,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        hecha = await firma.firmar(
            db,
            direccion=_direccion(usuario),
            clave=programa,
            radicado=cuerpo.radicado,
            sesion=sesion,
            caso_ids=cuerpo.caso_ids,
            persona=_persona(usuario),
            rol=usuario.rol,
            canal="web",
        )
    except (firma.FirmaNoPermitida, flujo.TransicionNoPermitida) as exc:
        raise HTTPException(409, str(exc)) from None
    anio = firma.hoy_local().year
    siguiente = await actas_comite.proponer_numero(db, hecha.programa, anio)
    return {
        **_firma_json(hecha),
        "acta_siguiente": actas_comite.formato_numero(siguiente),
    }


@router.get("/firmas")
async def firmas(usuario: _Firma, db: Db) -> dict[str, object]:
    """Documentos firmados de la dirección, el más reciente primero."""
    return {
        "firmas": [
            _firma_json(f) for f in await firma.de_la_direccion(db, _direccion(usuario))
        ]
    }


@router.get("/firmas/{firma_id}/{documento}/{formato}")
async def descargar_firmado(
    firma_id: int, documento: str, formato: str, usuario: _Firma, db: Db
) -> Response:
    hecha = await firma.obtener(db, firma_id)
    if hecha is None or hecha.direccion != _direccion(usuario):
        raise HTTPException(404, "No encontré esa firma en su dirección.")
    archivo = hecha.archivo(documento, formato)
    if archivo is None or formato not in _MIME:
        raise HTTPException(404, "Ese documento no se generó.")
    try:
        contenido = firma.leer_verificado(archivo)
    except FileNotFoundError:
        raise HTTPException(404, "El archivo ya no está en el volumen.") from None
    except firma.FirmaNoPermitida as exc:
        raise HTTPException(409, str(exc)) from None
    return Response(
        contenido,
        media_type=_MIME[formato],
        headers={"Content-Disposition": f'attachment; filename="{archivo.ruta.name}"'},
    )


# ---------------------------------------------------------------------------
# Actas del comité por programa (app/services/actas_comite.py)
# ---------------------------------------------------------------------------


def _acta_comite_json(a: actas_comite.ActaComite) -> dict[str, object]:
    programa = comite_de(a.programa)
    archivos: list[dict[str, str]] = []
    if a.docx_ruta is not None:
        archivos.append(
            {
                "documento": "acta",
                "formato": "docx",
                "nombre": a.docx_ruta.name,
                "ruta": f"/actas/actas-comite/{a.id}/docx",
            }
        )
    return {
        "id": a.id,
        "programa": a.programa,
        "programa_nombre": programa.nombre if programa else a.programa,
        "anio": a.anio,
        "numero": a.numero_texto,
        "fecha_sesion": a.fecha_sesion,
        "estado": a.estado,
        "firma_id": a.firma_id,
        "cerrada_por": a.cerrada_por,
        "cerrada": a.cerrada,
        "caso_ids": a.caso_ids,
        "archivos": archivos,
    }


@router.get("/actas-comite")
async def actas_del_comite(usuario: _Firma, db: Db) -> dict[str, object]:
    """Actas cerradas de la dirección, por programa. Las firmadas se descargan
    con /firmas/{firma_id}/..., las cerradas sin firma, con su Word."""
    direccion = _direccion(usuario)
    firmas_por_id = {f.id: f for f in await firma.de_la_direccion(db, direccion, 500)}
    salida = []
    for a in await actas_comite.de_la_direccion(db, direccion):
        fila = _acta_comite_json(a)
        hecha = firmas_por_id.get(a.firma_id) if a.firma_id else None
        if hecha is not None:
            fila["radicado"] = hecha.radicado
            fila["archivos"] = [
                {
                    "documento": x.documento,
                    "formato": x.formato,
                    "nombre": x.ruta.name,
                    "ruta": f"/actas/firmas/{hecha.id}/{x.documento}/{x.formato}",
                }
                for x in hecha.archivos
            ]
        salida.append(fila)
    return {"actas": salida}


@router.get("/actas-comite/{programa}/abierta")
async def acta_abierta(programa: str, usuario: _Firma, db: Db) -> dict[str, object]:
    """El acta en curso del programa, para cerrarla sin firma. No escribe."""
    try:
        acta = await actas_comite.abierta(
            db,
            direccion=_direccion(usuario),
            clave=programa,
            hoy=firma.hoy_local(),
        )
    except actas_comite.ActaNoPermitida as exc:
        raise HTTPException(404, str(exc)) from None
    return {
        "programa": acta.programa.clave,
        "programa_nombre": acta.programa.nombre,
        "anio": acta.anio,
        "numero_propuesto": actas_comite.formato_numero(acta.numero_propuesto),
        "casos": [
            {
                "id": c.id,
                "estudiante": c.extraccion.nombre_estudiante if c.extraccion else None,
                "sentido_texto": ETIQUETA_SENTIDO[c.sentido],
            }
            for c in acta.casos
        ],
        "caso_ids": acta.caso_ids,
        "pendientes": [c.id for c in acta.pendientes],
    }


class PedidoCierre(BaseModel):
    numero: str
    fecha_sesion: str
    # Los casos que la persona vio: si cambiaron, no se cierra.
    caso_ids: list[int]
    confirmo: bool = False


@router.post("/actas-comite/{programa}/cerrar")
async def cerrar_acta(
    programa: str, cuerpo: PedidoCierre, usuario: _Firma, db: Db
) -> dict[str, object]:
    """Cierra el acta en curso sin firma en MemorIA (se firmó por fuera): los
    casos pasan al Consejo y los nuevos entran a la siguiente."""
    if not cuerpo.confirmo:
        raise HTTPException(400, "Falta confirmar el cierre.")
    try:
        numero = actas_comite.leer_numero(cuerpo.numero)
        fecha = firma.leer_fecha(cuerpo.fecha_sesion)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    hoy = firma.hoy_local()
    try:
        cerrada = await actas_comite.cerrar_sin_firma(
            db,
            direccion=_direccion(usuario),
            clave=programa,
            numero=numero,
            fecha_sesion=fecha,
            caso_ids=cuerpo.caso_ids,
            persona=_persona(usuario),
            rol=usuario.rol,
            canal="web",
            hoy=hoy,
        )
    except (actas_comite.ActaNoPermitida, flujo.TransicionNoPermitida) as exc:
        raise HTTPException(409, str(exc)) from None
    siguiente = await actas_comite.proponer_numero(db, cerrada.programa, hoy.year)
    return {
        **_acta_comite_json(cerrada),
        "acta_siguiente": actas_comite.formato_numero(siguiente),
    }


@router.get("/actas-comite/{acta_id}/docx")
async def descargar_acta_comite(acta_id: int, usuario: _Firma, db: Db) -> Response:
    acta = await actas_comite.obtener(db, acta_id)
    if acta is None or acta.direccion != _direccion(usuario):
        raise HTTPException(404, "No encontré esa acta en su dirección.")
    try:
        contenido = actas_comite.leer_docx(acta)
    except FileNotFoundError:
        raise HTTPException(404, "El Word de esa acta no está guardado.") from None
    except actas_comite.ActaNoPermitida as exc:
        raise HTTPException(409, str(exc)) from None
    assert acta.docx_ruta is not None
    return Response(
        contenido,
        media_type=_MIME["docx"],
        headers={
            "Content-Disposition": f'attachment; filename="{acta.docx_ruta.name}"'
        },
    )


# ---------------------------------------------------------------------------
# Acta del Consejo
# ---------------------------------------------------------------------------


def _alcance(usuario: Usuario) -> str | None:
    """La administrativa cruza con los casos de su área; admin, con todos."""
    return None if usuario.rol == "admin" else _direccion(usuario)


def _persona(usuario: Usuario) -> str:
    return usuario.nombre or usuario.correo


def _caso_corto(caso: Caso | None) -> dict[str, object] | None:
    if caso is None:
        return None
    ext = caso.extraccion
    return {
        "id": caso.id,
        "estudiante": ext.nombre_estudiante if ext else None,
        "documento": ext.documento if ext else None,
        "programa": PROGRAMAS[caso.programa].nombre
        if caso.programa in PROGRAMAS
        else None,
        "recomendacion": ETIQUETA_SENTIDO[caso.sentido],
    }


async def _filas_visibles(
    db: Db, acta: consejo.Acta, alcance: str | None
) -> list[consejo.FilaDecision]:
    """Solo las decisiones cuyo caso o candidatos son del área de quien mira."""
    return [
        f
        for f in await consejo.decisiones_del_acta(db, acta.id)
        if await consejo.fila_visible(db, f, acta, alcance)
    ]


async def _acta_visible(db: Db, acta_id: int, usuario: Usuario) -> consejo.Acta:
    acta = await consejo.get_acta(db, acta_id)
    alcance = _alcance(usuario)
    if acta is None or (alcance is not None and acta.direccion not in (None, alcance)):
        raise HTTPException(404, "No encontré esa acta.")
    return acta


async def _detalle_acta(
    db: Db, acta: consejo.Acta, usuario: Usuario
) -> dict[str, object]:
    alcance = _alcance(usuario)
    texto = await consejo.texto_acta(db, acta.id)
    filas = []
    for f in await _filas_visibles(db, acta, alcance):
        candidatos = []
        ajenos = False
        for i in f.candidatos:
            c = await repo.get_caso(db, i)
            if c is not None and (alcance is None or c.direccion == alcance):
                candidatos.append(_caso_corto(c))
            elif c is not None:
                ajenos = True
        caso = await repo.get_caso(db, f.caso_id) if f.caso_id else None
        if caso is not None and alcance is not None and caso.direccion != alcance:
            caso = None
            ajenos = True
        leida = f.leida.model_dump(mode="json")
        if ajenos:
            # Puede ser de un caso de otra área: solo se muestra la decisión y
            # los datos del candidato de su área, no lo que dice el acta.
            leida = {
                **{k: None for k in leida},
                "texto_decision": f.leida.texto_decision,
                "fragmento": "",
            }
        filas.append(
            {
                "id": f.id,
                "orden": f.orden,
                "leida": leida,
                "oculta": ajenos,
                "asignable": f.cruce != Cruce.NO_VERIFICADO
                or consejo.asignable_a_mano(f, texto),
                "sentido": f.sentido.value,
                "sentido_texto": ETIQUETA_SENTIDO_CONSEJO[f.sentido],
                "cruce": f.cruce.value,
                "motivo": f.motivo,
                "estado": f.estado.value,
                "revisado_por": f.revisado_por,
                "caso": _caso_corto(caso),
                "candidatos": candidatos,
            }
        )
    grupos: dict[str, list[dict[str, object]]] = {
        "cruzaron": [],
        "en_duda": [],
        "sin_caso": [],
    }
    for fila in filas:
        cruce = fila["cruce"]
        if cruce == Cruce.EXACTO.value:
            grupos["cruzaron"].append(fila)
        elif cruce == Cruce.SIN_CASO.value:
            grupos["sin_caso"].append(fila)
        else:
            grupos["en_duda"].append(fila)
    faltantes = await consejo.no_aparecieron(db, acta.id, alcance or acta.direccion)
    return {
        "id": acta.id,
        "instancia": acta.instancia.value,
        "instancia_texto": NOMBRE_INSTANCIA[acta.instancia],
        "numero": acta.numero,
        "fecha": acta.fecha,
        "archivo": acta.archivo_nombre,
        "subido_por": acta.subido_por,
        "creado": acta.creado,
        "pendientes": sum(
            1 for f in filas if f["estado"] == EstadoDecision.PENDIENTE.value
        ),
        **grupos,
        "no_aparecieron": [_caso_corto(c) for c in faltantes],
    }


@router.get("/consejo")
async def actas_consejo(usuario: _ActaConsejo, db: Db) -> dict[str, object]:
    alcance = _alcance(usuario)
    sql = "SELECT id FROM actas_consejo"
    params: tuple[object, ...] = ()
    if alcance is not None:
        sql += " WHERE direccion IS NULL OR direccion = ?"
        params = (alcance,)
    cur = await db.execute(sql + " ORDER BY id DESC LIMIT 30", params)
    actas = []
    for (acta_id,) in await cur.fetchall():
        acta = await consejo.get_acta(db, int(acta_id))
        if acta is None:
            continue
        filas = await _filas_visibles(db, acta, alcance)
        if not filas and acta.direccion is None and alcance is not None:
            continue  # acta de admin sin nada de su área
        actas.append(
            {
                "id": acta.id,
                "instancia_texto": NOMBRE_INSTANCIA[acta.instancia],
                "numero": acta.numero,
                "fecha": acta.fecha,
                "archivo": acta.archivo_nombre,
                "decisiones": len(filas),
                "pendientes": sum(
                    1 for f in filas if f.estado == EstadoDecision.PENDIENTE
                ),
            }
        )
    return {
        "actas": actas,
        "instancias": [
            {"clave": i.value, "nombre": NOMBRE_INSTANCIA[i]} for i in Instancia
        ],
    }


@router.post("/consejo")
async def subir_acta_consejo(
    usuario: _ActaConsejo,
    db: Db,
    archivo: Annotated[UploadFile, File()],
    instancia: Annotated[Instancia | None, Form()] = None,
) -> dict[str, object]:
    """Lee el acta y propone el cruce. No registra nada en los casos."""
    datos = await archivo.read(20 * 1024 * 1024 + 1)
    try:
        registrada = await consejo.leer_y_registrar(
            db,
            datos=datos,
            nombre_archivo=archivo.filename or "acta.pdf",
            direccion=_alcance(usuario),
            instancia=instancia,
            subido_por=_persona(usuario),
        )
    except consejo.ErrorActa as exc:
        raise HTTPException(400, str(exc)) from exc
    acta = await _acta_visible(db, registrada.acta_id, usuario)
    return await _detalle_acta(db, acta, usuario)


@router.get("/consejo/{acta_id}")
async def ver_acta_consejo(
    acta_id: int, usuario: _ActaConsejo, db: Db
) -> dict[str, object]:
    return await _detalle_acta(db, await _acta_visible(db, acta_id, usuario), usuario)


class Confirmacion(BaseModel):
    caso_id: int | None = None
    # Confirmación explícita para reemplazar una decisión final ya registrada.
    reemplazar: bool = False


@router.post("/consejo/{acta_id}/decisiones/{decision_id}/confirmar")
async def confirmar_decision(
    acta_id: int,
    decision_id: int,
    cuerpo: Confirmacion,
    usuario: _ActaConsejo,
    db: Db,
) -> dict[str, object]:
    """Una persona confirma que la decisión del acta corresponde al caso."""
    acta = await _acta_visible(db, acta_id, usuario)
    if decision_id not in {
        f.id for f in await consejo.decisiones_del_acta(db, acta.id)
    }:
        raise HTTPException(404, "Esa decisión no es de esta acta.")
    try:
        await consejo.aplicar(
            db,
            decision_id,
            caso_id=cuerpo.caso_id,
            persona=_persona(usuario),
            direccion=_alcance(usuario),
            reemplazar=cuerpo.reemplazar,
            rol=usuario.rol,
        )
    except consejo.ErrorActa as exc:
        raise HTTPException(409, str(exc)) from exc
    return await _detalle_acta(db, acta, usuario)


@router.post("/consejo/{acta_id}/decisiones/{decision_id}/descartar")
async def descartar_decision(
    acta_id: int, decision_id: int, usuario: _ActaConsejo, db: Db
) -> dict[str, object]:
    acta = await _acta_visible(db, acta_id, usuario)
    if decision_id not in {
        f.id for f in await consejo.decisiones_del_acta(db, acta.id)
    }:
        raise HTTPException(404, "Esa decisión no es de esta acta.")
    try:
        await consejo.descartar(
            db, decision_id, persona=_persona(usuario), direccion=_alcance(usuario)
        )
    except consejo.ErrorActa as exc:
        raise HTTPException(409, str(exc)) from exc
    return await _detalle_acta(db, acta, usuario)


@router.post("/consejo/{acta_id}/confirmar-exactos")
async def confirmar_exactos(
    acta_id: int, usuario: _ActaConsejo, db: Db
) -> dict[str, object]:
    acta = await _acta_visible(db, acta_id, usuario)
    try:
        await consejo.aplicar_exactos(
            db,
            acta.id,
            persona=_persona(usuario),
            direccion=_alcance(usuario),
            rol=usuario.rol,
        )
    except consejo.ErrorActa as exc:
        raise HTTPException(409, str(exc)) from exc
    return await _detalle_acta(db, acta, usuario)


# ---------------------------------------------------------------------------
# Tablero
# ---------------------------------------------------------------------------


@router.get("/tablero")
async def tablero(_: _Lectura, db: Db) -> dict[str, object]:
    """Solo conteos por área: sin nombres de estudiantes."""
    cur = await db.execute(
        "SELECT direccion, estado, sentido, COUNT(*) FROM casos"
        " WHERE estado != ? GROUP BY direccion, estado, sentido",
        (EstadoCaso.DESCARTADO.value,),
    )
    por_area: dict[str, dict[str, int]] = {}
    for direccion, estado, sentido, n in await cur.fetchall():
        c = por_area.setdefault(
            direccion,
            {
                "recibidos": 0,
                "en_curso": 0,
                "recomendar_aprobar": 0,
                "recomendar_no_aprobar": 0,
            },
        )
        c["recibidos"] += n
        if estado in (
            EstadoCaso.ABIERTO.value,
            EstadoCaso.PROCESANDO.value,
            EstadoCaso.LISTO.value,
        ):
            c["en_curso"] += n
        if sentido == Sentido.APROBAR.value:
            c["recomendar_aprobar"] += n
        elif sentido == Sentido.NO_APROBAR.value:
            c["recomendar_no_aprobar"] += n
    total = {
        k: sum(c[k] for c in por_area.values())
        for k in (
            "recibidos",
            "en_curso",
            "recomendar_aprobar",
            "recomendar_no_aprobar",
        )
    }
    return {
        "servicio": "actas",
        "titulo": "Comités asesores: casos estudiantiles",
        "total": total,
        "por_programa": [
            {"nombre": DIRECCIONES[d].nombre if d in DIRECCIONES else d, "conteo": c}
            for d, c in sorted(por_area.items())
        ],
    }


# ---------------------------------------------------------------------------
# Indicadores (solo cifras): decanatura y admin ven la Facultad; cada
# administrativa, solo su área.
# ---------------------------------------------------------------------------

_Indicadores = Annotated[
    Usuario, Depends(auth.requiere("administrativa", "decanatura", "admin"))
]


async def _reporte_indicadores(
    usuario: Usuario, db: Db, periodo: str
) -> indicadores.Reporte:
    alcance = _direccion(usuario) if usuario.rol == "administrativa" else None
    hoy = indicadores.hoy_local()
    try:
        elegido = indicadores.periodo_de(periodo, hoy)
    except indicadores.PeriodoInvalido as exc:
        raise HTTPException(422, str(exc)) from None
    return await indicadores.reporte(db, elegido, hoy, alcance)


@router.get("/indicadores")
async def ver_indicadores(
    usuario: _Indicadores, db: Db, periodo: str = ""
) -> dict[str, object]:
    return indicadores.a_json(await _reporte_indicadores(usuario, db, periodo))


@router.get("/indicadores/xlsx")
async def descargar_indicadores(
    usuario: _Indicadores, db: Db, periodo: str = ""
) -> Response:
    reporte = await _reporte_indicadores(usuario, db, periodo)
    try:
        contenido = indicadores.xlsx(reporte)
    except indicadores.ConfigIndicadoresError:
        raise HTTPException(
            503, "No se pudo armar el Excel: revise config/indicadores.yaml."
        ) from None
    return Response(
        content=contenido,
        media_type=indicadores.MIME_XLSX,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{indicadores.nombre_xlsx(reporte)}"'
            )
        },
    )


# ---------------------------------------------------------------------------
# Datos SUIT (trimestrales) de la Secretaría de Facultad: solo cifras de toda
# la Facultad, para decanatura y admin.
# ---------------------------------------------------------------------------

# La Secretaría de Facultad es quien reporta el SUIT.
_Suit = Annotated[Usuario, Depends(auth.requiere("secretaria", "decanatura", "admin"))]


@router.get("/suit/xlsx")
async def descargar_suit(_: _Suit, db: Db, ano: str = "") -> Response:
    try:
        elegido = suit.ano_de(ano, indicadores.hoy_local())
    except suit.AnoInvalido as exc:
        raise HTTPException(422, str(exc)) from None
    r = await suit.reporte(db, elegido, indicadores.hoy_local())
    return Response(
        content=suit.xlsx(r),
        media_type=suit.MIME_XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{suit.nombre_xlsx(r)}"'
        },
    )
