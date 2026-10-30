# Indicadores del servicio de actas

El Consejo de Facultad pidió el 28-oct-2026:

- que las métricas oficiales salgan del acta del Consejo;
- un reporte mensual automático a los programas y a la Vicedecanatura;
- `/indicadores` para responder a Calidad de inmediato.

Este documento define cada indicador, dice de dónde sale y lista lo que falta de la plantilla oficial de Calidad.

Código: `app/services/indicadores.py` (cálculo, texto, Excel) y `app/services/reporte_mensual.py` (envío del día 1).

## Reglas

- **Solo cifras y solo lectura.** Ningún indicador lleva nombres, documentos ni textos de las solicitudes. De cada caso se leen solo el área, el programa, el trámite principal, la fecha de la solicitud, la recomendación y la decisión del Consejo.
- **Lo decidido sale del acta del Consejo confirmada.** Una decisión cuenta solo si consta en un acta del Consejo (de Facultad, de Sede o Superior) que se subió a MemorIA y que una persona confirmó caso por caso (`/acta_consejo` o la pantalla «Acta del Consejo»).
- **Sin acta, el caso es «pendiente de acta del Consejo».** Nunca se cuenta como aprobado. Un aplazamiento tampoco es una decisión: el caso sigue pendiente y se cuenta aparte.
- **El comité asesor solo recomienda.** «Recomendar aprobar» no es «aprobado».

## Qué casos entran

Un periodo incluye los casos **recibidos** en él: la fecha en que se registró el caso en MemorIA, en hora de Bogotá. Los casos descartados no entran.

Cada caso se cuenta con su estado **a la fecha de corte** (el día en que se pide el reporte). Por eso, un mismo mes puede mostrar más casos decididos si se consulta más tarde, porque mientras tanto llegó el acta.

El periodo se escribe así:

| Texto | Periodo |
|---|---|
| `2026-10` | Un mes calendario |
| `2026` | Un año calendario (de 2000 a 2100) |
| vacío, `actual` o el valor de `PERIODO_ACTUAL` (p. ej. `2026-2S`) | Desde `PERIODO_INICIO` (primer día de clases) hasta hoy |

Los periodos académicos anteriores no se pueden pedir por nombre, porque MemorIA solo conoce la fecha de inicio del periodo en curso. Para esos casos se piden los meses.

## Indicadores

| Clave | Indicador | Definición | Fuente |
|---|---|---|---|
| `recibidos` | Casos recibidos | Casos registrados en el periodo, sin descartados | Casos de MemorIA: fecha de registro |
| `recomendados` | Recomendados por el comité | Recomendar aprobar + recomendar no aprobar | Botón de la administrativa en MemorIA |
| `recomendar_aprobar` | Recomendar aprobar | — | Botón de la administrativa |
| `recomendar_no_aprobar` | Recomendar no aprobar | — | Botón de la administrativa |
| `decididos_consejo` | Decididos por el Consejo | Aprobó + no aprobó + otra decisión. **No** incluye aplazados | Acta del Consejo confirmada |
| `consejo_aprobo` | El Consejo aprobó | — | Acta del Consejo confirmada |
| `consejo_no_aprobo` | El Consejo no aprobó | — | Acta del Consejo confirmada |
| `consejo_aplazo` | El Consejo aplazó | Siguen pendientes de acta | Acta del Consejo confirmada |
| `consejo_otro` | Otra decisión del Consejo | Decisiones que no son aprobó, no aprobó ni aplazó | Acta del Consejo confirmada |
| `pendientes_acta` | Pendientes de acta del Consejo | Recomendados sin decisión confirmada desde el acta, más todos los aplazados (tengan o no recomendación registrada) | Botón + acta del Consejo |
| `dias_comite_mediana` | Días de la solicitud a la recomendación (mediana) | Días calendario entre la fecha de la solicitud y el registro de la recomendación | Ver «Fechas» |
| `dias_comite_p90` | Ídem, percentil 90 | Ver «Mediana y percentil 90» | Ver «Fechas» |
| `dias_comite_casos` | Casos que entran en ese cálculo | — | — |
| `dias_consejo_mediana` | Días de la recomendación a la decisión del Consejo (mediana) | Días calendario entre el registro de la recomendación y la fecha de la sesión que consta en el acta. Solo decididos, sin aplazados | Ver «Fechas» |
| `dias_consejo_p90` | Ídem, percentil 90 | — | Ver «Fechas» |
| `dias_consejo_casos` | Casos que entran en ese cálculo | — | — |
| `sin_fecha_recomendacion` | Recomendados sin fecha de recomendación | Recomendados antes de que MemorIA guardara la fecha. Cuentan como recomendados, pero no entran en los días ni en los plazos | Botón de la administrativa |
| `fechas_inconsistentes` | Decididos con fechas inconsistentes | Decididos cuya acta tiene fecha anterior al registro de la recomendación. No entran en los días de la recomendación a la decisión | Botón + acta del Consejo |
| `fuera_plazo_comite` | Fuera de plazo en el comité | Recomendados después del plazo, o sin recomendación y con el plazo ya vencido a la fecha de corte | `config/solicitudes.yaml`, `plazos.comite` |
| `fuera_plazo_consejo` | Fuera de plazo en el Consejo | Decididos después del plazo desde la recomendación, o pendientes de acta (incluidos los aplazados) con el plazo ya vencido | `config/solicitudes.yaml`, `plazos.consejo` |

