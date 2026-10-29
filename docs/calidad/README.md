# Servicio de calidad (plan de mejoramiento y acreditación)

Todo entra por Excel mientras no haya acceso al Drive de la DAMA. Datos de la plantilla, el directorio y la simulación: **ficticios**.

## Comandos
`/start <código>` · `/importar_plan` · `/plan <programa>` · `/evidencia <código> [enlace]` · `/alerta_vista_previa` · `/reporte <programa>` · `/a_quien <tema>`

## Variables de entorno
| Variable | Uso |
|---|---|
| `BOT_SERVICIO=calidad` | Selecciona este servicio |
| `CALIDAD_INVITE_CODE` | Código de invitación para `/start` |
| `CALIDAD_MAX_USERS` | Máximo de personas registradas (10) |
| `CALIDAD_DIAS_PROXIMA` | Días para «próxima a vencer» (28 = 4 semanas) |
| `ALERTAS_ACTIVAS` | `false` por defecto: el cron no envía nada hasta ponerla en `true` |

## Alerta quincenal
`POST /internal/alerta-quincenal` (cabecera `X-Cron-Secret`), programada los días 1 y 15 en `.github/workflows/alerta-quincenal.yml` con el secreto `CALIDAD_APP_URL`. Con `ALERTAS_ACTIVAS=false` responde `activas: false` y no envía. Las alertas van a las personas registradas; separar destinatarios por programa queda pendiente.

## Archivos
- `plantilla_plan_mejoramiento.xlsx`: 15 tareas ficticias de dos programas (`scripts/crear_plantilla_calidad.py`).
- `config/calidad/directorio.yaml`: directorio de ejemplo, todo PARA COMPLETAR.
- `simulacion-AAAA-MM-DD.md`: salida de `scripts/simular_calidad.py`.

Pendiente: proponer `factor_cna` con el modelo (una persona lo confirma).
