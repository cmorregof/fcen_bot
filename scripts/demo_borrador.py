"""Borrador de ejemplo con casos ficticios, sin modelo ni Telegram.

Uso:
    uv run python scripts/demo_borrador.py [programa]

Escribe out/demo_<programa>.docx y, si LibreOffice está instalado, el PDF.
Los nombres, documentos y cifras son inventados.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.programas import PROGRAMAS
from app.schemas.caso import (
    AsignaturaSolicitada,
    Caso,
    Concepto,
    DatosSIA,
    EstadoCaso,
    ExtraccionCaso,
    FilaCreditos,
    Sentido,
    TipoSolicitud,
)
from app.services.documento import (
    CasoDocumento,
    DatosOficio,
    construir_acta,
    construir_oficio,
)
from app.services.pdf import docx_a_pdf
from app.services.reglas import analizar

OUT = Path("out")


def pantallazo_ficticio(ruta: Path, filas: list[FilaCreditos]) -> None:
    ancho, alto_fila = 1100, 26
    im = Image.new("RGB", (ancho, alto_fila * (len(filas) + 3)), "white")
    d = ImageDraw.Draw(im)
    d.text((10, 6), "Resumen de créditos (EJEMPLO FICTICIO)", fill=(60, 60, 60))
    y = alto_fila + 4
    d.rectangle((0, y, ancho, y + alto_fila), fill=(122, 25, 40))
    cols = [
        "TIPOLOGÍAS",
        "EXIGIDOS",
        "APROBADOS",
        "PENDIENTES",
        "INSCRITOS",
        "CURSADOS",
    ]
    xs = [10, 330, 480, 630, 780, 930]
    for x, c in zip(xs, cols, strict=True):
        d.text((x, y + 7), c, fill="white")
    for i, f in enumerate(filas):
        y = alto_fila * (i + 2) + 4
        if i % 2:
            d.rectangle((0, y, ancho, y + alto_fila), fill=(245, 245, 245))
        valores = [
            f.tipologia,
            f.exigidos,
            f.aprobados,
            f.pendientes,
            f.inscritos,
            f.cursados,
        ]
        for x, v in zip(xs, valores, strict=True):
            d.text((x, y + 7), str(v), fill="black")
    im.save(ruta)


def filas_fisica() -> list[FilaCreditos]:
    datos = [
        ("DISCIPLINAR OPTATIVA", 12, 9, 3, 3, 9),
        ("FUND. OBLIGATORIA", 66, 66, 0, 0, 66),
        ("FUND. OPTATIVA", 12, 12, 0, 0, 12),
        ("DISCIPLINAR OBLIGATORIA", 40, 32, 8, 6, 32),
        ("LIBRE ELECCIÓN", 34, 30, 4, 3, 30),
        ("TRABAJO DE GRADO", 6, 0, 6, 0, 0),
        ("TOTAL", 170, 149, 21, 12, 149),
        ("NIVELACIÓN", 12, 12, 0, 0, 12),
        ("TOTAL ESTUDIANTE", 182, 161, 21, 12, 161),
    ]
    return [
        FilaCreditos(
            tipologia=t, exigidos=a, aprobados=b, pendientes=c, inscritos=d, cursados=e
        )
        for t, a, b, c, d, e in datos
    ]


def casos_ficticios(programa: str, img: Path) -> list[tuple[Caso, ExtraccionCaso, str]]:
    sia = DatosSIA(
        plan_codigo="4030",
        plan_nombre="INGENIERIA FISICA",
        periodo="2026-2S",
        papa=4.1,
        promedio_academico=4.2,
        porcentaje_avance=87.6,
        resumen_creditos=filas_fisica(),
    )
    correo1 = (
        "Estimados miembros del Comité Asesor,\n\nCordial saludo.\n\n"
        "Mi nombre es Andrea Ejemplo Ficticia, identificada con C.C. 1000000001. "
        "Solicito la inscripción de mi Trabajo de Grado en la modalidad de "
        "asignaturas de posgrado para el periodo 2026-2S, con excepción del "
        "requisito de créditos disciplinares, pues los que me faltan están "
        "inscritos este semestre.\n\nAgradezco su atención.\n\n"
        "Andrea Ejemplo Ficticia\nEstudiante de Ingeniería Física\nC.C. 1000000001"
    )
    e1 = ExtraccionCaso(
        nombre_estudiante="Andrea Ejemplo Ficticia",
        documento="1000000001",
        tratamiento="La estudiante",
        fecha_solicitud="2026-08-26",
        tipos=[TipoSolicitud.TRABAJO_GRADO, TipoSolicitud.EXCEPCION_NORMA],
        objeto_solicitud="inscripción extemporánea de la asignatura Trabajo de Grado "
        "en la modalidad de asignaturas de posgrado, con excepción del parágrafo del "
        "artículo 5 de la Resolución CFCEN-060-2008",
        modalidad_trabajo_grado="asignaturas de posgrado",
        asignaturas=[
            AsignaturaSolicitada(nombre="Componente ZAPC", accion="apertura"),
            AsignaturaSolicitada(
                codigo="4101167",
                nombre="Mecánica estadística avanzada",
                creditos=4,
                accion="inscribir",
            ),
            AsignaturaSolicitada(
                codigo="4101189",
                nombre="Fenómenos críticos y transiciones de fase",
                creditos=4,
                accion="inscribir",
            ),
        ],
        cuerpo_desde_linea=1,
        cuerpo_hasta_linea=12,
        justificacion_breve="Le faltan créditos disciplinares que está cursando este semestre.",
        sia=sia,
    )
    correo2 = (
        "Buenos días,\n\nSolicito cancelar la asignatura Termodinámica (4100849) y "
        "quedar por debajo de la carga mínima, porque debo trabajar más horas para "
        "sostener mis estudios.\n\nAtentamente,\n\nBruno Ejemplo Inventado\n"
        "C.C. 100000002"
    )
    e2 = ExtraccionCaso(
        nombre_estudiante="Bruno Ejemplo Inventado",
        documento="100000002",
        tratamiento="El estudiante",
        fecha_solicitud="2026-10-07",
        tipos=[TipoSolicitud.CARGA_MINIMA, TipoSolicitud.CANCELACION],
        objeto_solicitud="cancelación de la asignatura 4100849 Termodinámica y "
        "autorización para cursar el periodo por debajo de la carga mínima",
        asignaturas=[
            AsignaturaSolicitada(
                codigo="4100849", nombre="Termodinámica", creditos=4, accion="cancelar"
            )
        ],
        cuerpo_desde_linea=1,
        cuerpo_hasta_linea=9,
        anexos=["certificación laboral"],
        sia=sia.model_copy(update={"papa": 3.6, "porcentaje_avance": 74.1}),
    )
    casos = []
    for i, (extr, correo, sentido) in enumerate(
        ((e1, correo1, Sentido.APROBAR), (e2, correo2, Sentido.PENDIENTE)), start=1
    ):
        caso = Caso(
            id=i,
            chat_id=0,
            direccion="ciencias_naturales",
            programa=programa,
            estado=EstadoCaso.LISTO,
            sentido=sentido,
            texto=correo,
            imagenes=[str(img)],
            extraccion=extr,
        )
        casos.append((caso, extr, correo))
    return casos


async def main() -> None:
    clave = sys.argv[1] if len(sys.argv) > 1 else "ing_fisica"
    programa = PROGRAMAS[clave]
    OUT.mkdir(exist_ok=True)
    img = OUT / "pantallazo_ficticio.png"
    pantallazo_ficticio(img, filas_fisica())
    items = []
    for caso, extr, correo in casos_ficticios(clave, img):
        analisis = analizar(
            extr, programa, periodo_inicio=date(2026, 8, 3), hay_imagenes=True
        )
        for alerta in analisis.alertas:
            print(f"  caso {caso.id} [{alerta.nivel}] {alerta.mensaje}")
        items.append(CasoDocumento(caso, extr, analisis, correo.strip(), [img]))
    # Un concepto ficticio en el primer caso, para ver cómo queda en el acta.
    if items and programa.miembros:
        m = programa.miembros[-1]
        items[0].caso.conceptos = [
            Concepto(
                miembro=m.nombre,
                tratamiento=m.tratamiento,
                texto="Recomiendo aprobar la solicitud.\n\nLa estudiante cumple "
                "los requisitos y presentó los soportes a tiempo.",
            )
        ]
    datos = DatosOficio(
        programa=programa,
        fecha=date(2026, 10, 13),
        casos=items,
        elaboro="FCEN",
        miembros=programa.miembros,
    )
    for nombre, docx in (
        (f"demo_oficio_{clave}", construir_oficio(datos, "2026-2S")),
        (f"demo_acta_{clave}", construir_acta(datos, "2026-2S")),
    ):
        (OUT / f"{nombre}.docx").write_bytes(docx)
        print(f"Escrito {OUT / f'{nombre}.docx'}")
        pdf = await docx_a_pdf(docx)
        if pdf:
            (OUT / f"{nombre}.pdf").write_bytes(pdf)
            print(f"Escrito {OUT / f'{nombre}.pdf'}")


if __name__ == "__main__":
    asyncio.run(main())
