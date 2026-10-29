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

Todo el texto del listado y la guía va en el system prompt con prompt caching (sin RAG). Si un PDF es escaneado, se le hace OCR una sola vez (`ocrmypdf` con `tesseract-ocr-spa`) y el texto queda en `<nombre>.ocr.txt` junto al PDF, en la carpeta de insumos. En Railway hay que instalar `ocrmypdf` y `tesseract-ocr-spa` en la imagen, o subir ese `.ocr.txt` al volumen con el PDF.

## Qué se edita sin tocar código

- `docs/admision/aviso_datos.md`: aviso de tratamiento de datos (**PENDIENTE DE AVAL DE LA FACULTAD**).
- `config/admision/chequeo.yaml`: documentos, sección del listado y puntos de la lista de chequeo.

## Datos

- Los documentos se procesan en memoria y se descartan. No se usa `MEDIA_DIR`.
- La base (`<DATA_DIR>/admision/fcen.db`) solo guarda el consentimiento por chat y contadores por día (preguntas, documentos revisados, tipos de error). Ningún texto ni archivo.
- El bot filtra correos y contraseñas antes de llamar al modelo, no los guarda y avisa al estudiante.

## Simulación

```bash
uv run python scripts/simular_admision.py --estimar   # costo, sin llamar a la API
uv run python scripts/simular_admision.py             # 10 conversaciones ficticias
```
