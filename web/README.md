# Web de MemorIA

Frontend en Next.js (TypeScript) para el personal de la FCEN y para los admitidos.
El diseño está en [`docs/web/diseno.md`](../docs/web/diseno.md).

La web solo sirve páginas estáticas. El navegador llama a `/srv/<servicio>/...` en el
mismo dominio de la web y Vercel reenvía la petición al backend de Railway (ver
«Proxy de Vercel», abajo). Los datos pasan por Vercel, pero Vercel no los guarda.

## Correrlo en local

Requisitos: `uv` y Node 20 o superior. No hace falta instalar nada global.

1. Backends (actas en :8001, calidad en :8002, admisión en :8003, oportunidades en
   :8004), con datos ficticios
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
   | `secretaria@unal.edu.co` | Notificaciones: fechas, Excel de tiempos y borrador del oficio del Consejo |
   | `calidad@unal.edu.co` | Plan de mejoramiento, alertas, reporte, «¿A quién acudo?» |
   | `admision@unal.edu.co` | Métricas y lista de chequeo de admisión |
   | `decana@unal.edu.co` | Tablero de la Facultad (solo lectura) |
   | `oportunidades@unal.edu.co` | Cola de revisión, ofertas, empresas y boletín |
   | `admin@unal.edu.co` | Usuarios de los cuatro servicios |

   Los admitidos entran por «Revisar mis documentos», sin cuenta.

Verificación: `npm run lint`, `npm run typecheck` y `npm run build`.

Para probar el proxy como en Vercel: ponga las `NEXT_PUBLIC_API_*` en `.env.local`
(o `.env.production.local`), `npx next build` y `npx next start -p 3100`. Como
`:3100` no está en `WEB_ORIGINS`, cualquier llamada que no pase por el proxy falla
por CORS y se nota en la consola.

## Proxy de Vercel

Desde noviembre de 2026 algunas redes bloquean las IP de Railway (incidente
«External network blocks affecting access to Railway» en status.railway.com) y la web
mostraba «No hay conexión con el servicio». Por eso el navegador ya no habla con
Railway: llama a rutas del dominio de la web y Vercel las reenvía.

- **Rutas.** `web/next.config.ts` define un *rewrite* externo por servicio:
  `/srv/<servicio>/api/web/:ruta*` → `<NEXT_PUBLIC_API_SERVICIO>/api/web/:ruta*`
  (o las `*_PRACTICA` con `NEXT_PUBLIC_PRACTICA=true`). Solo se reenvía `/api/web`;
  el resto del backend (por ejemplo el webhook de Telegram) no se expone por aquí.
  Los destinos se leen al construir: si cambia una URL, hay que volver a desplegar.
- **Datos.** Las peticiones y respuestas atraviesan Vercel, pero no se guardan allí:
  no hay funciones de servidor ni base de datos en la web, y la caché está apagada
  dos veces (`x-vercel-enable-rewrite-caching: 0` en estas rutas y
  `Cache-Control: no-store` en toda respuesta de `/api/web` del backend).
- **Límites de Vercel.** El backend debe responder en **120 s** o Vercel devuelve
  error (la web muestra «El servicio tardó demasiado…»). Los Word, PDF y Excel tardan
  segundos y la revisión de soportes corre en segundo plano (la web consulta cada
  3 s), así que caben. Vercel no documenta un tope para el cuerpo de un *rewrite*
  externo; el de sus funciones es 4,5 MB.
- **Archivos grandes, directo a Railway.** Por eso, todo envío de más de **4 MB**
  (en la práctica, el zip de soportes de calidad, que puede pesar cientos de MB) va
  directo al backend como antes, con CORS (`WEB_ORIGINS`). Si la red bloquea Railway,
  la persona ve: «No se pudo enviar el archivo… Intente desde otra red (por ejemplo,
  los datos del celular) o con un archivo de menos de 4 MB». Lo demás, incluidas las
  descargas, va por el proxy. El tope está en `MAXIMO_PROXY_BYTES`
  (`web/src/lib/api.ts`).
- **CORS** se mantiene en los backends: lo usan las subidas grandes y la vuelta
  atrás.
- **Volver atrás sin tocar código.** `NEXT_PUBLIC_PROXY=false` en Vercel y un nuevo
  despliegue: la web vuelve a llamar directo a Railway.
- **Admisión (cuando se despliegue).** Detrás del proxy, la IP que ve Railway es la
  de Vercel. Para que el límite por IP de los admitidos siga siendo por persona,
  `ADMISION_PROXIES_CONFIABLES=2` (Vercel + Railway); ver
  [`docs/admision/despliegue.md`](../docs/admision/despliegue.md).

## Variables en Vercel

| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_API_ACTAS` | URL pública del backend de actas en Railway |
| `NEXT_PUBLIC_API_CALIDAD` | URL pública del backend de calidad |
| `NEXT_PUBLIC_API_ADMISION` | URL pública del backend de admisión |
| `NEXT_PUBLIC_API_OPORTUNIDADES` | URL pública del backend de oportunidades |
| `NEXT_PUBLIC_PROXY` | No definir. `false` vuelve a la llamada directa a Railway |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Client ID del cliente OAuth de Google (tipo «aplicación web») |
| `NEXT_PUBLIC_INGRESO_DEV` | No definir (o `false`) en Vercel |

Raíz del proyecto en Vercel: `web/`. Ninguna de estas variables es secreta. Las
`NEXT_PUBLIC_API_*` sirven a la vez de destino del proxy y de ruta directa para los
archivos grandes.

## Variables en Railway (cada servicio)

Además de las que ya usa cada servicio (`BOT_SERVICIO`, `TELEGRAM_*`, `ANTHROPIC_API_KEY`…):

| Variable | Valor |
|---|---|
| `WEB_GOOGLE_CLIENT_ID` | El mismo Client ID de Google |
| `WEB_SESSION_SECRET` | Secreto largo y aleatorio, **distinto en cada servicio** |
| `WEB_ORIGINS` | Dominio de Vercel, por ejemplo `https://memoria-fcen.vercel.app` (lo usan las subidas grandes, que van directo) |
| `WEB_ADMINS` | Correos @unal.edu.co que administran usuarios en ese servicio |
| `WEB_DOMINIO` | `unal.edu.co` (valor por defecto) |
| `WEB_AUTH_DEV` | No definir. Aunque se defina, se ignora en Railway |

En Google Cloud Console, el cliente OAuth necesita como «orígenes de JavaScript
autorizados» el dominio de Vercel (y `http://localhost:3000` para pruebas).

## Despliegue de práctica

Para capacitaciones, un proyecto de Vercel aparte con `NEXT_PUBLIC_PRACTICA=true` y las
variables `NEXT_PUBLIC_API_*_PRACTICA` (la web usa solo esas, sin volver a las de
producción) muestra el banner «ENTORNO DE PRÁCTICA · datos ficticios». Pasos completos en
[`docs/entorno-practica.md`](../docs/entorno-practica.md).
