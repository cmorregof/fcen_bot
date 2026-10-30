"""Borrador de avance de un corte: fuentes, citas, nombres y costo. Datos FICTICIOS."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from openpyxl import load_workbook
from pydantic import BaseModel

from app.servicios.calidad.avance import borrador as bor
from app.servicios.calidad.avance import fuentes, salidas
from app.servicios.calidad.avance import nombres as nm
from app.servicios.calidad.plan import PlanGuardado, Soporte
from app.servicios.calidad.soportes.cliente import Respuesta
from app.servicios.calidad.soportes.describir import Cache
from app.servicios.calidad.soportes.indice import guardar_indice, leer_indice
from app.servicios.calidad.soportes.modelos import (
    Archivo,
    Descripcion,
    DescripcionArchivo,
)
from tests.calidad.conftest import leer

CORTE = date(2026, 11, 30)
PERSONA = "Zoila Ficticia Pérez"


class ModeloFalso:
    """Redacta una frase por fuente nueva y cuenta las llamadas."""

    def __init__(self, frases: list[dict[str, Any]] | None = None) -> None:
        self.textos: list[str] = []
        self.frases = frases

    async def llamar(
        self,
        *,
        modelo: str,
        sistema: str,
        bloques: list[dict[str, Any]],
        texto: str,
        salida: type[BaseModel],
        nombre_herramienta: str,
        esfuerzo: str,
        max_tokens: int,
    ) -> Respuesta:
        self.textos.append(texto)
        if self.frases is not None:
            return Respuesta({"frases": self.frases}, 1000, 200, modelo=modelo)
        nuevas = re.findall(r"^\[(\w+)\] \(nueva en este corte\)", texto, re.M)
        frases = [{"texto": f"Se registró avance [{i}].", "citas": [i]} for i in nuevas]
        return Respuesta({"frases": frases}, 1000, 200, modelo=modelo)


def guardado(responsable: str | None = None) -> PlanGuardado:
    plan = leer()
    if responsable:
        plan.acciones[0].responsables = responsable
        plan.acciones[0].tareas[0].responsable = responsable
    return PlanGuardado(plan=plan, importacion_id=1, archivo="plan.xlsx")


def con_enlace(pg: PlanGuardado, codigo: str, url: str, creado: str) -> None:
    pg.soportes[codigo] = [
        Soporte(1, 1, "enlace", url, None, 0, "x@ejemplo.test", creado)
    ]


def armar(pg: PlanGuardado, **kw: Any) -> list[fuentes.AccionCorte]:
    return fuentes.armar(pg, CORTE, kw.get("soportes", {}), nm.nombres_en_plan(pg))


def accion(acciones: list[fuentes.AccionCorte], codigo: str) -> fuentes.AccionCorte:
    return next(a for a in acciones if a.accion.codigo == codigo)


async def correr(
    pg: PlanGuardado, modelo: ModeloFalso, tmp_path: Path, **kw: Any
) -> bor.Borrador:
    acciones = armar(pg, **kw)
    return await bor.generar(
        "Ejemplo",
        CORTE.isoformat(),
        acciones,
        nm.nombres_en_plan(pg),
        modelo,
        Cache(tmp_path / "c"),
    )


# ---------------------------------------------------------------------------


def test_apagado_por_defecto() -> None:
    from app.servicios.calidad.config import CalidadSettings

    assert CalidadSettings.model_fields["avance_activo"].default is False
    assert CalidadSettings.model_fields["avance_tope_usd"].default == 2.0


def test_fuentes_con_hoja_y_fila_del_plan() -> None:
    a = accion(armar(guardado()), "1.1.1")
    plan = [f for f in a.fuentes if f.tipo == "plan"]
    assert plan[0].ref == "«2. Plan de Mejora» fila 9"
    assert any(f.ref == "«3. Cronograma 2026» fila 8" for f in plan)
    assert [f.id for f in a.fuentes if f.tipo == "corte"] == ["C1", "C2"]
    # Lo viejo no es evidencia nueva: nada cambió desde el corte de mayo.
    assert not a.hay_evidencia_nueva


def test_enlace_registrado_despues_del_corte_anterior_es_nuevo() -> None:
    pg = guardado()
    con_enlace(pg, "1.1.1", "https://ejemplo.invalid/drive/nuevo", "2026-10-01T10:00")
    con_enlace(pg, "1.2.1", "https://ejemplo.invalid/drive/viejo", "2026-01-01T10:00")
    acciones = armar(pg)
    assert accion(acciones, "1.1.1").hay_evidencia_nueva
    assert not accion(acciones, "1.2.1").hay_evidencia_nueva
    enlace = next(f for f in accion(acciones, "1.1.1").fuentes if f.nueva)
    assert enlace.ref.startswith("https://ejemplo.invalid/drive/nuevo")


def test_soportes_del_revisor_se_leen_de_la_cache(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache")
    archivo = Archivo("S007", "x/a.pdf", "a.pdf", "1.1.2", "pdf", ".pdf", 10)
    desc = DescripcionArchivo(
        que_es="Acta ficticia",
        fecha_documento="2026-09",
        que_prueba="Una jornada con profesores",
        ilegible_o_incompleto=False,
        observacion="",
    )
    guardar_indice(
        cache, "Ejemplo Alfa", {"S007": Descripcion("S007", desc)}, [archivo]
    )
    soportes = leer_indice(cache, "ejemplo alfa")
    a = accion(armar(guardado(), soportes=soportes), "1.1.2")
    s = next(f for f in a.fuentes if f.id == "S007")
    assert s.tipo == "soporte" and a.hay_evidencia_nueva
    assert "a.pdf" not in s.texto  # el nombre del archivo no se manda
    assert leer_indice(cache, "Otro programa") == {}


async def test_citas_verificadas_y_lo_que_no_tiene_fuente_se_marca(
    tmp_path: Path,
) -> None:
    pg = guardado()
    con_enlace(pg, "1.1.1", "https://ejemplo.invalid/drive/nuevo", "2026-10-01T10:00")
    modelo = ModeloFalso(
        [
            {"texto": "Se publicó una pieza [P1, E1].", "citas": ["P1", "E1"]},
            {"texto": "Asistieron 40 personas.", "citas": []},
            {"texto": "Se aprobó el cierre [P99].", "citas": ["P99"]},
            {"texto": "Hay un acta [S555].", "citas": ["S555"]},
        ]
    )
    b = await correr(pg, modelo, tmp_path)
    a = next(x for x in b.acciones if x.base.accion.codigo == "1.1.1")
    assert [f.valida for f in a.frases] == [True, False, False, False]
    assert [f.motivo for f in a.rechazadas] == [
        bor.MOTIVO_SIN_CITA,
        bor.MOTIVO_CITA_INVALIDA,
        bor.MOTIVO_CITA_INVALIDA,
    ]
    assert a.parrafo == "Se publicó una pieza [P1, E1]."
    assert "40 personas" not in a.parrafo and a.citas == ["P1", "E1"]
    assert a.alertas


async def test_accion_sin_evidencia_no_llama_al_modelo_ni_inventa(
    tmp_path: Path,
) -> None:
    modelo = ModeloFalso()
    b = await correr(guardado(), modelo, tmp_path)
    assert modelo.textos == []
    for a in b.acciones:
        assert a.sin_evidencia_nueva
        assert a.parrafo.startswith(bor.SIN_EVIDENCIA_NUEVA)
        assert a.citas[0].startswith("P")
    assert b.resumen()["sin_evidencia_nueva"] == len(b.acciones)


async def test_sin_nombres_de_personas(tmp_path: Path) -> None:
    pg = guardado(PERSONA)
    con_enlace(pg, "1.1.1", "https://ejemplo.invalid/drive/nuevo", "2026-10-01T10:00")
    nombres = nm.nombres_en_plan(pg)
    assert PERSONA in nombres
    # Los cargos del resto del plan no se toman por nombres.
    assert not any("Dirección" in n or "Comité" in n for n in nombres)

    modelo = ModeloFalso(
        [
            {"texto": f"{PERSONA} publicó la pieza [P1].", "citas": ["P1"]},
            {"texto": "Escribir a ana@ejemplo.test [P1].", "citas": ["P1"]},
            {"texto": "El profesor Juan Gómez lo aprobó [P1].", "citas": ["P1"]},
            {
                "texto": "La dirección del programa publicó la pieza [E1].",
                "citas": ["E1"],
            },
        ]
    )
    b = await correr(pg, modelo, tmp_path)
    a = next(x for x in b.acciones if x.base.accion.codigo == "1.1.1")
    assert [f.valida for f in a.frases] == [False, False, False, True]
    assert all(f.motivo == bor.MOTIVO_NOMBRE for f in a.rechazadas)
    # Ni el prompt ni las fuentes llevan el nombre.
    assert PERSONA not in modelo.textos[0]
    assert all(PERSONA not in f.texto for f in a.base.fuentes)

    salidas.borrador_docx(tmp_path / "b.docx", b)
    salidas.revision_xlsx(tmp_path / "r.xlsx", b)
    # En las salidas el nombre aparece solo dentro de la frase rechazada.
    doc = Document(str(tmp_path / "b.docx"))
    texto = "\n".join(p.text for p in doc.paragraphs)
    assert "no se afirma" in texto and "La dirección del programa publicó" in texto
    propuesta = load_workbook(tmp_path / "r.xlsx")["Revisión del corte"]["E2"].value
    assert PERSONA not in propuesta and "ana@" not in propuesta


def test_el_prompt_no_manda_responsables_ni_correos() -> None:
    pg = guardado("Zoila Ficticia Pérez, zoila@ejemplo.test")
    a = accion(armar(pg), "1.1.1")
    prompt = bor.texto_para_modelo(a)
    assert "Zoila" not in prompt and "zoila@" not in prompt
    assert "Fuentes (cita solo estas)" in prompt


async def test_salidas_docx_y_xlsx(tmp_path: Path) -> None:
    pg = guardado()
    con_enlace(pg, "1.1.1", "https://ejemplo.invalid/drive/nuevo", "2026-10-01T10:00")
    b = await correr(pg, ModeloFalso(), tmp_path)
    salidas.borrador_docx(tmp_path / "b.docx", b)
    salidas.revision_xlsx(tmp_path / "r.xlsx", b)

    doc = Document(str(tmp_path / "b.docx"))
    assert doc.sections[0].header.paragraphs[0].text.startswith("BORRADOR — propuesta")
    assert doc.paragraphs[0].text.startswith("BORRADOR — propuesta")
    titulos = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert any(t.startswith("Objetivo 1.") for t in titulos)
    assert any(t.startswith("Acción 1.1.1") for t in titulos)
    texto = "\n".join(p.text for p in doc.paragraphs)
    assert "[P1] «2. Plan de Mejora» fila" in texto  # acción sin evidencia nueva
    assert re.search(r"\[E\d\] https://ejemplo.invalid/drive/nuevo", texto)
    assert bor.SIN_EVIDENCIA_NUEVA in texto

    ws = load_workbook(tmp_path / "r.xlsx")["Revisión del corte"]
    columnas = [c.value for c in ws[1]]
    assert "Decisión (Aprobado/Editar/Descartar)" in columnas
    assert "Texto final" in columnas
    assert ws.max_row == 1 + len(b.acciones)
    assert (
        ws.data_validations.dataValidation[0].formula1 == '"Aprobado,Editar,Descartar"'
    )


# ---------------------------------------------------------------------------
# Revisión del PR: nombres en salidas y caché, texto del plan, hechos sin fuente
# ---------------------------------------------------------------------------


def todo_el_texto(carpeta: Path) -> str:
    """Todo lo que quedó en disco: docx, xlsx (XML interno) y caché."""
    import zipfile

    partes: list[str] = []
    for ruta in carpeta.rglob("*"):
        if not ruta.is_file():
            continue
        if ruta.suffix in (".docx", ".xlsx"):
            with zipfile.ZipFile(ruta) as z:
                partes += [z.read(n).decode("utf-8", "ignore") for n in z.namelist()]
        else:
            partes.append(ruta.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(partes)


async def test_el_nombre_no_aparece_en_ninguna_parte(tmp_path: Path) -> None:
    pg = guardado(PERSONA)
    a0 = pg.plan.acciones[0]
    a0.descripcion = f"Publicar piezas con {PERSONA}"
    a0.indicador = "Escribir a zoila@ejemplo.test o al 3105551234"
    pg.plan.objetivos[0].texto = "Objetivo a cargo de zoila ficticia pérez"
    a0.cortes[-1].descripcion = f"{PERSONA.upper()} hizo la jornada"
    con_enlace(pg, a0.codigo, "https://ejemplo.invalid/drive/nuevo", "2026-10-01T10:00")
    acciones = armar(pg)
    prompt = bor.texto_para_modelo(accion(acciones, a0.codigo))
    modelo = ModeloFalso(
        [
            {"texto": f"{PERSONA} publicó la pieza [P1].", "citas": ["P1"]},
            {"texto": "Hay un enlace nuevo [E3].", "citas": ["E3"]},
        ]
    )
    cache = Cache(tmp_path / "cache")
    b = await bor.generar(
        "Ejemplo",
        CORTE.isoformat(),
        acciones,
        nm.nombres_en_plan(pg),
        modelo,
        cache,
    )
    salidas.borrador_docx(tmp_path / "salida" / "b.docx", b)
    salidas.revision_xlsx(tmp_path / "salida" / "r.xlsx", b)
    texto = prompt + "\n".join(modelo.textos) + todo_el_texto(tmp_path)
    for secreto in (
        "Zoila",
        "ZOILA",
        "zoila",
        "Ficticia",
        "3105551234",
        "ejemplo.test",
    ):
        assert secreto not in texto, secreto
    a = next(x for x in b.acciones if x.base.accion.codigo == a0.codigo)
    assert a.rechazadas[0].texto == bor.OMITIDA
    assert a.rechazadas[0].motivo == bor.MOTIVO_NOMBRE


def test_ocultar_ignora_tildes_y_mayusculas_y_exige_palabra_completa() -> None:
    nombres = {"Zoila Ficticia Pérez"}
    assert nm.ocultar("ZOILA FICTICIA PEREZ firmó", nombres) == "[responsable] firmó"
    assert nm.ocultar("zoila ficticia pérez.", nombres) == "[responsable]."
    assert nm.ocultar("Ana Gómez", {"Ana Gómez"}) == "[responsable]"
    assert nm.ocultar("Mariana Gómez", {"Ana Gómez"}) == "Mariana Gómez"
    assert nm.ocultar("el profesor Juan Gómez", set()) == "el [persona]"
    assert nm.con_nombre_de_persona("ZOILA FICTICIA PEREZ", nombres)


def test_cargos_e_instituciones_no_son_nombres() -> None:
    pg = guardado()
    pg.plan.acciones[0].responsables = (
        "Facultad de Ciencias Exactas y Naturales, Dirección del programa, "
        "Oficina de Calidad; Comité Asesor"
    )
    assert nm.nombres_en_plan(pg) == set()
    texto = "La Facultad de Ciencias Exactas publicó la pieza"
    assert nm.ocultar(texto, nm.nombres_en_plan(pg)) == texto


def verificar(
    texto: str, citas: list[str], pg: PlanGuardado | None = None
) -> bor.FraseVerificada:
    pg = pg or guardado()
    con_enlace(pg, "1.1.1", "https://ejemplo.invalid/drive/nuevo", "2026-10-01T10:00")
    ac = accion(armar(pg), "1.1.1")
    return bor.verificar(ac, [bor.FraseAvance(texto=texto, citas=citas)], set())[0]


@pytest.mark.parametrize(
    ("texto", "citas", "motivo"),
    [
        ("40 asistentes el 12 de octubre [P1].", ["P1"], bor.MOTIVO_DATO_SIN_FUENTE),
        ("El avance es de 75 % [P1].", ["P1"], bor.MOTIVO_DATO_SIN_FUENTE),
        (
            "Hay un enlace https://otro.invalid/x [E3].",
            ["E3"],
            bor.MOTIVO_DATO_SIN_FUENTE,
        ),
        ("Se hizo la jornada [P1].", ["P1"], bor.MOTIVO_SOLO_CONTEXTO),
        ("Se hizo la jornada.", ["P1"], bor.MOTIVO_SIN_CITA),
        ("Se hizo la jornada [P1] [E3].", ["P1"], bor.MOTIVO_CITAS_NO_COINCIDEN),
        ("Se hizo la jornada [P1].", ["P1", "E3"], bor.MOTIVO_CITAS_NO_COINCIDEN),
        ("Se hizo la jornada [P99].", ["P99"], bor.MOTIVO_CITA_INVALIDA),
    ],
)
def test_verificador_no_acepta_hechos_sin_fuente(
    texto: str, citas: list[str], motivo: str
) -> None:
    f = verificar(texto, citas)
    assert not f.valida and f.motivo == motivo


def test_verificador_acepta_lo_que_esta_literal_en_las_fuentes() -> None:
    # El % declarado de la 1.1.1 es 60; el enlace está en [E3]; el código de la
    # acción y las fechas del corte también son legítimos.
    assert verificar("El plan declara 60 % de avance [P1].", ["P1"]).valida
    assert verificar(
        "Se registró https://ejemplo.invalid/drive/nuevo [E3].", ["E3"]
    ).valida
    assert verificar("Para la acción 1.1.1 hay un enlace nuevo [E3].", ["E3"]).valida


def test_novedad_solo_con_fecha_real_dentro_de_la_ventana() -> None:
    pg = guardado()
    # 1.1.2 no tiene cortes: ventana abierta por la izquierda, cerrada en el corte.
    con_enlace(pg, "1.1.2", "https://ejemplo.invalid/despues", "2026-12-15T10:00")
    con_enlace(pg, "1.2.1", "https://ejemplo.invalid/antes", "2026-05-21T10:00")
    acciones = armar(pg)
    assert not accion(acciones, "1.1.2").hay_evidencia_nueva  # después del corte
    assert not accion(acciones, "1.2.1").hay_evidencia_nueva  # ni > corte anterior
    # Las tareas cumplidas no cuentan: su fecha es la planeada, no la real.
    assert not accion(acciones, "1.1.1").hay_evidencia_nueva


@pytest.mark.parametrize(
    ("fecha", "nueva"),
    [
        ("2026-09-10", True),
        ("2026-09", True),
        ("2026-11", True),  # termina el 30 de noviembre = el corte
        ("2026-12", False),  # después del corte
        ("2026-05-21", False),  # el día del corte anterior no es nuevo
        ("2026-05", False),  # el mes cruza el corte anterior
        ("2025", False),
        ("2026", False),  # el año entero pasa del corte
        ("", False),
        ("hace poco", False),
    ],
)
def test_soporte_del_revisor_es_nuevo_segun_su_fecha(fecha: str, nueva: bool) -> None:
    desc = DescripcionArchivo(
        que_es="Acta ficticia",
        fecha_documento=fecha,
        que_prueba="Una jornada",
        ilegible_o_incompleto=False,
        observacion="",
    )
    a = accion(armar(guardado(), soportes={"1.2.1": [("S001", desc)]}), "1.2.1")
    assert next(f for f in a.fuentes if f.id == "S001").nueva is nueva


def test_soporte_del_revisor_pasa_por_el_filtro_de_nombres() -> None:
    desc = DescripcionArchivo(
        que_es="Acta firmada por la profesora Ana Gómez, ana@ejemplo.test",
        fecha_documento="2026-09",
        que_prueba="Llamar al 3105551234",
        ilegible_o_incompleto=False,
        observacion="",
    )
    a = accion(armar(guardado(), soportes={"1.2.1": [("S001", desc)]}), "1.2.1")
    texto = next(f for f in a.fuentes if f.id == "S001").texto
    for secreto in ("Ana", "ana@", "3105551234"):
        assert secreto not in texto


# ---------------------------------------------------------------------------
# Segunda revisión: citas en la caché, hechos por token, filtro de nombres
# ---------------------------------------------------------------------------


async def test_el_campo_citas_no_filtra_datos_a_la_cache(tmp_path: Path) -> None:
    pg = guardado(PERSONA)
    a0 = pg.plan.acciones[0]
    con_enlace(pg, a0.codigo, "https://ejemplo.invalid/drive/nuevo", "2026-10-01T10:00")
    modelo = ModeloFalso(
        [
            {
                "texto": "Hay un enlace nuevo [E3].",
                "citas": ["E3", "zoila@ejemplo.test"],
            },
            {"texto": "Otro enlace nuevo [E3].", "citas": ["E3", PERSONA]},
        ]
    )
    cache = Cache(tmp_path / "cache")
    b = await bor.generar(
        "Ejemplo", CORTE.isoformat(), armar(pg), nm.nombres_en_plan(pg), modelo, cache
    )
    salidas.borrador_docx(tmp_path / "salida" / "b.docx", b)
    texto = todo_el_texto(tmp_path)
    for secreto in ("Zoila", "zoila", "ejemplo.test"):
        assert secreto not in texto
    a = next(x for x in b.acciones if x.base.accion.codigo == a0.codigo)
    # Solo sobreviven los IDs válidos.
    assert all(f.citas == ["E3"] for f in a.frases if f.valida)


@pytest.mark.parametrize(
    ("texto", "citas", "motivo"),
    [
        # [P1] no respalda cifras ni fechas.
        ("Se avanzó hasta el 60 % en 2026 [P1].", ["P1"], bor.MOTIVO_DATO_SIN_FUENTE),
        # Una cifra suelta dentro de una fecha de la fuente no cuenta.
        ("Asistieron 10 personas [E3].", ["E3"], bor.MOTIVO_DATO_SIN_FUENTE),
        ("Asistieron 2026 personas [E3].", ["E3"], bor.MOTIVO_DATO_SIN_FUENTE),
        ("Fue el 12 de octubre [E3].", ["E3"], bor.MOTIVO_DATO_SIN_FUENTE),
        ("Fue el 2026-10-02 [E3].", ["E3"], bor.MOTIVO_DATO_SIN_FUENTE),
        # URL completa, con o sin esquema; ni prefijos ni otros sitios.
        (
            "Ver https://ejemplo.invalid/drive/nue [E3].",
            ["E3"],
            bor.MOTIVO_DATO_SIN_FUENTE,
        ),
        ("Ver ejemplo.invalid/otro [E3].", ["E3"], bor.MOTIVO_DATO_SIN_FUENTE),
        ("Ver www.otro.com/x [E3].", ["E3"], bor.MOTIVO_DATO_SIN_FUENTE),
        # En palabras: se marcan «revisar».
        ("Hubo cuarenta asistentes [E3].", ["E3"], bor.MOTIVO_REVISAR),
        ("Se hizo en septiembre [E3].", ["E3"], bor.MOTIVO_REVISAR),
        # El % declarado solo vale si la frase cita la acción en el plan.
        ("El avance llegó al 60 % [E3].", ["E3"], bor.MOTIVO_DATO_SIN_FUENTE),
    ],
)
def test_hechos_literales_por_token(texto: str, citas: list[str], motivo: str) -> None:
    f = verificar(texto, citas)
    assert not f.valida and f.motivo == motivo


@pytest.mark.parametrize(
    "texto",
    [
        "Se registró el 1 de octubre de 2026 un enlace [E3].",
        "El enlace se registró el 2026-10-01 [E3].",
        "Se registró en octubre https://ejemplo.invalid/drive/nuevo [E3].",
        "Se registró ejemplo.invalid/drive/nuevo [E3].",
        "El plan declara 60 % de avance [P1].",
        "Para la acción 1.1.1 hay un enlace nuevo [E3].",
    ],
)
def test_hechos_que_si_estan_en_la_fuente(texto: str) -> None:
    citas = list(dict.fromkeys(nm_citas(texto)))
    assert verificar(texto, citas).valida, texto


def nm_citas(texto: str) -> list[str]:
    return fuentes.citas_en_texto(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "Prof. Ana Gómez presentó la pieza",
        "La profesora ana gómez presentó la pieza",
        "La Sra. Pérez presentó la pieza",
        "la dra. gomez presentó la pieza",
        "El ing. Pérez presentó la pieza",
        "La lic. lópez presentó la pieza",
        "Se hizo con Juan Gómez",
        "Se hizo por Ana Pérez Ruiz",
        "Zoila​Ficticia Pérez presentó la pieza",
        "Zoila  Ficticia   Pérez presentó la pieza",
        "ZOILA PÉREZ presentó la pieza",
        "Escribir a ana@ejemplo.test",
    ],
)
def test_filtro_detecta_nombres_con_variantes(texto: str) -> None:
    assert nm.con_nombre_de_persona(texto, nm.nombres_en_plan(guardado(PERSONA)))


@pytest.mark.parametrize(
    "texto",
    [
        "La estudiante Ciencias Exactas participó",
        "La coordinadora Curricular Nacional revisó",
        "El estudiante de posgrado asistió",
        "Los profesores participaron en la jornada",
        "Se hizo con Dirección del Programa",
        "Se hizo por Ciencias Exactas",
        "El docente del programa presentó la pieza",
    ],
)
def test_filtro_no_marca_cargos_ni_dependencias(texto: str) -> None:
    assert not nm.con_nombre_de_persona(texto, set())
    assert nm.ocultar(texto, set()) == texto


def test_la_ref_de_la_fuente_tambien_se_oculta() -> None:
    pg = guardado()
    con_enlace(
        pg, "1.1.1", "https://ejemplo.invalid/ana@ejemplo.test/x", "2026-10-01T10:00"
    )
    a = accion(armar(pg), "1.1.1")
    assert all("ana@" not in f.ref for f in a.fuentes)


def test_el_docx_y_el_xlsx_llevan_el_aviso_del_filtro(tmp_path: Path) -> None:
    b = bor.Borrador("Ejemplo", CORTE.isoformat(), [])
    salidas.borrador_docx(tmp_path / "b.docx", b)
    salidas.revision_xlsx(tmp_path / "r.xlsx", b)
    assert "no una garantía" in "\n".join(
        p.text for p in Document(str(tmp_path / "b.docx")).paragraphs
    )
    assert "no una garantía" in todo_el_texto(tmp_path)
