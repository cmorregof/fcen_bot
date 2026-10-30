# Despliegue multiservicio en Railway y configuración en BotFather

El proyecto **MemorIA** (`fcen_bot`) aloja tres agentes de Telegram que comparten el mismo núcleo de código pero operan de forma 100 % aislada:

1. **`actas`**: comités asesores de área curricular.
2. **`admision`**: documentación y requisitos de admitidos.
3. **`calidad`**: plan de mejoramiento, autoevaluación e indicadores.

> Para capacitaciones hay un entorno aparte con datos ficticios: [`docs/entorno-practica.md`](entorno-practica.md).

> Admisión tiene su guía propia, con insumos, OCR y web: [`docs/admision/despliegue.md`](admision/despliegue.md).

Cada servicio se despliega de manera independiente en Railway a partir del mismo repositorio y rama, con sus propias variables de entorno, su propio bot en Telegram y su propia base de datos SQLite. **Un servicio nunca lee ni escribe en la base de datos de otro.**

---

## 1. Creación de los bots en BotFather

Para cada uno de los servicios nuevos (`admision` y `calidad`), así como para `actas` si se monta un ambiente nuevo:

1. Abre Telegram y busca a [@BotFather](https://t.me/BotFather).
2. Envía el comando `/newbot`.
3. Asigna un nombre para mostrar (visible para las personas usuarias):
   - Actas: `FCEN Actas — MemorIA`
   - Admisión: `FCEN Admisión — MemorIA`
   - Calidad: `FCEN Calidad — MemorIA`
4. Asigna un nombre de usuario único (`username`) que termine en `bot`:
   - Por ejemplo: `fcenadmision_bot`, `fcencalidad_bot`.
5. BotFather entregará un mensaje con el token de acceso a la API HTTP:
   ```text
   Use this token to access the HTTP API:
   1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
   > [!IMPORTANT]
   > Guarda este token de forma segura. **Nunca** lo subas al repositorio ni lo incluyas en commits. Se configurará en Railway en la variable `TELEGRAM_BOT_TOKEN`.

6. (Opcional recomendado) Configura comandos y descripción en BotFather:
   - `/setdescription`: define qué hace el bot antes de iniciarlo.
   - `/setcommands`: registra los comandos sugeridos en la barra de chat:
     - Para `admision`:
       ```text
       start - Iniciar validación de admisión
       ```
     - Para `calidad`:
       ```text
       start - Iniciar seguimiento de calidad
       ```
     - Para `actas`:
       ```text
       nuevo - Empieza otro caso
       listo - Procesa el caso abierto
       cancelar - Descarta el caso abierto
       casos - Lista de últimos casos
       caso - Muestra la ficha del caso N
       acta - Genera oficio y acta ahora
       cerrar_acta - Cierra casos tratados por el comité
       costo - Consumo del modelo este mes
       ayuda - Instrucciones de uso
       ```

---

## 2. Generación de secretos de webhook

Cada bot debe tener su propio secreto aleatorio de 32 bytes en hexadecimal para proteger el endpoint `/webhook` mediante la cabecera `X-Telegram-Bot-Api-Secret-Token`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Genera un secreto distinto para cada servicio.

---

## 3. Creación de servicios en Railway

En un proyecto de Railway (pueden convivir dentro del mismo proyecto para compartir métricas y facturación, o en proyectos separados):

1. Pulsa **+ New** → **GitHub Repo** y selecciona `fcen_bot_repo`.
2. En la configuración del servicio ("Settings"):
   - Cambia el nombre del servicio para identificarlo claramente: `fcen-actas`, `fcen-admision` o `fcen-calidad`.
   - Verifica que el despliegue use el `Dockerfile` de la raíz del repo.
   - En **Networking** → **Public Networking**, genera un dominio público (por ejemplo `fcen-admision.up.railway.app`).
3. Agrega un volumen persistente:
   - Ve a **Volumes** → **Add Volume**.
   - Monta el volumen en `/data`.
   - Cada servicio usará su propia subcarpeta aislada dentro de `/data/` (ver variables abajo).

---

## 4. Variables de entorno por servicio en Railway

Configura las variables en la pestaña **Variables** de cada servicio en Railway:

| Variable | Servicio `actas` | Servicio `admision` | Servicio `calidad` | Propósito |
|---|---|---|---|---|
| `BOT_SERVICIO` | `actas` | `admision` | `calidad` | Define el servicio activo y el enrutador de updates |
| `TELEGRAM_BOT_TOKEN` | Token BotFather Actas | Token BotFather Admisión | Token BotFather Calidad | Acceso a la Bot API de Telegram |
| `TELEGRAM_WEBHOOK_SECRET` | Secreto hex Actas | Secreto hex Admisión | Secreto hex Calidad | Validación del header `X-Telegram-Bot-Api-Secret-Token` |
| `DB_PATH`, `MEDIA_DIR`, `OUTPUT_DIR` | No definir | No definir | No definir | Se derivan de `DATA_DIR=/data` (lo fija el Dockerfile): `/data/<servicio>/fcen.db`, `media` y `out` |
| `ANTHROPIC_API_KEY` | Requerida | Requerida | Opcional (fase esqueleto) | Acceso a Claude para lectura y redacción |
| `INVITE_CODE` | Código alfanumérico | No aplica por ahora | No aplica por ahora | Registro de administrativos autorizados |
| `INTERNAL_CRON_SECRET` | Secreto cron diario | No aplica | No aplica | Autenticación de `/internal/borrador-diario` |
| `PERIODO_ACTUAL` | `2026-2S` | `2026-2S` | `2026-2S` | Periodo académico en curso |
| `PERIODO_INICIO` | `AAAA-MM-DD` | No aplica | No aplica | Fecha de inicio de clases para cálculo de semanas |
| `DECANATURA_TELEGRAM_IDS` | Ids de Telegram de la Decana y los vicedecanos, separados por comas | No aplica | No aplica | Únicas personas que pueden usar `/resumen` y que reciben el resumen semanal |
| `RESUMEN_SEMANAL_ACTIVO` | `true` (por defecto) o `false` | No aplica | No aplica | `false` apaga el envío del lunes; `/resumen` sigue disponible |
| `RESUMEN_DIAS_SIN_MOVIMIENTO` | `7` (por defecto) | No aplica | No aplica | Días sin movimiento a partir de los cuales un caso sale como alerta |
| `RESUMEN_SECRET` | Secreto hex compartido | El mismo valor | El mismo valor | Protege `GET /internal/cifras`; sin él, la ruta responde 403 y el resumen no trae calidad ni admisión |
| `RESUMEN_CALIDAD_URL`, `RESUMEN_ADMISION_URL` | URL pública de cada servicio | No aplica | No aplica | Actas pide ahí los conteos agregados de calidad y admisión (nunca lee su base) |
| `ADMIN_TELEGRAM_IDS` | Ids de Telegram de los administradores, separados por comas | No aplica | No aplica | Pueden usar `/indicadores`, igual que la decanatura |
| `VICEDECANATURA_TELEGRAM_IDS` | Ids de Telegram de la Vicedecanatura Académica | No aplica | No aplica | Reciben el consolidado del reporte mensual de indicadores |
| `REPORTE_MENSUAL_ACTIVO` | `true` (por defecto) o `false` | No aplica | No aplica | `false` apaga el reporte mensual del día 1; `/indicadores` y la web siguen disponibles |
| `INDICADORES_PATH` | No definir | No aplica | No aplica | Otro archivo de columnas del Excel de indicadores (por defecto `config/indicadores.yaml`) |

> [!CAUTION]
> Cada servicio de Railway tiene su propio volumen en `/data`. Si se define `DB_PATH` a mano, debe ser exclusiva del servicio: `admision` y `calidad` se niegan a arrancar si apuntan a la base de actas.

> [!IMPORTANT]
> **Servicio `actas` ya desplegado.** Antes de esta versión la base vivía en `/data/fcen.db` (con `/data/media` y `/data/out`). Si esa base existe y `/data/actas/fcen.db` no, el servicio la sigue usando sin cambios. No definas `DB_PATH=/data/actas/fcen.db` en ese servicio: arrancaría con una base vacía y los casos y usuarios registrados quedarían huérfanos.

---

## 5. Registro del Webhook en Telegram

Una vez que el servicio esté desplegado en Railway y responda en su dominio público:

### Opción A: Con el script del repositorio (`scripts/set_webhook.py`)

Ejecuta el script pasando las variables del bot correspondiente:

```bash
TELEGRAM_BOT_TOKEN="<TOKEN_DEL_BOT>" \
TELEGRAM_WEBHOOK_SECRET="<SECRET_DEL_BOT>" \
uv run python scripts/set_webhook.py https://<app-name>.up.railway.app
```

Ejemplo para admisión:
```bash
TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ" \
TELEGRAM_WEBHOOK_SECRET="a1b2c3d4..." \
uv run python scripts/set_webhook.py https://fcen-admision.up.railway.app
```

### Opción B: Con `curl` directo a la API de Telegram

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN_DEL_BOT>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<app-name>.up.railway.app/webhook",
    "secret_token": "<SECRET_DEL_BOT>",
    "allowed_updates": ["message", "callback_query"],
    "drop_pending_updates": false
  }'
```

Telegram responderá:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

### Comprobar el estado del webhook

Para validar que Telegram registró la URL y no tiene errores de entrega:
```bash
curl "https://api.telegram.org/bot<TOKEN_DEL_BOT>/getWebhookInfo"
```

Debe mostrar `url` apuntando a `https://<app-name>.up.railway.app/webhook`, `has_custom_certificate: false` y `pending_update_count: 0`.

---

## 6. Verificación en producción

1. **Healthcheck HTTP:**
   Consulta en el navegador o con `curl`:
   ```bash
   curl https://<app-name>.up.railway.app/health
   ```
   Respuesta esperada:
   ```json
   {
     "ok": true,
     "servicio": "admision",
     "commit": "...",
     "modelo": "claude-sonnet-5-5",
     "modelo_configurado": false,
     "telegram_configurado": true,
     "periodo": "2026-2S",
     "periodo_inicio": null
   }
   ```

2. **Prueba funcional en Telegram:**
   - Abre el bot en Telegram (`@fcenadmision_bot` o `@fcencalidad_bot`).
   - Envía `/start`.
   - El bot debe responder inmediatamente:
     ```text
     Servicio en construcción
     ```
   - Para el bot de actas (`@fcenpregrado_bot`), `/start <INVITE_CODE>` iniciará el registro administrativo usual.

---

## 7. Resumen para la decanatura

El servicio de actas responde `/resumen` solo a los ids de `DECANATURA_TELEGRAM_IDS` y, cada lunes a las 7:30 a. m. (hora de Bogotá), el workflow `resumen-semanal.yml` llama a `POST /internal/resumen-semanal` con `INTERNAL_CRON_SECRET` para enviárselo. Usa los mismos secrets de GitHub Actions que el borrador diario (`APP_URL`, `INTERNAL_CRON_SECRET`).

- Cada persona de la decanatura debe abrir el bot y enviar `/start` una vez: Telegram no deja que un bot le escriba primero a alguien. Su id numérico se puede consultar con [@userinfobot](https://t.me/userinfobot).
- El mensaje trae solo cifras por programa y por estado, sin nombres ni documentos.
- Ningún caso se cuenta como aprobado por el comité: lo que decide el Consejo sale de su acta, confirmada caso por caso en MemorIA (`/acta_consejo` o la pantalla «Acta del Consejo»). Sin esa confirmación, el caso recomendado figura como «pendiente de acta del Consejo». El resumen trae además las actas del Consejo registradas en la semana (instancia, número y fecha), con sus conteos.
- Para incluir calidad y admisión, define el mismo `RESUMEN_SECRET` en los tres servicios y, en actas, `RESUMEN_CALIDAD_URL` y `RESUMEN_ADMISION_URL`. Actas pide `GET /internal/cifras` (los mismos conteos del tablero web, sin nombres); si un servicio no responde, el resumen lo dice y sigue.

---

## 8. Indicadores y reporte mensual

Definiciones y lo que falta de la plantilla de Calidad: `docs/indicadores.md`.

- `/indicadores [periodo]` en Telegram responde solo a `DECANATURA_TELEGRAM_IDS` y `ADMIN_TELEGRAM_IDS`, con las cifras de toda la Facultad y el Excel.
- En la web, la pantalla «Indicadores» (`/indicadores`) es para decanatura y admin (toda la Facultad) y para cada administrativa (solo su área).
- El día 1 de cada mes a las 7:30 a. m. (hora de Bogotá), el workflow `reporte-mensual.yml` llama a `POST /internal/reporte-mensual` con `INTERNAL_CRON_SECRET`. Cada administrativa registrada en el bot recibe las cifras de su área del mes anterior; los ids de `VICEDECANATURA_TELEGRAM_IDS` reciben el consolidado. Usa los mismos secrets de GitHub Actions que el resumen semanal.
- `REPORTE_MENSUAL_ACTIVO=false` lo apaga: la ruta responde `activo: false` y no envía nada.
- Como con la decanatura, cada persona de la Vicedecanatura debe abrir el bot y enviar `/start` una vez.
