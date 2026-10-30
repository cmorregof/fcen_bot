# Servicio de calidad (plan de mejoramiento y acreditación)

El bot lee los planes de mejoramiento con la **plantilla institucional** de la oficina de calidad, un .xlsx por programa. Todo entra por Excel mientras no haya acceso al Drive de la DAMA. Los planes, el directorio y la simulación de esta carpeta son **ficticios**.

## La plantilla
| Hoja | Qué se lee |
|---|---|
| «1. Formulación» | Oportunidad de mejora, línea base, factor y característica CNA, relación con el plan de acción de la Facultad |
| «2. Plan de Mejora» (o «2. Plan de Mejoramiento 2025») | Objetivo, meta, acciones numeradas (1.1, 1.2.1…), indicador, responsables, recursos, inicio y fin, % de avance, evidencias y una descripción del avance por cada corte (columnas con fecha) |
| «3. Cronograma 20XX», una por año | Tareas específicas de cada acción: soporte, responsable, enlace al Drive, % de avance, OK, estados escritos a mano y Gantt semanal |
| «4. Evaluación» | Fecha de evaluación, % de avance declarado y real, descripción |
| «Presupuesto» | No se lee |

Modelo: programa → objetivo → acción → tareas del cronograma (`app/servicios/calidad/plantilla.py`).

El lector es determinista, sin modelo de lenguaje, y ubica hojas y columnas por palabras clave, no por posición:
- Encabezados en cualquier fila (3, 5, 6 o 7 en los planes reales) y nombres de hoja con espacios o sin numeración («Cronograma 2026»).
- Celdas combinadas: el objetivo combinado sobre varias acciones, la acción sobre varias tareas, los meses del Gantt.
- Fechas como datetime o como texto: «1 de enero de 2023», «30 de agosto 2028», «03-12-2025», «01/02/2025».
- Dos fechas en la celda de fin («01/02/2025 … 30/07/2025»): la última es la vigente y la anterior cuenta como reprogramación.
- % de avance: con formato de porcentaje la celda guarda 0–1; sin formato, 0–100; también el texto «100 %».
- Estados escritos a mano: «NO FUNCIONÓ» antes del código de la acción, «Tercera reprogramación» en la columna del Drive, notas como «Fechas pospuestas» dentro del Gantt.
- Si el cronograma no trae fechas por tarea, las toma de las semanas marcadas en el Gantt.
- Filas de instrucciones, promedios al pie y leyendas de colores no se leen como acciones.

Lo que no se puede leer queda como **alerta de lectura** en el resumen de importación. Las alertas citan hoja y celda, nunca su contenido.

## Estados de una acción (regla fija)
1. **NO FUNCIONÓ**: marcada así en el plan o en el cronograma.
2. **Cumplida**: % de avance de 100.
3. **Vencida**: la fecha de fin ya pasó y el avance es menor a 100 %.
4. **Por iniciar**: la fecha de inicio aún no llega.
5. **En curso**: lo demás.

Además, una acción está **reprogramada** si tiene fechas de fin anteriores, una marca de reprogramación o tareas reprogramadas en el cronograma. El **próximo corte** es la siguiente fecha de corte del plan; si todas pasaron, el último corte más seis meses, marcado como estimado.

## Comandos
- `/start <código>`: registrarse con el código de invitación.
- `/importar_plan`: muestra un resumen (programa, acciones, tareas, % de avance, cambios y alertas de lectura) y solo guarda si alguien toca **Guardar**. Reimportar actualiza por programa y código de acción, no duplica, conserva los cortes anteriores y deja en `cal_cambios` qué cambió. Las acciones que dejan de venir se conservan marcadas.
- `/plan <programa>`: tablero con cada acción y su % de avance, vencidas, reprogramadas, «NO FUNCIONÓ», en curso, por iniciar, cumplidas, responsables y próximo corte.
- `/evidencia <programa> <código> [enlace]`: registra un soporte (archivo o enlace). Queda por revisar y no cambia el % de avance, que solo viene del plan.
- `/alerta_vista_previa`: la alerta quincenal de cada programa (vencidas, las que vencen en 4 semanas, reprogramadas sin cumplir, «NO FUNCIONÓ» y próximo corte).
- `/reporte <programa>`: Excel con las pestañas estado, acciones, tareas, cortes y fuentes. En «fuentes», cada cifra tiene una fila por acción, con su registro, la importación, el archivo y la hoja y fila de origen en el plan.
- `/a_quien <tema>`: dependencia y cargo a quien acudir.

El formato plano anterior (una fila por tarea) se retiró: ningún plan real lo usa. Sus tablas (`cal_tareas`, `cal_historial`, `cal_evidencias`) ya no se crean; en una base vieja quedan sin uso y no se borran.

## Variables de entorno
| Variable | Uso |
|---|---|
| `BOT_SERVICIO=calidad` | Selecciona este servicio |
| `CALIDAD_INVITE_CODE` | Código de invitación para `/start` |
| `CALIDAD_MAX_USERS` | Máximo de personas registradas (10) |
| `CALIDAD_DIAS_PROXIMA` | Días para «vence pronto» (28 = 4 semanas) |
| `ALERTAS_ACTIVAS` | `false` por defecto: el cron no envía nada hasta ponerla en `true` |
| `CALIDAD_REVISOR_ACTIVO` y demás `CALIDAD_REVISOR_*` | Revisión de soportes desde la web; apagada por defecto. Ver [cierre.md](cierre.md#desde-la-web) |

## Alerta quincenal
`POST /internal/alerta-quincenal` (cabecera `X-Cron-Secret`), programada los días 1 y 15 en `.github/workflows/alerta-quincenal.yml` con el secreto `CALIDAD_APP_URL`. Con `ALERTAS_ACTIVAS=false` responde `activas: false` y no envía. Las alertas van a las personas registradas; separar destinatarios por programa queda pendiente.

## Archivos
- `plantilla_plan_mejoramiento.xlsx` y `plantilla_plan_mejoramiento_beta.xlsx`: dos programas inventados con la misma estructura de cinco hojas y las variaciones de formato de los planes reales (`scripts/crear_plantilla_calidad.py` describe cuál trae cada una). Las pruebas y la simulación usan solo estos archivos.
- `simulacion-AAAA-MM-DD.md`: salida de `scripts/simular_calidad.py`.
- `siguientes-pasos.md`: revisión asistida de soportes, borrador de la descripción por corte y cierre del plan (sin implementar).
- `cierre.md`: revisor de soportes para el cierre de un plan (script `scripts/cierre_plan.py`, aún sin exponer en la web ni en Telegram): cómo correrlo y cuánto cuesta.
- `config/calidad/directorio.yaml`: directorio de ejemplo, todo PARA COMPLETAR.

## Planes reales
Viven fuera del repositorio, en `~/fcen_insumos/calidad/planes_reales/`, y nunca entran a él: ni copias, ni fragmentos, ni fixtures derivados. Para comprobar el lector contra ellos:

```bash
uv run python scripts/validar_planes_reales.py
```

El script imprime solo conteos y estados por archivo, y las alertas de lectura con su hoja y celda.
