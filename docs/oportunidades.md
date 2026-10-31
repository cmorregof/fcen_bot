# Estudiantes y oportunidades (vigía semanal)

Servicio `BOT_SERVICIO=oportunidades`. Fase 3 del plan: vigía semanal de ofertas de empleo, prácticas, pasantías, convocatorias y becas para los programas de la FCEN, con dos agentes (**buscador** y **verificador**) y **revisión humana del boletín** antes de que salga.

```
fuentes activas ──► buscador (modelo lee la página) ──► encontrada
                                                         │
                       verificador (reglas fijas) ◄──────┘
                         │ pasa todo           │ algo falla
                         ▼                     ▼
                     verificada         cola de revisión (con motivos)
                         │                     │ persona: corrige, verifica o descarta
                         ▼                     ▼
     persona: «Aprobar para el boletín» ──► aprobada
                         │
     borrador semanal por programa (plantilla fija, sin modelo)
                         │
     persona: «Aprobar y publicar» ──► publicada ──► exportar texto/HTML ──► correo (lo envía una persona)
```

Cualquier oferta, salvo una publicada, puede pasar a **descartada** con un motivo escrito.

## Lo que hace y lo que no

- El modelo **lee y resume**; no decide si una oferta sirve, no aprueba y no publica.
- El verificador usa **reglas deterministas**. El modelo solo deja **dudas**, que mandan la oferta a la cola.
- «Aprobada para boletín» y «Aprobar y publicar» son **botones de una persona** con rol `oportunidades` (o `admin`). Cada cambio queda en `opo_historial`: quién, cuándo y por qué.
- MemorIA **no envía** el boletín en esta versión: se exporta en texto o HTML y una persona lo manda por correo.
- **No hay datos de estudiantes.** No hay tablas de estudiantes ni de postulaciones, y el boletín no guarda destinatarios. A las ofertas se les quitan correos y teléfonos (`texto.sin_contactos`) y el modelo tiene instrucción de no copiar nombres de personas. El registro de entidades guarda datos de la entidad, no de sus contactos.

## Por qué un servicio propio

Va como servicio aparte, no como módulo de actas:

- **Aislamiento.** Tiene su propia base (esquema `oportunidades` en la misma Postgres) y sus propias sesiones web. Actas maneja datos sensibles de estudiantes; este servicio maneja información pública. Mezclarlos ampliaría sin necesidad quién tiene acceso a qué.
- **Otro público y otro ritmo.** Lo opera Extensión, Bienestar o la persona que designe la Decanatura, con un cron semanal. Actas lo operan las áreas curriculares, todos los días.
- **Cambios mínimos en lo común.** Se tocan pocas líneas: el `Literal` de `BOT_SERVICIO`, `ROLES_POR_SERVICIO`, el despacho, el router web, una ruta `/internal/vigia-semanal`, la siembra de práctica y la lista de herramientas de la web. El flujo de solicitudes de actas no se toca.
- No tiene bot de Telegram en esta versión: `manejar_update` ignora los updates.

## Roles

| Rol | Puede |
|---|---|
| `oportunidades` (nuevo) | Correr la vigía, revisar la cola, corregir, verificar, aprobar para boletín, descartar, registrar ofertas y entidades, rehacer el borrador y **Aprobar y publicar**. |
| `decanatura` | Consultar todo (ofertas, cola, empresas, boletín, tablero) y exportar. No cambia nada. |
| `admin` | Lo mismo que `oportunidades`, y además administrar usuarios. |

Se llama `oportunidades` y no `extension` porque está definido por la tarea, no por la dependencia. Así la Decanatura puede asignarlo a quien quiera.

## Modelo de datos (tablas `opo_*`)

- `opo_ofertas`: fuente y URL (más `url_clave`, la URL normalizada para encontrar duplicados), título, entidad (y `entidad_id` si está registrada), tipo (`empleo`, `practica`, `pasantia`, `convocatoria`, `beca`), programas FCEN (claves de `app/core/programas.py`), áreas tal como las pide la oferta, resumen, requisitos, fecha de cierre, modalidad (`presencial`, `remota`, `hibrida`, `sin_dato`) y lugar. También guarda el estado, los motivos del verificador, las dudas del modelo, el motivo del descarte, y quién y cuándo verificó, aprobó, publicó o descartó.
- `opo_historial`: cada transición, con quién y una nota.
- `opo_entidades`: registro de empresas y entidades: tipo, sector, sitio web, si es **aliada**, convenio y notas.
- `opo_corridas`: cada vigía: origen (cron o web), resultado por fuente, conteos, tokens y costo.
- `opo_boletines`: uno por semana ISO (`2026-S44`), con el texto, el HTML, los ids de las ofertas, quién lo generó y quién lo aprobó.

