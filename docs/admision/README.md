# Servicio de admisión

Asistente de Telegram que ayuda a los admitidos a la FCEN a revisar su documentación antes de subirla. No reemplaza la revisión oficial ni sube nada por el estudiante.

## Variables de entorno

| Variable | Para qué |
|---|---|
| `BOT_SERVICIO=admision` | Elige este servicio |
| `ADMISION_INSUMOS_DIR` | Carpeta (fuera del repo) con los insumos oficiales; en Railway, `/data/admision/insumos` |
| `ADMISION_CONTACTO` | Contacto de la responsable, para lo que no está en las fuentes |
| `ADMISION_ADMIN_IDS` | IDs de Telegram autorizados para `/metricas`, separados por comas |
| `ADMISION_MODELO` | Por defecto `claude-sonnet-5-5` |
| `ADMISION_LIMITE_PREGUNTAR_HORA`, `ADMISION_LIMITE_REVISAR_HORA`, `ADMISION_LIMITE_CONSENTIMIENTO_HORA` | Límite por IP y hora de la web pública (20, 10 y 30) |
| `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Secretos del servicio, solo en variables de entorno |

## Fuentes

El servicio carga **todos** los `.pdf`, `.txt` y `.md` de `ADMISION_INSUMOS_DIR`. Para
admitidos de pregrado 2027-1S van exactamente estos cuatro archivos, con estos nombres:

| Archivo | Qué es |
|---|---|
| `LISTADO_DE_DOCUMENTOS_ADMITIDOS_PREGRADO_2027_1S.pdf` | Listado de documentos de admitidos |
| `2.Lista-de-Chequeo-y-Verificacion-de-Documentos.pdf` | Lista de chequeo y verificación (la que sigue `config/admision/chequeo.yaml`) |
| `Formato-de-matricula-2027-1S-2.pdf` | Formato de matrícula |
| `Manual_Usuario_FORE_Admitidos_2027_1S.pdf` | Manual de la plataforma FORE para admitidos |

Nunca van al repositorio. Si falta alguno, el servicio lo dice en los logs al arrancar
y en la web («Fuentes del asistente», solo responsables).

Todo el texto va en el system prompt con prompt caching (sin RAG). Si un PDF es escaneado, se le hace OCR una sola vez (`ocrmypdf` con `tesseract-ocr-spa`) y el texto queda en `<nombre>.ocr.txt` junto al PDF. Con el `.ocr.txt` presente no se llama a OCR, aunque el PDF tenga una fecha más reciente.

El despliegue en Railway (volumen, cómo subir los insumos, OCR, variables de la web) está en [`despliegue.md`](despliegue.md).

## Qué se edita sin tocar código

- `docs/admision/aviso_datos.md`: aviso de tratamiento de datos (**PENDIENTE DE AVAL DE LA FACULTAD**).
- `config/admision/chequeo.yaml`: documentos de la lista oficial, con su sección literal, si son obligatorios, condicionales (`condicion`: a quién aplican) u opcionales, y los puntos de chequeo. El ítem de descuento de Medellín (Universidad de Antioquia) queda fuera porque no aplica a la Sede Manizales.

## Datos

- Los documentos se procesan en memoria y se descartan. No se usa `MEDIA_DIR`.
- Los insumos subidos desde la web son documentos públicos de la Universidad; nunca se suben documentos de admitidos.
- La base (`<DATA_DIR>/admision/fcen.db`) solo guarda el consentimiento por chat y contadores por día (preguntas, documentos revisados, tipos de error). Ningún texto ni archivo.
- El bot filtra antes de llamar al modelo: los correos, y todo lo que siga a «contraseña», «clave», «usuario» o similares hasta el fin de la línea (o hasta un nuevo «¿»). Ante la duda, bloquea. No guarda nada de eso y avisa al estudiante.

## Simulación

```bash
uv run python scripts/simular_admision.py --estimar   # costo, sin llamar a la API
uv run python scripts/simular_admision.py             # 10 conversaciones ficticias
```
