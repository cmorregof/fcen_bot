# Web de MemorIA

Frontend en Next.js (TypeScript) para el personal de la FCEN y para los admitidos.
El diseño está en [`docs/web/diseno.md`](../docs/web/diseno.md).

La web solo sirve páginas estáticas. El navegador llama directo al backend de cada
servicio en Railway, así que los datos de estudiantes nunca pasan por Vercel.

## Correrlo en local

Requisitos: `uv` y Node 20 o superior. No hace falta instalar nada global.

1. Backends (actas en :8001, calidad en :8002, admisión en :8003), con datos ficticios
   y la entrada de prueba sin Google:

   ```bash
   make web-local
   ```

   Los datos quedan en `data/web-local/` (ignorado por git). Sin `ANTHROPIC_API_KEY`
   todo funciona menos leer casos, responder preguntas y revisar documentos.

2. Frontend, en otra terminal:

   ```bash
   cd web && cp .env.example .env.local && npm install && npm run dev
   ```

3. Abra http://localhost:3000 y entre con un correo ficticio:

   | Correo | Ve |
   |---|---|
   | `administrativa@unal.edu.co` | Casos del comité, ficha, recomendación, oficio y acta |
   | `comite@unal.edu.co` | Consulta de casos y conceptos |
   | `calidad@unal.edu.co` | Plan de mejoramiento, alertas, reporte, «¿A quién acudo?» |
   | `admision@unal.edu.co` | Métricas y lista de chequeo de admisión |
   | `decana@unal.edu.co` | Tablero de la Facultad (solo lectura) |
   | `admin@unal.edu.co` | Usuarios de los tres servicios |

   Los admitidos entran por «Revisar mis documentos», sin cuenta.

Verificación: `npm run lint`, `npm run typecheck` y `npm run build`.

## Variables en Vercel

| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_API_ACTAS` | URL pública del backend de actas en Railway |
| `NEXT_PUBLIC_API_CALIDAD` | URL pública del backend de calidad |
| `NEXT_PUBLIC_API_ADMISION` | URL pública del backend de admisión |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Client ID del cliente OAuth de Google (tipo «aplicación web») |
| `NEXT_PUBLIC_INGRESO_DEV` | No definir (o `false`) en Vercel |

Raíz del proyecto en Vercel: `web/`. Ninguna de estas variables es secreta.

## Variables en Railway (cada servicio)

Además de las que ya usa cada servicio (`BOT_SERVICIO`, `TELEGRAM_*`, `ANTHROPIC_API_KEY`…):

| Variable | Valor |
|---|---|
| `WEB_GOOGLE_CLIENT_ID` | El mismo Client ID de Google |
| `WEB_SESSION_SECRET` | Secreto largo y aleatorio, **distinto en cada servicio** |
| `WEB_ORIGINS` | Dominio de Vercel, por ejemplo `https://memoria-fcen.vercel.app` |
| `WEB_ADMINS` | Correos @unal.edu.co que administran usuarios en ese servicio |
| `WEB_DOMINIO` | `unal.edu.co` (valor por defecto) |
| `WEB_AUTH_DEV` | No definir. Aunque se defina, se ignora en Railway |

En Google Cloud Console, el cliente OAuth necesita como «orígenes de JavaScript
autorizados» el dominio de Vercel (y `http://localhost:3000` para pruebas).
