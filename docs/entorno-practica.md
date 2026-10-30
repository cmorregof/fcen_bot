# Entorno de práctica de MemorIA

Para las capacitaciones, el personal practica en una copia de MemorIA con datos
ficticios. Lo que crean allí **no** entra a los borradores de oficio reales.

El entorno es el mismo código que producción, con la variable
`MEMORIA_PRACTICA=true`. Con ella:

- La web muestra el banner **«ENTORNO DE PRÁCTICA · datos ficticios»** en todas las pantallas.
- **No se envía nada a Telegram.** El cliente descarta los envíos aunque el servicio tenga token, y el token y el secreto del webhook se ignoran.
- La base va en su propia carpeta del volumen: `/data/practica/<servicio>/` (`fcen.db`, `media`, `out`). Si `DB_PATH`, `MEDIA_DIR` u `OUTPUT_DIR` (ya resueltas) no están dentro de `<DATA_DIR>/practica`, el servicio se niega a arrancar.
- El arranque carga (si la siembra anterior no terminó) los datos ficticios. Después, el administrador usa el botón **Reiniciar práctica**.

Los datos: ocho casos de actas (todos «Ficticio/a», documentos 1000000xxx, con la
extracción ya hecha: no gastan API), el plan «Ejemplo Beta» de calidad y las
métricas de admisión. La lista de chequeo de admisión sale de
`config/admision/chequeo.yaml`, igual que en producción.

## Por qué un despliegue aparte (y no un interruptor en la web de producción)

- **Seguro por construcción.** La web de práctica es *otro proyecto de Vercel* con sus propias variables, que apuntan solo a los servicios de práctica. No hay un modo que alguien pueda activar por error en la web real.
- **No cambia producción.** Con `NEXT_PUBLIC_PRACTICA` sin definir, la web usa las variables `NEXT_PUBLIC_API_*` de siempre.
- **Falla cerrado.** Con `NEXT_PUBLIC_PRACTICA=true` la web usa *únicamente* `NEXT_PUBLIC_API_*_PRACTICA`; si falta una, ese servicio queda sin configurar. Nunca vuelve a la URL de producción.
- Aunque alguien apunte la web de producción a un backend de práctica, el banner sale igual: lo pide al backend (`GET /api/web/entorno`).

## Pasos para Carlos

### 1. Railway: tres servicios de práctica

Dentro del proyecto de Railway (o en uno nuevo, `memoria-practica`, para separar la factura), crea tres servicios desde el mismo repositorio y la misma rama:
`fcen-practica-actas`, `fcen-practica-calidad`, `fcen-practica-admision`.
Para cada uno:

1. **Volumen propio** (Volumes → Add Volume) montado en `/data`. No reutilices el volumen de producción.
2. **Dominio público** (Networking → Generate Domain).
3. **Variables:**

| Variable | Valor |
|---|---|
| `MEMORIA_PRACTICA` | `true` |
| `BOT_SERVICIO` | `actas`, `calidad` o `admision` según el servicio |
| `WEB_GOOGLE_CLIENT_ID` | El mismo Client ID de producción |
| `WEB_SESSION_SECRET` | Secreto nuevo (`python3 -c "import secrets; print(secrets.token_hex(32))"`), distinto en cada servicio y distinto al de producción |
| `WEB_ORIGINS` | El dominio de la web de práctica en Vercel (paso 2) |
| `WEB_ADMINS` | Tu correo @unal.edu.co y el de quien más administre la práctica |
| `ANTHROPIC_API_KEY` | **Opcional.** Sin ella todo funciona con los casos sembrados; solo fallan «procesar», correcciones y revisión de documentos nuevos. Si la pones, gasta API |
| `ADMISION_INSUMOS_DIR` | Solo en admisión; puede quedar vacío para la práctica |

   **No definas** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `INTERNAL_CRON_SECRET`, `RESUMEN_SECRET`, `RESUMEN_CALIDAD_URL`, `RESUMEN_ADMISION_URL` (en práctica se ignoran, para no mostrar cifras reales), `DB_PATH`, `MEDIA_DIR`, `OUTPUT_DIR` ni `WEB_AUTH_DEV`, y **no registres ningún webhook**.
4. Despliega y comprueba `https://<servicio-practica>/api/web/entorno`: debe responder `"practica": true`. El primer arranque crea `/data/practica/<servicio>/` con los datos ficticios.