## Fuentes (`config/oportunidades.yaml`)

Una fuente se puede consultar solo si cumple las tres condiciones:

1. es **pública**: no hay que iniciar sesión;
2. su **robots.txt** permite la página;
3. sus **términos de uso** no prohíben la consulta automatizada.

**Todas empiezan con `activa: false`.** La Decanatura aprueba cada una antes de encenderla.

| Fuente | Tipo | Justificación legal | Justificación técnica |
|---|---|---|---|
| MinCiencias: convocatorias (`minciencias.gov.co/convocatorias/todas`) | Convocatorias, becas | Información pública de una entidad del Estado (Ley 1712 de 2014) | robots.txt permite `/convocatorias` y pide `Crawl-delay: 10`, que se respeta. HTML estático |
| MinCiencias: oportunidades de formación | Becas de posgrado | Igual | Igual |
| Colfuturo: becas y descuentos | Becas en el exterior | Página pública de una fundación sin ánimo de lucro. **Antes de encenderla, revisar sus términos** | robots.txt no prohíbe la ruta |
| UNAL Manizales: convocatorias (`convocatoria.manizales.unal.edu.co`) | Convocatorias internas, auxiliares, monitorías | Sitio institucional de la Sede. Conviene confirmar con la Dirección de Sede | robots.txt sin restricciones |
| UNAL: Programa de Egresados (`egresados.unal.edu.co`) | Empleo, convocatorias | Portal público de la Universidad | robots.txt solo prohíbe `/wp-admin/` |

**Excluidas** (también están en el YAML y se ven en la web):

- **Bolsa de Empleo SIE (UNAL):** exige cuenta y el servicio no inicia sesión. Alternativa: pedir al Programa de Egresados un reporte periódico.
- **LinkedIn, Computrabajo, elempleo y similares:** sus términos prohíben la extracción automatizada. Alternativa: que las empresas aliadas envíen sus ofertas y se registren a mano.
- **Servicio Público de Empleo:** la búsqueda se arma con JavaScript. Alternativa: datos abiertos o un servicio web oficial.
- **ICETEX:** su robots.txt no respondió en la revisión del 31-oct-2026.

Estas condiciones se revisaron el 31-oct-2026. Los sitios cambian, así que conviene revisarlas otra vez al encender cada fuente.

### Cómo se consulta (`transporte.py`)

- Antes de cada sitio se lee **robots.txt**, en cada corrida. Si robots.txt no responde (error de red, 5xx, 401 o 403), el sitio **no se consulta**. Si da 404, se entiende que no hay restricciones (es lo estándar).
- Se respeta el **Crawl-delay** y se deja una pausa mínima entre pedidos al mismo sitio (`OPORTUNIDADES_PAUSA_SEGUNDOS`, 5 s por defecto).
- La consulta se identifica con un **User-Agent** propio (`OPORTUNIDADES_USER_AGENT`).
- Solo hace GET: sin cookies, sin credenciales y sin captchas. Ante **401, 403 o 429** no insiste: lo registra como «bloqueada» y sigue con la siguiente fuente.
- Cada fuente pide **una página por semana**. Para verificar el enlace de cada oferta nueva se pide **una vez** esa página.

## Buscador

Para cada fuente activa:

1. Descarga la página y la convierte a texto, conservando los enlaces (`texto.a_texto`).
2. El modelo devuelve una lista estructurada (`PaginaLeida` de Pydantic, como en el resto del repositorio).
3. Normaliza con reglas fijas (`buscador.normalizar`):
   - si el **enlace** que dio el modelo no está en la página, se usa el de la fuente y se anota una duda (el modelo no puede inventar enlaces);
   - los programas que no existen se quitan y queda una duda;
   - se borran correos y teléfonos.
4. Si la oferta ya existe (mismo enlace y mismo título), no se vuelve a guardar.

El gasto de cada corrida tiene tope: `OPORTUNIDADES_TOPE_USD_CORRIDA`, 1 USD por defecto. Al alcanzarlo, las fuentes que faltan quedan como «tope». Sin `ANTHROPIC_API_KEY` el buscador no corre, pero el verificador y el boletín sí.

