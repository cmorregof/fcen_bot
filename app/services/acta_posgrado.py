"""Acta del Comité Asesor de Posgrados del Área Curricular de Ciencias Exactas.

El formato visual es el del acta de pregrado (la plantilla y los estilos
«FCEN …» de app/services/documento.py). La estructura es la de las actas 022
a 029 de 2026 de ese comité:

1. Encabezado: universidad, sede, comité y «ACTA-NNN»; FECHA, HORA y LUGAR.
2. MIEMBROS DEL COMITÉ ASISTENTES: «Profesor NOMBRE, en calidad de cargo;».
3. ORDEN DEL DÍA: un punto por solicitud.
4. DESARROLLO: párrafo de apertura, los programas de las solicitudes y un
   punto numerado por solicitud con su título en mayúsculas, la presentación
   del caso, los datos propios del trámite (cursos, evento, tesis, jurados o
   evaluadores, programa de destino), la justificación del estudiante, los
   conceptos de los integrantes y la RECOMENDACIÓN.
5. La firma del director, sin «Varios» ni verificación del quórum.

Nada de esto llama al modelo: todo sale de los datos ya registrados. El
sentido de la recomendación lo registra una persona; si falta, queda
«[APROBAR / NO APROBAR]» en amarillo. Inventario: docs/solicitudes-posgrado.md.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace

from docx.document import Document as DocumentoDocx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph

from app.core.programas import PROGRAMAS, normalizar
from app.normativa.base import normas_para
from app.schemas.caso import (
    TIPOS_CON_TRABAJO,
    AsignaturaSolicitada,
    Jurado,
    Sentido,
    TipoSolicitud,
)
from app.services.documento import (
    CasoDocumento,
    DatosOficio,
    _analisis,
    _bloque_firma,
    _bloques,
    _conceptos,
    _documento,
    _equivalencias,
    _guardar,
    _linea_dato,
    _marcador,
    _normas,
    _p,
    _r,
    _texto_con_saltos,
    _vacio,
    fecha_larga,
    programa_del_caso,
    texto_recomendacion,
    titulo_seccion,
)
from app.services.reglas import es_asunto_programa

_ACCION = {"inscribir": "inscribir", "cancelar": "cancelar"}

_ROTULO_JURADOS = {
    TipoSolicitud.SUSTENTACION_TESIS: "Jurados evaluadores",
    TipoSolicitud.CALIFICACION_TRABAJO_FINAL: "Evaluador",
    TipoSolicitud.NOMBRAMIENTO_EVALUADORES: (
        "Evaluadores puestos a consideración del Comité"
    ),
}


_NIVELES = ("doctorado", "maestria", "especializacion")


def _orden_programa(clave: str | None) -> tuple[int, int]:
    """Doctorado, maestrías y especializaciones, como en las actas; dentro de
    cada nivel, el orden de programas.py. Sin programa, al final."""
    programa = PROGRAMAS.get(clave or "")
    if programa is None:
        return (len(_NIVELES), 0)
    nombre = normalizar(programa.nombre)
    nivel = next(
        (i for i, n in enumerate(_NIVELES) if nombre.startswith(n)), len(_NIVELES)
    )
    return (nivel, list(PROGRAMAS).index(programa.clave))


def ordenados(datos: DatosOficio) -> list[CasoDocumento]:
    """Las solicitudes agrupadas por programa; dentro de cada programa, en el
    orden en que llegaron."""
    return sorted(datos.casos, key=lambda item: _orden_programa(item.caso.programa))


def periodo_del_caso(item: CasoDocumento) -> str | None:
    e = item.extraccion
    if e.periodo_solicitado:
        return e.periodo_solicitado.strip()
    if e.sia and e.sia.periodo:
        return e.sia.periodo.strip()
    return None


def titulo_punto(datos: DatosOficio, item: CasoDocumento) -> str:
    """«SOLICITUD DE CANCELACIÓN DE CURSOS – DOCTORADO EN … 2026-2S»."""
    titulo = titulo_seccion(item.extraccion, posgrado=True)
    programa = programa_del_caso(datos, item)
    if programa:
        titulo += f" – {programa.upper()}"
    periodo = periodo_del_caso(item)
    if periodo:
        titulo += f" {periodo.upper()}"
    return titulo


def _dato(
    doc: DocumentoDocx, rotulo: str, valor: str | None, falta: str | None = None
) -> None:
    """«Rótulo: valor». Sin valor: el marcador `falta` en amarillo o nada."""
    if not (valor or "").strip() and falta is None:
        return
    p = _p(doc, "FCEN Cuerpo")
    _r(p, f"{rotulo}: ", negrita=True)
    if (valor or "").strip():
        _r(p, (valor or "").strip())
    else:
        _marcador(p, falta or "")


def _vineta(doc: DocumentoDocx, texto: str) -> Paragraph:
    return _p(doc, "FCEN Vineta", f"•\t{texto}")


def _entre_comillas(texto: str | None) -> str | None:
    texto = (texto or "").strip().strip('“”"«»')
    return f"“{texto}”" if texto else None


# ---------------------------------------------------------------------------
# Encabezado
# ---------------------------------------------------------------------------


def _encabezado(
    doc: DocumentoDocx, datos: DatosOficio, items: list[CasoDocumento]
) -> None:
    if datos.borrador:
        p = _p(doc, "FCEN Destinatario")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = _r(p, "BORRADOR · pendiente de revisión del Comité Asesor", negrita=True)
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0xB0, 0x00, 0x20)
        _vacio(doc)

    for linea in (
        "UNIVERSIDAD NACIONAL DE COLOMBIA",
        "SEDE MANIZALES",
        datos.programa.comite.upper(),
    ):
        _p(
            doc, "FCEN Destinatario", linea, negrita=True
        ).alignment = WD_ALIGN_PARAGRAPH.CENTER
    _vacio(doc)
    p = _p(doc, "FCEN Destinatario")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p, "ACTA-", negrita=True)
    if datos.numero_acta:
        _r(p, datos.numero_acta, negrita=True)
    else:
        _marcador(p, "[No.]")
    _vacio(doc, "FCEN Texto")

    _linea_dato(
        doc,
        "FECHA",
        datos.fecha_sesion and f"Manizales, {datos.fecha_sesion}",
        f"Manizales, {fecha_larga(datos.fecha)}",
    )
    _linea_dato(doc, "HORA", datos.hora, "[hora]")
    _linea_dato(doc, "LUGAR", datos.lugar, "[lugar o «sesión no presencial»]")
    _vacio(doc, "FCEN Texto")

    _p(doc, "FCEN Texto", "MIEMBROS DEL COMITÉ ASISTENTES:", negrita=True)
    if datos.miembros:
        # «Profesor NOMBRE, en calidad de cargo;», como en el acta 029.
        for i, m in enumerate(datos.miembros, start=1):
            p = _p(doc, "FCEN Vineta", "•\t")
            titulo = m.tratamiento.removeprefix("El ").removeprefix("La ")
            if titulo:
                _r(p, f"{titulo.capitalize()} ")
            if m.nombre:
                _r(p, m.nombre.upper())
            else:
                _marcador(p, "[nombre]")
            fin = "." if i == len(datos.miembros) else ";"
            _r(p, f", en calidad de {m.cargo}{fin}")
    else:
        _marcador(_p(doc, "FCEN Vineta"), "[Integrantes del comité, con su cargo]")
    _vacio(doc, "FCEN Texto")

    _p(doc, "FCEN Texto", "ORDEN DEL DÍA:", negrita=True)
    for n, item in enumerate(items, start=1):
        e = item.extraccion
        titulo = titulo_seccion(e, posgrado=True).capitalize()
        programa = programa_del_caso(datos, item)
        if es_asunto_programa(e):
            quien = programa or ""
        else:
            nombre = (e.nombre_estudiante or "____").title()
            quien = f"{nombre} ({programa})" if programa else nombre
        _p(doc, "FCEN Vineta", f"{n})\t{titulo}" + (f": {quien}" if quien else ""))
    if not items:
        _marcador(_p(doc, "FCEN Vineta"), "[Sin solicitudes]")
    _vacio(doc, "FCEN Texto")

    _p(doc, "FCEN Texto", "DESARROLLO:", negrita=True)
    p = _p(doc, "FCEN Cuerpo")
    _r(p, f"El {datos.programa.comite}, en sesión realizada el ")
    if datos.fecha_sesion:
        _r(p, datos.fecha_sesion)
    else:
        _marcador(p, fecha_larga(datos.fecha))
    _r(p, ", según Acta ")
    if datos.numero_acta:
        numero = datos.numero_acta
        _r(p, str(int(numero)) if numero.isdigit() else numero)
    else:
        _marcador(p, "[No.]")
    _r(
        p,
        f" de {datos.fecha.year}, estudió las solicitudes que se relacionan a "
        "continuación, de acuerdo con su respectivo programa curricular.",
    )
    programas = list(
        OrderedDict.fromkeys(
            prog for item in items if (prog := programa_del_caso(datos, item))
        )
    )
    if programas:
        _p(
            doc,
            "FCEN Cuerpo",
            "Las solicitudes corresponden a los siguientes programas:"
            if len(programas) > 1
            else "La solicitud corresponde al siguiente programa:",
        )
        for prog in programas:
            _vineta(doc, prog)
    _p(
        doc,
        "FCEN Cuerpo",
        "A continuación, se relacionan las solicitudes de cada programa:",
    )
    _vacio(doc, "FCEN Cuerpo")


# ---------------------------------------------------------------------------
# Cada solicitud
# ---------------------------------------------------------------------------


def _presentacion(doc: DocumentoDocx, datos: DatosOficio, item: CasoDocumento) -> None:
    """«NOMBRE, identificado con DNI No. …, estudiante del …, solicita …»."""
    e = item.extraccion
    objeto = e.objeto_solicitud.strip().rstrip(".") or "lo que se transcribe"
    p = _p(doc, "FCEN Cuerpo")
    if es_asunto_programa(e):
        if (e.presenta or "").strip():
            _r(p, (e.presenta or "").strip())
        else:
            _marcador(p, "[quién presenta el asunto]")
        _r(p, f" presenta a consideración del Comité la solicitud de {objeto}.")
        return
    identificado = (
        "identificado" if e.tratamiento == "El estudiante" else "identificada"
    )
    _r(p, (e.nombre_estudiante or "____").upper(), negrita=True)
    _r(p, f", {identificado} con ")
    _r(p, f"DNI No. {e.documento or '____'}", negrita=True)
    programa = programa_del_caso(datos, item)
    if programa:
        reingreso = TipoSolicitud.REINGRESO in e.tipos
        persona = "exestudiante" if reingreso else "estudiante"
        articulo = "del" if programa.startswith("Doctorado") else "de la"
        _r(p, f", {persona} {articulo} {programa},")
    medio = "formato de solicitud" if item.medio == "formato" else "correo"
    _r(p, f" mediante {medio} del día {fecha_larga(e.fecha_solicitud)}, solicita ")
    _r(p, objeto)
    periodo = (e.periodo_solicitado or "").strip()
    if periodo and periodo.lower() not in objeto.lower():
        _r(p, f" para el periodo académico {periodo}")
    _r(p, ".")
    if (e.radicado_portal or "").strip():
        _p(
            doc,
            "FCEN Cuerpo",
            f"La solicitud se radicó con el número {(e.radicado_portal or '').strip()}.",
        )


def _cursos(doc: DocumentoDocx, asignaturas: list[AsignaturaSolicitada]) -> None:
    """Como en las actas: «Curso: nombre, código …, tipología …, N créditos»."""
    por_accion: OrderedDict[str, list[AsignaturaSolicitada]] = OrderedDict()
    for a in asignaturas:
        if a.accion in _ACCION:  # ZAPC va en la recomendación, no aquí (§5.4)
            por_accion.setdefault(a.accion, []).append(a)
    for accion, cursos in por_accion.items():
        plural = len(cursos) > 1
        _p(
            doc,
            "FCEN Cuerpo",
            f"{'Cursos' if plural else 'Curso'} que solicita {_ACCION[accion]}:",
            negrita=True,
        )
        for c in cursos:
            partes = [c.nombre]
            if c.codigo:
                partes.append(f"código {c.codigo}")
            if c.grupo:
                partes.append(f"grupo {c.grupo}")
            if c.tipologia:
                partes.append(f"tipología {c.tipologia}")
            if c.creditos is not None:
                partes.append(f"{c.creditos} crédito{'' if c.creditos == 1 else 's'}")
            _vineta(doc, ", ".join(partes) + ".")


def _eventos(doc: DocumentoDocx, item: CasoDocumento) -> None:
    for ev in item.extraccion.eventos:
        _dato(doc, "Evento", ev.nombre)
        _dato(doc, "En calidad de", ev.participacion)
        _dato(doc, "Fechas de participación", ev.fechas_participacion)
        _dato(doc, "Fechas de realización del evento", ev.fechas_evento)
        _dato(doc, "Lugar", ev.lugar)


def _trabajo(doc: DocumentoDocx, item: CasoDocumento) -> None:
    """Tesis o trabajo final: título, director, actividad, fechas, objetivos."""
    e = item.extraccion
    proyecto = e.proyecto
    exige = bool(set(e.tipos) & TIPOS_CON_TRABAJO)
    if proyecto is None:
        if exige:
            _dato(doc, "Título", None, "[título]")
            _dato(doc, "Director(a)", None, "[director]")
        return

    def falta(marcador: str) -> str | None:
        # Título y director son indispensables en un trámite de tesis.
        return marcador if exige else None

    if proyecto.titulo_anterior:
        _dato(doc, "Título anterior", _entre_comillas(proyecto.titulo_anterior))
        _dato(doc, "Título nuevo", _entre_comillas(proyecto.titulo), falta("[título]"))
    else:
        _dato(doc, "Título", _entre_comillas(proyecto.titulo), falta("[título]"))
    if proyecto.director_anterior:
        _dato(doc, "Director(a) anterior", proyecto.director_anterior)
        _dato(doc, "Director(a) nuevo(a)", proyecto.director, falta("[director]"))
    else:
        _dato(doc, "Director(a)", proyecto.director, falta("[director]"))
    _dato(doc, "Codirector(a)", proyecto.codirector)
    _dato(doc, "Línea de investigación", proyecto.linea)
    _dato(doc, "Actividad académica", proyecto.actividad)
    if proyecto.fecha_entrega:
        _dato(
            doc, "Fecha de entrega para evaluación", fecha_larga(proyecto.fecha_entrega)
        )
    if proyecto.fecha_sustentacion:
        _dato(doc, "Fecha de sustentación", fecha_larga(proyecto.fecha_sustentacion))
    _dato(doc, "Calificación emitida", proyecto.calificacion)
    _dato(doc, "Objetivo general", proyecto.objetivo_general)
    if proyecto.objetivos_especificos:
        _p(doc, "FCEN Cuerpo", "Objetivos específicos:", negrita=True)
        for objetivo in proyecto.objetivos_especificos:
            _vineta(doc, objetivo.strip())


def _linea_jurado(j: Jurado) -> str:
    return ", ".join(x for x in (j.nombre, j.vinculacion, j.correo) if x)


def _jurados(doc: DocumentoDocx, item: CasoDocumento) -> None:
    e = item.extraccion
    if not e.jurados:
        return
    rotulo = next(
        (r for t, r in _ROTULO_JURADOS.items() if t in e.tipos),
        "Jurados" if len(e.jurados) > 1 else "Jurado",
    )
    if rotulo == "Evaluador" and len(e.jurados) > 1:
        rotulo = "Evaluadores"
    _p(doc, "FCEN Cuerpo", f"{rotulo}:", negrita=True)
    for jurado in e.jurados:
        _vineta(doc, _linea_jurado(jurado))


def _datos_tramite(doc: DocumentoDocx, item: CasoDocumento) -> None:
    e = item.extraccion
    transito = TipoSolicitud.TRANSITO_POSGRADO in e.tipos
    _dato(
        doc,
        "Programa de destino",
        e.programa_destino,
        "[programa de destino]" if transito else None,
    )
    _cursos(doc, e.asignaturas)
    _eventos(doc, item)
    _trabajo(doc, item)
    _jurados(doc, item)
    _equivalencias(doc, e)


def _justificacion(doc: DocumentoDocx, item: CasoDocumento) -> None:
    """La cita del estudiante, literal; en amarillo si no se pudo verificar."""
    bloques = _bloques(item.cuerpo_correo)
    if not bloques:
        return
    rotulo = (
        "Texto de la solicitud"
        if es_asunto_programa(item.extraccion)
        else "Justificación emitida por el estudiante"
    )
    resaltar = not item.cita_verificada
    p = _p(doc, "FCEN Cuerpo")
    _r(p, f"{rotulo}: ", negrita=True)
    _r(p, "“")
    _texto_con_saltos(
        p,
        bloques[0] + ("”" if len(bloques) == 1 else ""),
        cursiva=True,
        resaltar=resaltar,
    )
    for i, bloque in enumerate(bloques[1:], start=2):
        cita = _p(doc, "FCEN Cita")
        if "\n" in bloque:  # firmas y listas: sin justificar
            cita.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _texto_con_saltos(
            cita,
            bloque + ("”" if i == len(bloques) else ""),
            cursiva=True,
            resaltar=resaltar,
        )


def _anexos(doc: DocumentoDocx, item: CasoDocumento) -> None:
    anexos = [a.strip() for a in item.extraccion.anexos if a.strip()]
    if not anexos:
        return
    if len(anexos) == 1:
        texto = anexos[0]
    else:
        texto = ", ".join(anexos[:-1]) + " y " + anexos[-1]
    _p(
        doc,
        "FCEN Cuerpo",
        f"Para el estudio de la solicitud se adjuntó: {texto}.",
    )


def _recomendacion(doc: DocumentoDocx, datos: DatosOficio, item: CasoDocumento) -> None:
    antes, sentido, despues = texto_recomendacion(datos.programa, item)
    p = _p(doc, "FCEN Cuerpo")
    _r(p, "RECOMENDACIÓN", negrita=True)
    _r(p, f": {antes}")
    pendiente = item.caso.sentido == Sentido.PENDIENTE
    r = _r(p, sentido, negrita=pendiente)
    if pendiente:
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    _r(p, despues)


def _punto(
    doc: DocumentoDocx,
    datos: DatosOficio,
    item: CasoDocumento,
    numero: int,
    periodo: str,
) -> None:
    p = _p(doc, "FCEN Texto", f"{numero}) {titulo_punto(datos, item)}", negrita=True)
    p.paragraph_format.space_before = Cm(0.2)
    _vacio(doc, "FCEN Cuerpo")
    _presentacion(doc, datos, item)
    _datos_tramite(doc, item)
    _justificacion(doc, item)
    _anexos(doc, item)
    _vacio(doc, "FCEN Cuerpo")
    if not es_asunto_programa(item.extraccion):
        # Los anexos ya van en la frase «Para el estudio de la solicitud…».
        sin_anexos = item.extraccion.model_copy(update={"anexos": []})
        _analisis(doc, replace(item, extraccion=sin_anexos), periodo, acta=True)
    _conceptos(doc, item.caso.conceptos, datos.borrador)
    _recomendacion(doc, datos, item)
    _vacio(doc, "FCEN Cuerpo")
    _normas(doc, normas_para(item.extraccion.tipos, item.caso.programa), datos.borrador)
    _vacio(doc, "FCEN Cuerpo")


def construir_acta_posgrado(datos: DatosOficio, periodo: str) -> bytes:
    """Acta del comité único de posgrados, con la estructura de sus actas."""
    doc = _documento(datos)
    items = ordenados(datos)
    _encabezado(doc, datos, items)
    for n, item in enumerate(items, start=1):
        _punto(doc, datos, item, n, periodo)
    _vacio(doc, "FCEN Firma", n=2)
    _bloque_firma(doc, datos)
    return _guardar(doc)