Las mismas definiciones están en el código (`FUENTES`). Cada mensaje de Telegram las cita con números ([1] a [7]), la web las muestra bajo cada cifra y el Excel las trae en la pestaña «fuentes». Si `config/indicadores.yaml` tiene un error, Telegram envía las cifras y avisa que no pudo armar el Excel, y la web responde 503 en la descarga.

### Dimensiones

Cada indicador sale para el total y por grupo:

| Dimensión | Cómo se asigna | Fuente |
|---|---|---|
| Área curricular | Área de la administrativa que registró el caso (solo en el consolidado) | MemorIA |
| Programa | Programa reconocido en la ficha o asignado a mano; si no hay, «Sin programa asignado» | MemorIA |
| Tipo de solicitud | Trámite **principal** de la ficha (el primero). Cada caso cuenta una sola vez; un caso sin leer va a «Sin ficha» | Ficha del caso |
| Instancia | Si hay acta confirmada, el Consejo que la expidió. Si no, el que decide el trámite principal según `config/solicitudes.yaml` («Instancia por confirmar» si la ruta no está confirmada) | Acta; si no hay, la ruta configurada |
| Mes | Mes de registro (solo si el periodo abarca más de un mes) | MemorIA |

### Fechas

- **Fecha de la solicitud.** Es la fecha del correo o del formato que se leyó en la ficha. Si no se leyó, o si es posterior al registro del caso (mala lectura), se usa la fecha de registro.
- **Fecha de la recomendación.** Es el momento en que la administrativa registró la recomendación con el botón, en Telegram o en la web. Se guarda en `casos.recomendado`, una columna nueva, en UTC; los indicadores la convierten a la fecha de Bogotá. Solo un cambio real de sentido la mueve:
  - volver a marcar el mismo sentido no la cambia;
  - cambiar el sentido la actualiza;
  - volver a «Pendiente» la borra;
  - si el caso ya tiene una decisión del Consejo registrada (incluido un aplazamiento), no se mueve, para que los días hasta el acta se midan con la fecha original.
  - Los casos recomendados antes de esta versión no tienen esa fecha, y no se les inventa una, ni siquiera si se vuelve a pulsar el mismo botón. Cuentan como recomendados, pero no entran en los días ni en el plazo del comité: salen en `sin_fecha_recomendacion`.
- **Fecha de la decisión.** Es la fecha de la sesión que consta en el acta del Consejo confirmada (`decisiones_consejo.acta_fecha`). Sin fecha en el acta, el caso no entra en los días. Tampoco entra si la fecha del acta es anterior al registro de la recomendación: ese caso se cuenta en `fechas_inconsistentes`.

### Mediana y percentil 90

- **Mediana:** la de Python (`statistics.median`). Con un número par de casos, es el promedio de los dos centrales.
- **Percentil 90:** por rango más cercano. Es el valor en la posición ⌈0,9·n⌉ de los días ordenados. Con 10 casos es el noveno; con 1 caso, ese mismo.
- Sin casos con ambas fechas, la cifra sale «—» (vacía en el Excel).

## Dónde se ven