## Reglas del verificador

Están en `verificador.py`. Una oferta queda «verificada» solo si pasa **todas**:

| Regla | Qué comprueba |
|---|---|
| `campos` | Tiene título, entidad y enlace. |
| `enlace_vivo` | El enlace responde HTTP < 400, con permiso de robots.txt. Al registrar o corregir desde la web no se comprueba la red y queda como motivo para que una persona lo revise. |
| `dominio` | El enlace es del sitio de la fuente o de uno de sus `dominios`. |
| `cierre` | Tiene fecha de cierre y faltan al menos `OPORTUNIDADES_DIAS_MINIMOS_CIERRE` días (2 por defecto). |
| `programa` | Aplica a uno o más programas de `app/core/programas.py`. |
| `duplicado` | No hay otra oferta anterior viva con el mismo enlace, ni con la misma entidad y el mismo título. |
| `dudas` | El modelo no anotó dudas. |

Lo que no pasa queda en la **cola de revisión** con cada motivo. Ahí una persona puede corregir programas o fecha (la oferta se revisa otra vez), marcarla como verificada (si tiene motivos, debe escribir qué revisó) o descartarla con motivo.

## Boletín

- Se arma con una **plantilla fija**, sin modelo: una sección por programa en el orden de `app/core/programas.py`, ordenadas por fecha de cierre. Una oferta que aplica a varios programas sale en cada uno.
- Solo entran ofertas **aprobadas para boletín** que no cierren en los próximos `DIAS_MINIMOS_CIERRE` días.
- **Aprobar y publicar** comprueba que todas sus ofertas sigan aprobadas. Si alguna cambió, pide rehacer el borrador. Después marca el boletín y sus ofertas como publicados y guarda quién lo aprobó y cuándo.
- Se exporta en `.txt` o en `.html` (estilos en línea, listo para pegar en un correo).
- Un boletín publicado no se rehace.

## Web

Pantallas en `web/src/app/oportunidades/`, todas con el patrón `Pantalla` («qué hace / qué no hace»):

- `/oportunidades`: cola de revisión y verificadas por aprobar.
- `/oportunidades/ofertas`: todas las ofertas con filtros, fuentes, excluidas, corridas, «Correr la vigía ahora» y registro manual.
- `/oportunidades/empresas`: registro de empresas y entidades aliadas.
- `/oportunidades/boletin`: borrador, «Aprobar y publicar», exportar y boletines anteriores.

El tablero de la Facultad muestra las cifras del servicio (`/oportunidades/tablero`). `/oportunidades/resumen` reúne los conteos por programa, tipo, entidad y fuente, que sirven de insumo para el informe estudiantes–empresas.

## Cron semanal

`.github/workflows/vigia-semanal.yml` corre los lunes a las 6:00 a. m. (hora de Bogotá) y llama a `POST /internal/vigia-semanal` con `X-Cron-Secret`.

- Sin `OPORTUNIDADES_VIGIA_ACTIVA=true`, responde `activo=false` y no hace nada.
- Busca, verifica y deja el borrador del boletín listo para revisar en la mañana. **No publica.**
- No corren dos vigías a la vez: la segunda recibe 409. Una corrida que quedó colgada más de 2 horas se marca como «interrumpida».

Secretos de GitHub: `OPORTUNIDADES_APP_URL` (la URL del servicio) e `INTERNAL_CRON_SECRET`.

## Despliegue en Railway

Mismo patrón que calidad y admisión (`docs/despliegue-servicios.md`, `docs/base-de-datos.md`):

1. Crear un servicio nuevo a partir del mismo repositorio y rama, por ejemplo `fcen-oportunidades`, con el `Dockerfile` de la raíz y un dominio público.
2. Configurar sus variables:

   ```
   BOT_SERVICIO=oportunidades
   DATABASE_URL=${{Postgres.DATABASE_URL}}   # la misma Postgres de los demás
   DB_SCHEMA=oportunidades                   # o vacío: se deriva del servicio
   DATA_DIR=/data                            # volumen (media/out); la base va a Postgres
   ANTHROPIC_API_KEY=…                       # puede ser la misma; mejor una key propia para ver el gasto aparte
   INTERNAL_CRON_SECRET=…
   WEB_SESSION_SECRET=…                      # propio de este servicio
   WEB_GOOGLE_CLIENT_ID=…
   WEB_ADMINS=…
   WEB_ORIGINS=https://memoria-fcen.vercel.app
   OPORTUNIDADES_VIGIA_ACTIVA=false          # true cuando la Decanatura apruebe las fuentes
   # Opcionales: OPORTUNIDADES_MODELO, OPORTUNIDADES_TOPE_USD_CORRIDA,
   # OPORTUNIDADES_PAUSA_SEGUNDOS, OPORTUNIDADES_DIAS_MINIMOS_CIERRE,
   # OPORTUNIDADES_USER_AGENT
   ```

   No necesita `TELEGRAM_BOT_TOKEN`.
