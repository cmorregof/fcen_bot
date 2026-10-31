# Tiempos de respuesta de las notificaciones (Secretaría de Facultad)

Cada semestre, la oficina de Calidad pide a la Secretaría de Facultad los tiempos de respuesta de las notificaciones oficiales. Es el indicador de divulgación de la información oficial. Se calcula con tres fechas por caso:

1. **Ingreso:** cuando el caso llega a la Secretaría de Facultad.
2. **Expedición:** cuando se expide el oficio o el acto administrativo de respuesta.
3. **Notificación:** cuando se notifica ese acto.

Antes se llevaban a mano en un Excel. Ahora se registran en MemorIA.

## Cómo funciona

1. La pantalla **Notificaciones** (rol `secretaria`, servicio actas) lista los casos que el Consejo de Facultad decidió en el semestre. Toma solo las actas del Consejo confirmadas en MemorIA y deja fuera los aplazados.
2. Para cada caso, la Secretaría registra el acto (oficio o resolución), su número y las tres fechas. Como sugerencia para el ingreso aparece la fecha de la recomendación del comité asesor; solo cuenta lo que se guarda.
3. MemorIA valida las fechas: no puede haber fechas futuras y el orden debe ser ingreso ≤ expedición ≤ notificación.
4. Con **Descargar Excel de tiempos** sale el archivo, que tienen también decanatura y admin:
   - una hoja de resumen, con la mediana y el percentil 90 de cada tramo;
   - una fila por caso, sin nombres ni documentos;
   - las fechas que faltan, en amarillo.

El **semestre** es calendario y se toma por la fecha de la sesión del Consejo:

- 2026-1S va de enero a junio.
- 2026-2S va de julio a diciembre.

Código:

- `app/services/notificaciones.py`
- `app/api/web/secretaria.py`
- `web/src/app/secretaria/page.tsx`

## Estadísticas del Consejo para Calidad

La Secretaría entrega a Calidad un consolidado de las solicitudes estudiantiles que decide el Consejo de Facultad. El botón **Estadísticas para Calidad (Excel)** está en Notificaciones y en Indicadores (decanatura y admin). Sale de `GET /api/web/actas/secretaria/estadisticas/xlsx?semestre=`, que pueden pedir secretaria, decanatura y admin. Acepta un semestre (`2026-1S`, `2026-2S`) o un año completo (`2026`); vacío es el semestre actual.

- **Qué cuenta:** las solicitudes con decisión del Consejo de Facultad (aprobó, no aprobó u otra) tomada de un acta confirmada en MemorIA. El mes y el semestre son los de la sesión. Un caso con varios trámites cuenta una vez en cada trámite; el total de casos distintos va aparte.
- **Qué no cuenta:** aplazamientos, casos descartados, decisiones del Consejo de Sede o del Superior, casos sin acta confirmada y lo que no pasó por MemorIA.
- **Hojas:** «Resumen» (trámite × sentido), «Por programa» (programa × trámite, con subtotales de pregrado y posgrado), «Por mes», «Movilidades» y «Léeme». Solo cifras.
- **Movilidades:** salen del trámite `movilidad`. MemorIA no sabe si una homologación o equivalencia viene de una movilidad, así que esas quedan en su propio trámite. Las movilidades que no pasan por los comités en MemorIA no aparecen y hay que tomarlas de su fuente.

Código: `app/services/estadisticas_consejo.py`.

## Pendiente de revisar con la Secretaría

- Si el semestre se cuenta por la fecha de la sesión, como ahora, o por la de notificación.
- Si la fecha de ingreso que sugiere MemorIA (la de la recomendación del comité) les sirve como punto de partida.
- El formato del Excel que usan hoy, para igualar las columnas.
- Para las estadísticas: si Calidad agrupa los trámites como MemorIA o con otras categorías, y si quiere las homologaciones dentro de movilidades.
