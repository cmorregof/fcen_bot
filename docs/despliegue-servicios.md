# Despliegue multiservicio en Railway y configuración en BotFather

El proyecto **MemorIA** (`fcen_bot`) aloja tres agentes de Telegram que comparten el mismo núcleo de código pero operan de forma 100 % aislada:

1. **`actas`**: comités asesores de área curricular.
2. **`admision`**: documentación y requisitos de admitidos.
3. **`calidad`**: plan de mejoramiento, autoevaluación e indicadores.

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
| `ANTHROPIC_API_KEY` | Requerida | Opcional (fase esqueleto) | Opcional (fase esqueleto) | Acceso a Claude para lectura y redacción |
| `INVITE_CODE` | Código alfanumérico | No aplica por ahora | No aplica por ahora | Registro de administrativos autorizados |
| `INTERNAL_CRON_SECRET` | Secreto cron diario | No aplica | No aplica | Autenticación de `/internal/borrador-diario` |
| `PERIODO_ACTUAL` | `2026-2S` | `2026-2S` | `2026-2S` | Periodo académico en curso |
| `PERIODO_INICIO` | `AAAA-MM-DD` | No aplica | No aplica | Fecha de inicio de clases para cálculo de semanas |

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