3. En Vercel, agregar `NEXT_PUBLIC_API_OPORTUNIDADES=https://fcen-oportunidades.up.railway.app` y volver a desplegar.
4. En GitHub, agregar el secreto `OPORTUNIDADES_APP_URL`.
5. En la web, como admin, autorizar los correos con rol `oportunidades` o `decanatura`.
6. Encender las fuentes aprobadas en `config/oportunidades.yaml` (PR) y luego `OPORTUNIDADES_VIGIA_ACTIVA=true`.

El esquema `oportunidades` se crea solo al arrancar. La copia nocturna a Drive (`respaldo-drive.yml`, que ya incluye este servicio con el mismo secreto `OPORTUNIDADES_APP_URL`) y los respaldos de Railway Pro lo cubren igual que a los demás.

**Entorno de práctica:** con `MEMORIA_PRACTICA=true` se siembran 2 entidades y 3 ofertas ficticias (dominio `ejemplo.invalid`).

**En local:** `make web-local` levanta también este servicio en el puerto 8004.

## Costos del modelo por corrida

Solo el buscador llama al modelo: una vez por fuente activa y por semana. El verificador y el boletín no usan el modelo.

Estimado por fuente, con `OPORTUNIDADES_MAX_CARACTERES_PAGINA=30000`:

- entrada: unos 8 000 tokens de página, más unos 2 000 de instrucciones, lista de programas y esquema (en total, unos 10 000);
- salida: unos 2 000 tokens para unas 10 ofertas.

Con los precios configurados en `PRECIO_INPUT_MTOK` y `PRECIO_OUTPUT_MTOK` (2 y 10 USD por millón de tokens, los valores por defecto del repositorio):

| | Por fuente | 5 fuentes (corrida) | Al mes (4–5 corridas) |
|---|---|---|---|
| Entrada | 10 000 × 2 / 1 M = 0,020 USD | 0,10 USD | |
| Salida | 2 000 × 10 / 1 M = 0,020 USD | 0,10 USD | |
| **Total** | **≈ 0,04 USD** | **≈ 0,20 USD** | **≈ 0,8–1,0 USD** |

El costo real de cada corrida queda en `opo_corridas` y se ve en «Ofertas y fuentes». Confirme el precio vigente del modelo en la Console de Anthropic y ajuste `PRECIO_*` si cambia. El tope por corrida (1 USD) cubre más de 20 fuentes.

## Pendiente de definir con la Decanatura

1. **Qué fuentes se encienden** y si se pide permiso escrito a Colfuturo y a la Dirección de Sede. También si se busca un acuerdo con el Programa de Egresados para recibir la Bolsa SIE.
2. **Quién tiene el rol `oportunidades`**: Extensión, Bienestar o una persona de la Decanatura. También a quién se envía el boletín (listas de programa, egresados) y por qué canal.
3. **Programas de cada oferta:** si basta con la afinidad «evidente» que hoy propone el modelo, o si cada área curricular define palabras clave por programa para hacer la regla determinista.
4. **Empresas aliadas:** de dónde sale la lista inicial (convenios vigentes de prácticas) y quién la mantiene.
5. **Informe estudiantes–empresas:** qué preguntas debe responder. Hoy solo hay cifras agregadas de ofertas (`/resumen`). Cruzarlas con estudiantes (prácticas realizadas, empleabilidad) exige datos personales y un aval de tratamiento de datos, por eso queda fuera de esta versión.
6. **Envío automático** del boletín por correo (Gmail o la lista institucional): queda para una versión futura, siempre detrás del botón.
7. **Aviso legal del boletín** (pie de página): la redacción la debe revisar la Decanatura o Jurídica.
