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

## Pendiente de revisar con la Secretaría

- Si el semestre se cuenta por la fecha de la sesión, como ahora, o por la de notificación.
- Si la fecha de ingreso que sugiere MemorIA (la de la recomendación del comité) les sirve como punto de partida.
- El formato del Excel que usan hoy, para igualar las columnas.
