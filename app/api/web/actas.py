"""API web del servicio de actas. Solo se monta con BOT_SERVICIO=actas.

La administrativa y el comité ven solo los casos de su área curricular. El
comité nunca aprueba: se registra «Recomendar aprobar» o «Recomendar no
aprobar», y decide el Consejo.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.web import auth
from app.api.web.auth import Db, Usuario
from app.core import solicitudes
from app.core.config import settings
from app.core.programas import DIRECCIONES, PROGRAMAS, programas_de
from app.db import repo
from app.schemas.caso import TITULOS_TIPO, Caso, EstadoCaso, Sentido
from app.schemas.consejo import (
    ETIQUETA_SENTIDO_CONSEJO,
    NOMBRE_INSTANCIA,
    Cruce,
    EstadoDecision,
    Instancia,
)
from app.services import borrador, casos, consejo, indicadores, suit

router = APIRouter(prefix="/actas")

_Administrativa = Annotated[Usuario, Depends(auth.requiere("administrativa"))]
_Area = Annotated[Usuario, Depends(auth.requiere("administrativa", "comite"))]
_Lectura = Annotated[Usuario, Depends(auth.requiere("decanatura", "admin"))]
_ActaConsejo = Annotated[Usuario, Depends(auth.requiere("administrativa", "admin"))]

_IMAGENES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_MAX_IMAGEN = 10_000_000
_MAX_IMAGENES = 12

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
    programa = PROGRAMAS.get(caso.programa or "")
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
        "miembros": [m.nombre for m in programa.miembros] if programa else [],
        "programas": [
            {"clave": p.clave, "nombre": p.nombre} for p in programas_de(caso.direccion)
        ],
        "imagenes": len(caso.imagenes),
        "anexos": caso.anexos_archivos,
    }


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------


@router.get("/casos")
async def listar(usuario: _Area, db: Db) -> dict[str, object]:
    direccion = _direccion(usuario)
    recientes = await repo.casos_recientes(db, direccion=direccion, limite=50)
    return {
        "area": DIRECCIONES[direccion].nombre,
        "casos": [_resumen(c) for c in recientes],
    }


@router.post("/casos")
async def crear(
    usuario: _Administrativa,
    db: Db,
    texto: Annotated[str, Form()] = "",
    imagenes: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, object]:
    """Crea un caso con el texto del correo y los pantallazos del SIA."""
    direccion = _direccion(usuario)
    archivos = imagenes or []
    if not texto.strip() and not archivos:
        raise HTTPException(400, "Pegue el correo o adjunte al menos un pantallazo.")
    if len(archivos) > _MAX_IMAGENES:
        raise HTTPException(400, f"Adjunte máximo {_MAX_IMAGENES} pantallazos.")
    leidos: list[tuple[bytes, str]] = []
    for a in archivos:
        ext = _IMAGENES.get(a.content_type or "")
        if ext is None:
            raise HTTPException(
                400, f"«{a.filename}» no es una imagen JPG, PNG o WEBP."
            )
        datos = await a.read(_MAX_IMAGEN + 1)
        if len(datos) > _MAX_IMAGEN:
            raise HTTPException(400, f"«{a.filename}» pesa más de 10 MB.")
        leidos.append((datos, ext))
    caso_id = await repo.crear_caso(db, chat_id=0, user_id=0, direccion=direccion)
    if texto.strip():
        await repo.agregar_texto(db, caso_id, texto.strip())
    carpeta = settings.media_dir / str(caso_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    for datos, ext in leidos:
        unico = "web_" + hashlib.sha256(datos).hexdigest()[:24]
        ruta = carpeta / f"{unico}{ext}"
        ruta.write_bytes(datos)
        await repo.agregar_archivo(
            db,
            caso_id,
            tipo="imagen",
            ruta=str(ruta),
            nombre=None,
            file_unique_id=unico,
        )
    return {"id": caso_id}


@router.get("/casos/{caso_id}")
async def ver(caso_id: int, usuario: _Area, db: Db) -> dict[str, object]:
    return _detalle(await _caso_del_area(db, caso_id, usuario))


@router.post("/casos/{caso_id}/procesar")
async def procesar(caso_id: int, usuario: _Administrativa, db: Db) -> dict[str, object]:
    caso = await _caso_del_area(db, caso_id, usuario)
    if caso.estado not in (EstadoCaso.ABIERTO, EstadoCaso.ERROR, EstadoCaso.PROCESANDO):
        return _detalle(caso)
    if not caso.texto.strip() and not caso.imagenes:
        raise HTTPException(400, "El caso está vacío.")
    resultado = await casos.procesar(db, caso)
    if resultado.error is not None:
        raise HTTPException(
            502, f"No pude leer el caso: {resultado.error}. Puede intentarlo de nuevo."
        )
    return _detalle(resultado.caso)


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
    return _detalle(resultado.caso)


class Recomendacion(BaseModel):
    sentido: Sentido


@router.post("/casos/{caso_id}/recomendacion")
async def recomendar(
    caso_id: int, cuerpo: Recomendacion, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    """Registra lo que recomendó el comité. Lo decide una persona, no el modelo."""
    caso = await _caso_del_area(db, caso_id, usuario)
    await repo.set_sentido(db, caso.id, cuerpo.sentido)
    return _detalle(await _caso_del_area(db, caso_id, usuario))


@router.post("/casos/{caso_id}/nota")
async def nota(
    caso_id: int, cuerpo: Texto, usuario: _Administrativa, db: Db
) -> dict[str, object]:
    caso = await _caso_del_area(db, caso_id, usuario)
    await repo.set_nota(db, caso.id, cuerpo.texto.strip()[:1500] or None)
    return _detalle(await _caso_del_area(db, caso_id, usuario))


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
    return _detalle(await _caso_del_area(db, caso_id, usuario))


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
    return _detalle(await _caso_del_area(db, caso_id, usuario))


# ---------------------------------------------------------------------------
# Oficio y acta
# ---------------------------------------------------------------------------


@router.get("/documentos")
async def documentos(usuario: _Administrativa, db: Db) -> dict[str, object]:
    """Programas con casos listos para el borrador de oficio y acta."""
    listos = await repo.casos_listos(db, direccion=_direccion(usuario))
    programas = sorted({c.programa for c in listos if c.programa in PROGRAMAS})
    return {
        "programas": [
            {
                "clave": p,
                "nombre": PROGRAMAS[p].nombre,
                "casos": sum(1 for c in listos if c.programa == p),
            }
            for p in programas
        ],
        "sin_programa": [c.id for c in listos if c.programa not in PROGRAMAS],
    }


@router.get("/documentos/{programa}/{tipo}")
async def descargar(
    programa: str, tipo: str, usuario: _Administrativa, db: Db
) -> Response:
    if tipo not in ("oficio", "acta"):
        raise HTTPException(404, "Documento desconocido.")
    borradores, _ = await borrador.armar_borradores(
        db,
        direccion=_direccion(usuario),
        elaboro=usuario.nombre,
        solo_con_cambios=False,
    )
    elegido = next((b for b in borradores if b.programa.clave == programa), None)
    if elegido is None:
        raise HTTPException(404, "No hay casos listos para ese programa.")
    archivo = elegido.oficio if tipo == "oficio" else elegido.acta
    return Response(
        archivo.docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{archivo.ruta_docx.name}"'
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
            db, acta.id, persona=_persona(usuario), direccion=_alcance(usuario)
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

_Facultad = Annotated[Usuario, Depends(auth.requiere("decanatura", "admin"))]


@router.get("/suit/xlsx")
async def descargar_suit(_: _Facultad, db: Db, ano: str = "") -> Response:
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
