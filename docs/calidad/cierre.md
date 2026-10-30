# Revisor de soportes para el cierre de un plan de mejoramiento

Prepara, para revisión humana, el cierre de un plan de mejoramiento: describe
cada soporte, cruza los soportes de cada acción con su indicador y redacta un
borrador para el informe de autoevaluación.

**El modelo no decide.** Veredictos, porcentajes y párrafos son propuestas. La
oficina de calidad las revisa y las corrige, el Comité Asesor recomienda
aprobar o no aprobar el cierre y el Consejo de Facultad decide.

Se corre desde la web (pantalla «Revisión de soportes», rol calidad o admin)
o a mano con un script. No está en Telegram. **En la web está apagada** hasta
que exista el aval de tratamiento de datos (ver «Desde la web»).

## Pasos

| Paso | Quién | Qué hace |
|---|---|---|
| Plan | código | Lee las acciones del plan (ver «Formatos del plan»). |
| Inventario | código | Recorre la carpeta y asigna cada archivo a su acción por la carpeta `ACCION n.n` o `ACCIÓN n.n.n` (también dentro de un zip, o un zip llamado así). Registra tipo, tamaño, páginas, fecha de metadatos y hash. Lista los zip por dentro; omite `.ini`, archivos de sistema y enlaces simbólicos. |
| Descripción | Sonnet 5.5 (esfuerzo bajo) | Por archivo: qué es, fecha, qué podría probar, si se ve ilegible o incompleto. |
| Cruce | Opus 5.5 (esfuerzo alto) | Por acción: veredicto («evidencia suficiente», «parcial», «sin evidencia»), justificación, lo que falta, % de avance y párrafo de cierre, con citas `[S012]`. |
| Resumen | Opus 5.5 (esfuerzo medio) | Un resumen general del cierre a partir de los cruces. |
| Sugerencias | Opus 5.5 (esfuerzo medio) | Solo para las acciones «sin evidencia»: una sola llamada propone dónde buscar soportes y qué acción poner en el próximo plan. Va aparte y no cambia el veredicto. |
| Verificador | código | Revisa cada cita (ver abajo). Marca, no borra. |
| Salidas | código | `inventario_soportes.xlsx`, `cruce_acciones.xlsx`, `borrador_cierre.docx` y `reporte_sin_evidencia.md`. |

## Formatos del plan

- **Plantilla institucional** (cinco hojas, la que lee el bot): si el libro
  tiene la hoja «2. Plan de Mejora», se lee con el mismo lector del bot
  (`app/servicios/calidad/plantilla.py`). El modelo es el mismo:
  programa → objetivo → acción → tareas. Al cruce le llegan la oportunidad de
  mejora, el objetivo con su meta, la acción, el indicador, las fechas, las
  tareas del cronograma con su soporte esperado y las marcas («NO FUNCIONÓ»).
  Los códigos son los del plan (1.1.1), así que las carpetas de soportes deben
  llamarse `ACCIÓN 1.1.1`.
- **Formato 2016** (una sola hoja), anterior a la plantilla: aspecto,
  objetivo, acciones, fechas e indicador. Las acciones se numeran por aspecto
  (1.1, 1.2, 2.1…). Es el formato del piloto de MCMA y el lector del bot no lo
  lee, por eso se conserva aparte (`soportes/plan_acciones.py`).

En los dos casos el cruce usa una vista mínima de la acción
(`soportes.modelos.Accion`), no un segundo modelo del plan. Los responsables
no se leen. El % de avance declarado en el plan no se le manda al modelo: va
en `cruce_acciones.xlsx` junto al propuesto, para que la persona compare.

## Verificador de citas

Una cita `[S012]` (o un grupo `[S012, S013]`) es válida solo si:
1. el ID está en el inventario;
2. el archivo se le mostró al modelo en esa acción (soportes de la acción o
   documentos generales del plan);
3. el archivo tiene descripción, es decir, el modelo vio su contenido.

Las que no cumplen se marcan con ⚠ en las tres salidas y **no cuentan como
evidencia**. Las citas del resumen general solo valen si alguna acción las
citó de forma válida. También se marcan las incoherencias: «suficiente» con
menos de 100 %, «sin evidencia» con más de 0 %, un veredicto sin ninguna cita
válida o un párrafo de cierre sin citas.

