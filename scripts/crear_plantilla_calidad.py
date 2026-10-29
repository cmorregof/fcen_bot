"""Crea docs/calidad/plantilla_plan_mejoramiento.xlsx con 15 tareas FICTICIAS.

Dos programas inventados («Ejemplo Alfa» y «Ejemplo Beta»), sin datos reales.
Las fechas van repartidas entre 2026-08 y 2027-03 para que, a finales de octubre
de 2026, haya tareas vencidas, próximas y pendientes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

DESTINO = (
    Path(__file__).resolve().parents[1]
    / "docs/calidad/plantilla_plan_mejoramiento.xlsx"
)
COLUMNAS = [
    "programa", "código", "tarea", "responsable_cargo", "responsable_dependencia",
    "fecha_límite", "evidencia_esperada", "factor_cna", "eje_plan_accion",
]  # fmt: skip
ALFA = "Ejemplo Alfa (ficticio)"
BETA = "Ejemplo Beta (ficticio)"
DIR = "Dirección del programa (ejemplo)"
VICE = "Vicedecanatura Académica (ejemplo)"
CAL = "Oficina de Calidad (ejemplo)"
SEC = "Secretaría de Facultad (ejemplo)"

TAREAS = [
    (ALFA, "ALF-01", "Actualizar el documento de autoevaluación", "Coordinador(a) del programa", DIR, date(2026, 8, 31), "Documento de autoevaluación en PDF", "Factor 1", "Eje 1"),
    (ALFA, "ALF-02", "Publicar el perfil del egresado en la página del programa", "Profesional de comunicaciones", VICE, date(2026, 9, 15), "Enlace a la página publicada", "Factor 1", "Eje 1"),
    (ALFA, "ALF-03", "Aplicar la encuesta de satisfacción estudiantil", "Coordinador(a) del programa", DIR, date(2026, 10, 15), "Informe de resultados de la encuesta", "Factor 4", "Eje 2"),
    (ALFA, "ALF-04", "Revisar los contenidos de las asignaturas del núcleo", "Director(a) del área curricular", DIR, date(2026, 11, 10), "Acta de revisión del área", "Factor 3", "Eje 2"),
    (ALFA, "ALF-05", "Reportar los tiempos de respuesta a solicitudes", "Secretario(a) de Facultad", SEC, date(2026, 11, 20), "Tabla de tiempos del periodo", "Factor 4", "Eje 3"),
    (ALFA, "ALF-06", "Actualizar el registro de egresados", "Profesional de calidad", CAL, date(2026, 12, 5), "Base de egresados actualizada", "", "Eje 3"),
    (ALFA, "ALF-07", "Socializar el plan de mejoramiento con docentes", "Coordinador(a) del programa", DIR, date(2027, 1, 30), "Acta de la reunión de socialización", "Factor 2", "Eje 1"),
    (ALFA, "ALF-08", "Consolidar los indicadores de deserción", "Profesional de calidad", CAL, date(2027, 3, 15), "Informe de indicadores", "Factor 4", "Eje 3"),
    (BETA, "BET-01", "Revisar la pertinencia del plan de estudios", "Coordinador(a) del programa", DIR, date(2026, 9, 1), "Informe de pertinencia", "Factor 3", "Eje 1"),
    (BETA, "BET-02", "Documentar las prácticas de laboratorio", "Director(a) del área curricular", DIR, date(2026, 10, 1), "Guías de laboratorio actualizadas", "Factor 5", "Eje 2"),
    (BETA, "BET-03", "Inventariar los recursos bibliográficos", "Profesional de biblioteca", VICE, date(2026, 11, 5), "Inventario en Excel", "Factor 10", "Eje 2"),
    (BETA, "BET-04", "Actualizar la ficha de producción docente", "Coordinador(a) del programa", DIR, date(2026, 11, 25), "Ficha de producción actualizada", "Factor 2", "Eje 3"),
    (BETA, "BET-05", "Elaborar el informe semestral de seguimiento", "Vicedecano(a) Académico(a)", VICE, date(2026, 12, 18), "Informe semestral", "", "Eje 3"),
    (BETA, "BET-06", "Realizar el taller de capacitación sobre trámites", "Secretario(a) de Facultad", SEC, date(2027, 2, 12), "Lista de asistencia y presentación", "Factor 6", "Eje 1"),
    (BETA, "BET-07", "Cargar las evidencias del factor de internacionalización", "Profesional de calidad", CAL, date(2027, 3, 31), "Carpeta de evidencias con enlace", "Factor 9", "Eje 2"),
]  # fmt: skip


def main() -> None:
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "plan"
    hoja.append(COLUMNAS)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in TAREAS:
        hoja.append(list(fila))
    for col in hoja.columns:
        hoja.column_dimensions[col[0].column_letter].width = min(
            max(len(str(c.value or "")) for c in col) + 2, 60
        )
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    libro.save(DESTINO)
    print(f"{len(TAREAS)} tareas ficticias en {DESTINO}")


if __name__ == "__main__":
    main()