### 2. Vercel: proyecto aparte

1. New Project → importa el mismo repositorio. Raíz: `web/`. Nómbralo `memoria-fcen-practica`.
2. Variables (ninguna es secreta):

| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_PRACTICA` | `true` |
| `NEXT_PUBLIC_API_ACTAS_PRACTICA` | URL del servicio `fcen-practica-actas` |
| `NEXT_PUBLIC_API_CALIDAD_PRACTICA` | URL de `fcen-practica-calidad` |
| `NEXT_PUBLIC_API_ADMISION_PRACTICA` | URL de `fcen-practica-admision` |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | El mismo Client ID |

   No definas `NEXT_PUBLIC_API_ACTAS`, `_CALIDAD`, `_ADMISION` ni `NEXT_PUBLIC_INGRESO_DEV` en este proyecto.
3. Copia el dominio resultante en `WEB_ORIGINS` de los tres servicios de Railway y redespliega.
4. En Google Cloud Console, agrega ese dominio a los «orígenes de JavaScript autorizados» del **mismo** cliente OAuth. Si prefieres un dominio estable, asigna uno propio al proyecto (por ejemplo `practica.<tu dominio>`).

## Autorizar a los asistentes de una capacitación

El ingreso es el mismo (Google @unal.edu.co) y los roles son los mismos, pero en una base separada: **estar autorizado en producción no autoriza en práctica**, ni al revés.

1. Entra a la web de práctica con un correo de `WEB_ADMINS` → **Usuarios**.
2. En cada servicio que vayan a usar, «Autorizar un correo»: correo, rol (la administrativa de área, el comité, etc.) y el área curricular. Quien practique la sesión de actas necesita el rol `administrativa` y un área; quien practique calidad, `calidad`; admisión, `admision`.
3. Al terminar la capacitación, «Retirar acceso» a cada correo (o déjalos para la siguiente).

Los correos autorizados **se conservan** al reiniciar la práctica. Para una lista larga hay un CSV (`correo,nombre,rol,direccion`; el área es `ciencias_naturales` o `matematicas` para administrativa y comité). Guárdalo fuera del repositorio: son personas reales.

```bash
MEMORIA_PRACTICA=true BOT_SERVICIO=actas DATA_DIR=data/ensayo \
  uv run python scripts/sembrar_practica.py --asistentes ../asistentes.csv
```

Eso funciona en local. En Railway, el script está en la imagen (`railway ssh` al servicio y el mismo comando, con `DATA_DIR=/data` que ya viene definido); si `railway ssh` no te resulta, usa la pantalla Usuarios.

## Reiniciar los datos antes de cada capacitación

Con una sesión de administrador, en la web de práctica: **Usuarios → Reiniciar práctica** (aparece bajo el título de cada servicio; son tres botones, uno por servicio). Pide confirmación, borra lo creado (casos, planes, archivos y borradores) y vuelve a cargar los datos ficticios. Conserva los correos autorizados.

Equivale a `POST /api/web/practica/reiniciar` con sesión de admin; responde 404 si el servicio no es de práctica y 403 si el rol no es `admin`. También se puede correr `scripts/sembrar_practica.py` (idempotente: dos corridas dejan lo mismo).

Recomendación: reinicia el día anterior y otra vez justo antes de empezar.

## Costo estimado

Son cifras aproximadas; confirma las tarifas vigentes en railway.com/pricing y vercel.com/pricing.

- **Railway:** cobra por uso (CPU, memoria, volumen). Tres servicios pequeños encendidos todo el mes: del orden de **USD 5–15**. Si los apagas (elimina el despliegue activo) entre capacitaciones y solo pagas el volumen (unos USD 0,15 por GB-mes, 1 GB basta), baja a **menos de USD 2** más los días encendidos.
- **Vercel:** un segundo proyecto de la misma cuenta, estático, sin costo adicional apreciable.
- **API de Anthropic:** USD 0 si no pones `ANTHROPIC_API_KEY` en práctica. Con ella, lo de cada caso nuevo que procesen (centavos de dólar por caso).

## Qué no hace

- No es una copia de producción: nunca se importan datos reales. Pide a los asistentes que **no** peguen correos ni pantallazos de estudiantes reales en la práctica.
- No prueba Telegram: los bots no participan.