## Qué se le manda al modelo

Solo a la API de Anthropic; ningún otro servicio recibe archivos.
- PDF: las primeras 4 páginas y hasta 6000 caracteres del texto extraído.
- Imágenes: reducidas a 1568 px por el lado mayor.
- xlsx: los nombres de las hojas, los encabezados y cuántos registros hay por
  semestre o año, contados por el programa. Nunca las filas.
- docx: el texto de los primeros párrafos.
- Los correos electrónicos se reemplazan por `[correo]`.
- Del plan no se leen responsables.

## Cómo correrlo

Los soportes, el plan y las salidas viven fuera del repositorio. El script se
niega a escribir salidas dentro de él y a leer soportes dentro de él (salvo
`casos_reales/`, que está en `.gitignore`).

```bash
export SOPORTES="/ruta/a/la/carpeta/de/soportes"   # carpetas ACCION n.n
export PLAN="/ruta/al/plan.xlsx"                    # plantilla o formato 2016
export SALIDAS="/ruta/fuera/del/repo/cierre_programa"
export ANTHROPIC_API_KEY=...                        # o --env /ruta/al/.env

# 1. Solo estimar el costo (no llama al modelo):
uv run python scripts/cierre_plan.py --carpeta "$SOPORTES" --plan "$PLAN" \
  --salidas "$SALIDAS" --programa "Nombre del programa" --estimar

# 2. Correr:
uv run python scripts/cierre_plan.py --carpeta "$SOPORTES" --plan "$PLAN" \
  --salidas "$SALIDAS" --programa "Nombre del programa"
```

Opciones: `--concurrencia N` (4 por defecto), `--tope USD` (el de
`CALIDAD_REVISOR_TOPE_USD`, 10 por defecto: no corre si la estimación lo pasa
y se detiene si el gasto lo alcanza), `--env RUTA` (archivo con
`ANTHROPIC_API_KEY` y, si aplica, `ANTHROPIC_WORKSPACE_ID`; la clave nunca se
imprime).

- La caché (`$SALIDAS/.cache`) guarda cada respuesta: las descripciones por
  hash del archivo, modelo y versión del prompt; cruces, resumen y
  sugerencias por el texto exacto que se envía y el prompt del sistema.
  Volver a correr retoma donde quedó y solo paga lo que cambió o faltó.
- Si la cuenta se queda sin créditos, la clave es inválida o el modelo no
  existe, la corrida se detiene en la primera llamada fallida; las llamadas
  que no se hicieron no cuentan en el costo.
- La caché contiene descripciones de los soportes: es tan sensible como ellos
  y se queda con las salidas.

## Desde la web

Pantalla **Calidad → Revisión de soportes** (`/calidad/soportes`), solo para
los roles calidad y admin. Con `CALIDAD_REVISOR_ACTIVO=false` (por defecto) la
pantalla dice «Pendiente del aval de tratamiento de datos» y toda la API del
revisor responde 403.

Pasos que ve la persona:
1. Elige el programa. El plan debe estar cargado antes en «Cargar el plan»: las
   acciones salen de la base, no de un Excel aparte.
2. Sube un zip con los soportes (carpetas `ACCIÓN 1.1.1`…). El servicio lo
   descomprime en el volumen, hace el inventario y muestra cuántos archivos
   hay, cuántos irán al modelo, cuántos ya están en la caché, el costo
   estimado, las acciones sin carpeta y las carpetas cuyo código no está en el
   plan. Todavía no llama al modelo.
3. Marca «Entiendo que esta revisión gastará unos X USD» e inicia. La
   confirmación queda atada a esa carga (`carga_id`) y a ese costo: si otra
   persona subió otro zip o el costo estimado subió, no corre y pide confirmar
   otra vez. Si la estimación pasa del tope, el botón no aparece y la API
   responde 409.
4. Ve el avance por paso (descripción, cruce, resumen y salidas) con una barra
   de progreso. Puede cerrar la página: la corrida sigue en el servidor.
5. Descarga `inventario_soportes.xlsx`, `cruce_acciones.xlsx` y
   `borrador_cierre.docx`. La pantalla repite que todo es propuesta.