| Canal | Quién | Alcance |
|---|---|---|
| `/indicadores [periodo]` en Telegram | `DECANATURA_TELEGRAM_IDS` y `ADMIN_TELEGRAM_IDS` | Toda la Facultad, con el Excel adjunto |
| Web, pantalla «Indicadores» | Decanatura y admin | Toda la Facultad |
| Web, pantalla «Indicadores» | Administrativa | Solo su área curricular |
| Reporte mensual (día 1, 7:30 a. m. de Bogotá) | Administrativas registradas en el bot | Su área, mes anterior + acumulado del periodo |
| Reporte mensual | `VICEDECANATURA_TELEGRAM_IDS` | Consolidado de la Facultad |

El comité no tiene esta pantalla. En Telegram, las administrativas tampoco tienen `/indicadores`: reciben el reporte mensual de su área.

El reporte mensual lo dispara `.github/workflows/reporte-mensual.yml` con `POST /internal/reporte-mensual`, igual que el resumen semanal. Está **apagado por defecto**: se enciende con `REPORTE_MENSUAL_ACTIVO=true`. El envío es el de `resumen.enviar_a`: si falla uno, sigue con los demás.

El envío es idempotente:
- la tabla `reportes_mensuales` guarda cada mes ya enviado, y una nueva corrida del workflow para ese mes responde `ya_enviado: true` sin reenviar;
- si nadie recibió el reporte (no hay destinatarios o Telegram está caído), el mes no queda registrado y se puede volver a intentar;
- el workflow corre sin permisos sobre el repositorio (`permissions: {}`) y con `concurrency`, para que dos corridas no se pisen.

El resumen semanal de la decanatura muestra, además, las actas del Consejo confirmadas en la semana, con instancia, número, fecha y conteo por sentido.

## Plazos

Los plazos del indicador «fuera de plazo» están en `config/solicitudes.yaml`, sección `plazos` (ver `docs/solicitudes.md`). Son días calendario y cada uno necesita su `fuente`.

**Hoy están vacíos.** Ninguna norma transcrita en `app/normativa/base.py` fija un plazo para que el comité recomiende ni para que el Consejo decida, y no se inventan. Mientras sigan vacíos, el indicador dice «sin plazo configurado» y no cuenta casos.

## Excel y plantilla oficial de Calidad

El Excel tiene dos pestañas:

- **indicadores:** una fila por grupo (Total, áreas, programas, tipos, instancias, meses) y una columna por indicador;
- **fuentes:** el periodo, el alcance, el corte, los plazos, la definición y la fuente de cada columna, y la nota sobre el acta del Consejo.

**La plantilla oficial de indicadores de Calidad todavía no llega.** Por eso las columnas son provisionales y se configuran en `config/indicadores.yaml` (clave del indicador y encabezado), sin tocar el código. Una clave desconocida es un error.

Falta que Calidad defina:

1. **Nombres y orden de las columnas** de su plantilla, y si quiere los conteos, los días o ambos.
2. **Unidad de análisis:** casos recibidos en el periodo (lo actual) o decisiones del Consejo expedidas en el periodo (por fecha del acta).
3. **Periodos:** si reporta por mes calendario, por periodo académico o por corte. Si es por periodo académico, faltan las fechas de inicio y fin de cada periodo anterior.
4. **Días hábiles o calendario.** Hoy son calendario. Para hábiles se necesita el calendario de festivos y de receso de la Universidad.
5. **Fecha de inicio del trámite:** fecha del correo del estudiante (lo actual), fecha de radicación o fecha de registro.
6. **Fecha de la recomendación:** registro en MemorIA (lo actual) o fecha de la sesión del comité, que MemorIA todavía no captura (fase 3 del README).
7. **Plazos oficiales** por tramo y, si aplica, por tipo de solicitud, con la norma que los fija.
8. **Desagregación:** por programa (lo actual), por nivel (pregrado/posgrado) o por sede, y si los trámites con varios tipos se cuentan una vez por tipo.
9. **Indicadores adicionales,** por ejemplo el porcentaje de recomendaciones acogidas por el Consejo o los casos devueltos.

Cuando llegue la plantilla, los puntos 1 y 7 se resuelven editando `config/indicadores.yaml` y `config/solicitudes.yaml`. Los demás piden un cambio en `app/services/indicadores.py` y en este documento.
