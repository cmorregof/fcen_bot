# Revisor de soportes para el cierre de un plan de mejoramiento

Prepara, para revisión humana, el cierre de un plan de mejoramiento: describe
cada soporte, cruza los soportes de cada acción con su indicador y redacta un
borrador para el informe de autoevaluación.

**El modelo no decide.** Veredictos, porcentajes y párrafos son propuestas. La
oficina de calidad las revisa y las corrige, el Comité Asesor recomienda
aprobar o no aprobar el cierre y el Consejo de Facultad decide.

Por ahora se corre a mano con un script. No está expuesto en la web ni en
Telegram.

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

Opciones: `--concurrencia N` (4 por defecto), `--env RUTA` (archivo con
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