«Borrar soportes» borra soportes, salidas y estado. Con la casilla «Borrar
también las descripciones guardadas» borra además la caché.

### Qué se guarda y cuándo se borra

Todo vive en el volumen del servicio, en `CALIDAD_REVISOR_DIR` (por defecto
`/data/calidad/revisor` en Railway):

| Carpeta | Qué guarda | Se borra |
|---|---|---|
| `actual/subida.zip` | el zip mientras llega | al descomprimirlo |
| `actual/soportes/` | los soportes | al terminar la corrida (bien o mal) |
| `actual/salidas/` | los tres archivos para descargar | con «Borrar soportes», al subir otro zip o a los `CALIDAD_REVISOR_RETENCION_DIAS` |
| `cache/` | descripciones, cruces, resumen y sugerencias ya pagados | con la casilla de la caché o, cada entrada, a los `CALIDAD_REVISOR_RETENCION_DIAS` |

Al arrancar el servicio, si una corrida quedó cortada (o no hay estado), se
borran los soportes y el zip a medio subir: hay que volver a subirlo. Con
`CALIDAD_REVISOR_ACTIVO=false` se borra todo lo del revisor, al arrancar y en
la primera petición a su API.

El zip llega como cuerpo de la petición, no como formulario: así no pasa por
archivos temporales fuera del volumen. Nada sale a otro servicio que no sea la
API de Anthropic. La caché es tan sensible como los soportes: describe su
contenido.

### Protecciones

- **Una corrida a la vez** por servicio. Mientras corre no se puede subir otro
  zip ni borrar. Si el servicio se reinicia a mitad, la corrida queda
  «interrumpida»: se vuelve a subir el zip y lo ya pagado sale de la caché.
  El estado vive en memoria del proceso: **exige un solo worker de uvicorn**
  (así arranca hoy el Dockerfile).
- **Tope por corrida** (`CALIDAD_REVISOR_TOPE_USD`, 10 USD): se revisa la
  estimación antes de empezar y, durante la corrida, cada llamada reserva su
  costo máximo según el tamaño real de la petición: el texto a 2,5 caracteres
  por token, 5000 tokens por página de PDF y 3300 por imagen, cobrados a 1,25x
  (escritura en caché) y a la tarifa del modelo más caro (por si responde el
  modelo de respaldo), más la salida completa. Si lo gastado más lo reservado
  pasa del tope, la llamada no sale, la corrida se detiene y las salidas traen
  lo que alcanzó. El script usa el mismo tope (`--tope`).
- **Archivos dentro de la carpeta**: no se abre ningún archivo de más de 50 MB
  ni un xlsx o docx que declare más de 200 MB descomprimido. Los zip internos
  se leen en trozos, con 50 MB por archivo y un presupuesto común de 2 GB y
  5000 archivos; lo que pasa de ahí queda en el inventario con su nota, sin
  abrir.
- **Trabajo pesado en hilos**: PDF, imágenes, Excel, Word, salidas y borrados
  corren fuera del event loop para no frenar las demás peticiones.
- **Zip**: se rechaza entero si trae rutas que salen de la carpeta (`../`,
  rutas absolutas, `C:`), enlaces simbólicos, más de
  `CALIDAD_REVISOR_MAX_ARCHIVOS` entradas (carpetas incluidas) o más de
  `CALIDAD_REVISOR_MAX_DESCOMPRIMIDO_MB` descomprimido (se cuentan los bytes
  escritos, no los declarados).

### Variables

| Variable | Por defecto | Uso |
|---|---|---|
| `CALIDAD_REVISOR_ACTIVO` | `false` | Enciende la pantalla y la API. Solo con el aval de tratamiento de datos |
| `CALIDAD_REVISOR_TOPE_USD` | `10` | Máximo por corrida, en USD |
| `CALIDAD_REVISOR_MAX_MB` | `500` | Tamaño máximo del zip |
| `CALIDAD_REVISOR_MAX_DESCOMPRIMIDO_MB` | `2000` | Máximo descomprimido |
| `CALIDAD_REVISOR_MAX_ARCHIVOS` | `5000` | Máximo de archivos en el zip |
| `CALIDAD_REVISOR_RETENCION_DIAS` | `30` | Días que se guardan salidas y caché |
| `CALIDAD_REVISOR_DIR` | junto a la base | Carpeta del volumen |
| `ANTHROPIC_API_KEY` | — | La del servicio de calidad |

