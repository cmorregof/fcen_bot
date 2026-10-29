# Despliegue del servicio de admisión en Railway

Se crea igual que `fcen-calidad`: mismo repositorio, misma rama, mismo `Dockerfile`
y `railway.toml`, con su propio volumen, su propio bot de Telegram y su propia base.
La guía general (BotFather, secretos de webhook, `set_webhook.py`) está en
[`docs/despliegue-servicios.md`](../despliegue-servicios.md).

## 1. Crear el servicio

1. En el proyecto de Railway: **+ New** → **GitHub Repo** → `cmorregof/fcen_bot`, rama `main`.
2. **Settings**:
   - Nombre: `fcen-admision`.
   - Build: `Dockerfile` de la raíz (lo fija `railway.toml`).
   - Healthcheck: `/health` (lo fija `railway.toml`, con 300 s de espera).
   - **Networking** → **Generate Domain** (por ejemplo `fcen-admision.up.railway.app`).
3. **Volumes** → **Add Volume** montado en `/data`. Es solo de este servicio: allí
   quedan la base (`/data/admision/fcen.db`, solo consentimientos y contadores) y
   los insumos (`/data/admision/insumos`).

## 2. Variables

Sin valores aquí: los secretos solo van en Railway.

| Variable | Valor | Notas |
|---|---|---|
| `BOT_SERVICIO` | `admision` | Obligatoria |
| `ADMISION_INSUMOS_DIR` | `/data/admision/insumos` | Carpeta de los PDF oficiales, en el volumen |
| `INSTALAR_OCR` | `1` | Instala `ocrmypdf` y `tesseract-ocr-spa` en la imagen (ver §4). Solo en este servicio |
| `ANTHROPIC_API_KEY` | *secreto* | Obligatoria |
| `ANTHROPIC_WORKSPACE_ID` | | Solo si la key no se creó dentro de un workspace |
| `TELEGRAM_BOT_TOKEN` | *secreto* | Token del bot de admisión (BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | *secreto* | Distinto del de los otros servicios |
| `WEB_SESSION_SECRET` | *secreto* | Largo y aleatorio, **distinto** del de actas y calidad. Sin él, la web de admitidos responde 503 |
| `WEB_GOOGLE_CLIENT_ID` | | El mismo Client ID de Google de los otros servicios |
| `WEB_ORIGINS` | `https://memoria-fcen.vercel.app` | CORS: sin esto el navegador no puede llamar a la API |
| `WEB_ADMINS` | | Correos @unal.edu.co que administran usuarios de este servicio |
| `ADMISION_CONTACTO` | | Contacto de la responsable del proceso (lo ven los admitidos) |
| `ADMISION_ADMIN_IDS` | | IDs de Telegram para `/metricas`, separados por comas |
| `ADMISION_MODELO` | | Opcional; por defecto `claude-sonnet-5-5` |
| `ADMISION_LIMITE_PREGUNTAR_HORA` | | Opcional; por defecto 20 por IP y hora |
| `ADMISION_LIMITE_REVISAR_HORA` | | Opcional; por defecto 10 por IP y hora |
| `ADMISION_LIMITE_CONSENTIMIENTO_HORA` | | Opcional; por defecto 30 por IP y hora |
| `ADMISION_PROXIES_CONFIABLES` | | Opcional; por defecto 1 (el proxy de Railway) |

No definir `DB_PATH`, `MEDIA_DIR`, `OUTPUT_DIR` (salen de `DATA_DIR=/data`, que fija
el Dockerfile), `INVITE_CODE`, `INTERNAL_CRON_SECRET`, `PERIODO_INICIO` ni
`WEB_AUTH_DEV`.

## 3. Vercel

La web (`web/`, en `https://memoria-fcen.vercel.app`) encuentra la API con:

| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_API_ADMISION` | `https://fcen-admision.up.railway.app` (el dominio del paso 1, sin `/` final) |

Es pública (va en el JavaScript), no secreta. Después de crearla hay que
**volver a desplegar** la web: Next.js la incrusta en el build.

## 4. Insumos (fuentes del asistente)

El servicio carga **todos** los `.pdf`, `.txt` y `.md` de `ADMISION_INSUMOS_DIR` (ignora
las cachés `.ocr.txt`, que solo usa para el PDF del mismo nombre). Hay que poner
exactamente estos cuatro, con estos nombres:

- `LISTADO_DE_DOCUMENTOS_ADMITIDOS_PREGRADO_2027_1S.pdf`
- `2.Lista-de-Chequeo-y-Verificacion-de-Documentos.pdf`
- `Formato-de-matricula-2027-1S-2.pdf`
- `Manual_Usuario_FORE_Admitidos_2027_1S.pdf`

Nunca van al repositorio.

**Cómo subirlos al volumen.** Railway no permite copiar archivos al volumen desde el
panel. Por eso la web tiene una sección «Fuentes del asistente» en
*Admisión: cifras y lista de chequeo* (`/admision`), solo para los roles `admision` y
`admin`:

1. Entrar a la web con una cuenta que tenga rol `admin` o `admision` en este servicio.
2. En «Fuentes del asistente», subir cada PDF (si ya existe, se reemplaza).
3. La tabla muestra cada archivo con sus páginas y su estado, y la lista de los que faltan.

El servidor guarda el archivo en `ADMISION_INSUMOS_DIR` (crea la carpeta si no existe)
y vuelve a leer las fuentes en la siguiente pregunta. Solo acepta nombres
`[A-Za-z0-9._-]` terminados en `.pdf`, `.txt` o `.md`, hasta 40 MB
(`ADMISION_MAX_BYTES_INSUMO`). Son documentos públicos de la Universidad, nunca de
un admitido.

**PDF escaneados (OCR).** Si un PDF casi no tiene capa de texto, el servicio le hace
OCR una vez con `ocrmypdf` y guarda `<nombre>.ocr.txt` junto al PDF. La imagen base
no trae `ocrmypdf`; hay dos caminos:

- **Recomendado:** `INSTALAR_OCR=1` en este servicio. Railway pasa la variable como
  argumento de build y la imagen instala `ocrmypdf` y `tesseract-ocr-spa` (actas y
  calidad no la definen y no cargan con el peso). Al arrancar, el servicio lee las
  fuentes en segundo plano y hace el OCR que falte; el `.ocr.txt` queda en el volumen
  y no se repite.
- **Sin OCR en la imagen:** generar el `.ocr.txt` en un equipo con `ocrmypdf` (arrancar
  el servicio una vez con `ADMISION_INSUMOS_DIR` apuntando a la carpeta local) y subirlo
  desde la misma sección de la web junto al PDF. Con el `.ocr.txt` presente no se
  llama a OCR, aunque el PDF sea más reciente.

Si un PDF escaneado no tiene `.ocr.txt` y no hay `ocrmypdf`, la tabla lo marca
«Escaneado y sin .ocr.txt» y el bot responde que no puede consultar el listado.

## 5. Webhook de Telegram

```bash
TELEGRAM_BOT_TOKEN="<token>" TELEGRAM_WEBHOOK_SECRET="<secreto>" \
uv run python scripts/set_webhook.py https://fcen-admision.up.railway.app
```

## 6. Verificación

1. `curl https://fcen-admision.up.railway.app/health` → `"ok": true, "servicio": "admision"`,
   `"modelo_configurado": true`, `"telegram_configurado": true`.
2. En los logs del despliegue: `Insumos de admisión listos: …`. Si dice
   `Insumos de admisión no disponibles` o `Faltan insumos de admisión`, revisar §4.
3. En la web, «Revisar mis documentos» (`/admitidos`): aceptar el aviso, hacer una
   pregunta del listado y revisar un documento **ficticio**.
4. En Telegram: `/start` muestra el aviso de datos (con la marca PENDIENTE DE AVAL).

## Límite de uso

Cada pregunta o revisión llama al modelo, así que la parte pública tiene un límite
por IP y por hora (20 preguntas, 10 revisiones, 30 consentimientos; se cambian con
las variables `ADMISION_LIMITE_*_HORA`). Tener en cuenta:

- Se cuenta por IP. Admitidos que comparten red (un colegio, el wifi de la sede)
  comparten el cupo; si la oficina hace una jornada presencial, conviene subir los
  límites ese día.
- La IP se toma de la entrada de `X-Forwarded-For` que pone el proxy de Railway (la
  última), no de la primera, que el cliente puede inventar.
- Los contadores viven en memoria: se reinician con cada despliegue y suponen una
  sola réplica. Con varias réplicas el límite efectivo se multiplica.
