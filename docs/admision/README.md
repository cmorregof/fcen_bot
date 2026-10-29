# Servicio de admisión

Asistente de Telegram que ayuda a los admitidos a la FCEN a revisar su documentación antes de subirla. No reemplaza la revisión oficial ni sube nada por el estudiante.

## Variables de entorno

| Variable | Para qué |
|---|---|
| `BOT_SERVICIO=admision` | Elige este servicio |
| `ADMISION_INSUMOS_DIR` | Carpeta (fuera del repo) con el listado y la guía en PDF, TXT o MD |
| `ADMISION_CONTACTO` | Contacto de la responsable, para lo que no está en las fuentes |
| `ADMISION_ADMIN_IDS` | IDs de Telegram autorizados para `/metricas`, separados por comas |
| `ADMISION_MODELO` | Por defecto `claude-sonnet-5-5` |
| `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Secretos del servicio, solo en variables de entorno |

## Fuentes

Todo el texto del listado y la guía va en el system prompt con prompt caching (sin RAG). Si un PDF es escaneado, se le hace OCR una sola vez (`ocrmypdf` con `tesseract-ocr-spa`) y el texto queda en `<nombre>.ocr.txt` junto al PDF.

### Despliegue en Railway

En Railway no existe `~/fcen_insumos/admision` y la imagen no trae `ocrmypdf`. Hay que:

1. Generar el `.ocr.txt` en una máquina con OCR: basta con arrancar el servicio una vez con `ADMISION_INSUMOS_DIR` apuntando a la carpeta local (queda junto al PDF).
2. Subir al volumen el PDF **y** su `.ocr.txt` (por ejemplo a `/data/admision/insumos`).
3. Definir `ADMISION_INSUMOS_DIR=/data/admision/insumos`.

Con el `.ocr.txt` presente no se llama a OCR, aunque el PDF tenga una fecha más reciente (subir ambos al volumen cambia las fechas). Si falta el `.ocr.txt` y no hay `ocrmypdf`, el bot responde que no puede consultar el listado. Los archivos de insumos nunca van al repositorio.

## Qué se edita sin tocar código

- `docs/admision/aviso_datos.md`: aviso de tratamiento de datos (**PENDIENTE DE AVAL DE LA FACULTAD**).
- `config/admision/chequeo.yaml`: documentos, sección del listado y puntos de la lista de chequeo.

## Datos

- Los documentos se procesan en memoria y se descartan. No se usa `MEDIA_DIR`.
- La base (`<DATA_DIR>/admision/fcen.db`) solo guarda el consentimiento por chat y contadores por día (preguntas, documentos revisados, tipos de error). Ningún texto ni archivo.
- El bot filtra antes de llamar al modelo: los correos, y todo lo que siga a «contraseña», «clave», «usuario» o similares hasta el fin de la línea (o hasta un nuevo «¿»). Ante la duda, bloquea. No guarda nada de eso y avisa al estudiante.

## Simulación

```bash
uv run python scripts/simular_admision.py --estimar   # costo, sin llamar a la API
uv run python scripts/simular_admision.py             # 10 conversaciones ficticias
```