### API

Todas bajo `/api/web/calidad/revisor`, con sesión de calidad o admin:

| Método y ruta | Qué hace |
|---|---|
| `GET /revisor` | Estado: carga, estimación, pasos, costo, resumen y descargas listas |
| `POST /revisor/soportes?programa=…` | Cuerpo: el zip. Descomprime, inventaría y estima |
| `POST /revisor/correr` | `{"confirmo_costo": true, "carga_id": …, "costo_usd": …}`. Verifica la carga y el costo vistos, vuelve a estimar y lanza en segundo plano |
| `GET /revisor/descargar/{inventario,cruce,borrador}` | Descarga una salida |
| `DELETE /revisor[?cache=true]` | Borra soportes y salidas (y la caché) |

### Para encenderla

1. Aval de tratamiento de datos de la Universidad para mandar soportes con
   nombres y listados a la API de Anthropic.
2. En el servicio de calidad de Railway: `CALIDAD_REVISOR_ACTIVO=true` y
   revisar `CALIDAD_REVISOR_TOPE_USD`.
3. Probar con un zip pequeño y comprobar que el proxy de Railway acepta el
   tamaño de los zip reales.

## Revisión humana

1. `inventario_soportes.xlsx`: columnas «¿Correcto? (Sí/No)» y «Corrección».
2. `cruce_acciones.xlsx`: columnas «Revisado por calidad» y «Ajuste». «Alertas»
   trae lo que marcó el verificador; «Avance declarado en el plan» y «Marcas
   del plan» vienen del plan (plantilla institucional).
3. `borrador_cierre.docx`: lleva el encabezado «BORRADOR — propuesta sujeta a
   revisión de la oficina de calidad, a la recomendación del Comité Asesor y a
   la decisión del Consejo de Facultad». Las citas aparecen como
   `[S012 · archivo.pdf]`; las no verificadas, con ⚠.

## Costo aproximado

Tarifas por millón de tokens (entrada / salida): Sonnet 5.5, 2 / 10 USD;
Opus 5.5, 4 / 20 USD. `--estimar` usa supuestos holgados y da una cota alta.

| Concepto | Referencia |
|---|---|
| Descripción | unos 0,03 USD por archivo enviado (PDF de 4 páginas o imagen) |
| Cruce | unos 0,05–0,10 USD por acción; crece con los documentos generales, que se envían en cada acción |
| Resumen y sugerencias | unos 0,10–0,30 USD en total |

Piloto de MCMA (153 archivos, 19 acciones): 5,91 USD la primera corrida
completa, en unos 7 minutos (Sonnet unos 4,3 USD; Opus unos 1,6 USD). Rehacer
xlsx, cruces y sugerencias costó 1,87 USD.

La clave de cada descripción incluye ahora la descripción y el indicador de su
acción (antes solo el código): el mismo archivo con el mismo código en otro
programa ya no reutiliza una descripción hecha con otro contexto. Por eso una
caché hecha antes de este cambio no sirve y la primera corrida vuelve a pagar
las descripciones (unos 4 USD para un plan como el de MCMA).

Después de esta revisión, la primera corrida sobre una caché anterior vuelve a
pagar los cruces, el resumen y las sugerencias (la clave ahora incluye el
prompt del sistema) y la descripción de los xlsx: del orden de 2 USD para un
plan como el de MCMA. Las descripciones de PDF e imágenes siguen en caché.

## Límites conocidos

- De un PDF largo el modelo ve solo las primeras páginas: la descripción lo dice.
- De un xlsx el modelo ve los encabezados y los conteos por periodo, no los
  registros. Si una hoja no tiene encabezado, la primera fila con datos se
  toma como encabezado.
- La fecha de metadatos suele ser la de la copia del archivo; el prompt del
  cruce pide usar la fecha de los hechos.
- Un zip dentro de otro zip no se abre: queda marcado para descomprimirlo.
- La estimación no descuenta los cruces en caché.
