# Revisor de soportes para el cierre de un plan de mejoramiento

Prepara, para revisión humana, el cierre de un plan de mejoramiento: describe
cada soporte, cruza los soportes de cada acción con su indicador y redacta un
borrador para el informe de autoevaluación.

**El modelo no decide.** Veredictos, porcentajes y párrafos son propuestas.
Las aprueban la oficina de calidad, el Comité Asesor y el Consejo de Facultad.

## Pasos

| Paso | Quién | Qué hace |
|---|---|---|
| Inventario | código | Recorre la carpeta y asigna cada archivo a su acción por la carpeta `ACCION n.n`. Registra tipo, tamaño, páginas y fecha de metadatos. Lista los zip por dentro y omite `.ini` y archivos de sistema. |
| Descripción | Sonnet 5.5 | Por archivo: qué es, fecha, qué podría probar, si se ve ilegible o incompleto. |
| Cruce | Opus 5.5 | Por acción: veredicto («evidencia suficiente», «parcial», «sin evidencia»), justificación, lo que falta, % de avance y párrafo de cierre, con citas `[S012]`. |
| Verificador | código | Cada cita debe existir en el inventario. Marca (no borra) las que no, y las incoherencias (p. ej. «suficiente» con menos de 100 %). |
| Salidas | código | `inventario_soportes.xlsx`, `cruce_acciones.xlsx`, `borrador_cierre.docx`. |

## Qué se le manda al modelo

- PDF: las primeras 4 páginas y hasta 6000 caracteres del texto extraído.
- Imágenes: reducidas a 1568 px por el lado mayor.
- xlsx: solo los nombres de las hojas, los encabezados y el número de filas. Nunca las filas.
- docx: el texto de los primeros párrafos.
- Los correos electrónicos se reemplazan por `[correo]`.
- Del plan no se lee la columna de responsables.

## Uso

```bash
uv run python scripts/cierre_plan.py \
  --carpeta ~/fcen_insumos/calidad/MCMA_proceso1 \
  --plan ~/fcen_insumos/calidad/MCMA_proceso1/"1. Plan de mejoramiento 2016/Plan de mejoramiento MCMA 2016.xlsx" \
  --salidas ~/fcen_insumos/calidad/salidas/MCMA_cierre \
  --programa "Maestría en Ciencias – Matemática Aplicada" \
  --env /ruta/al/.env  [--estimar]
```

- `--estimar` calcula el costo sin llamar al modelo. Descuenta lo que ya está en caché.
- Las salidas deben quedar fuera del repositorio; el script se niega a escribir dentro.
- La caché (`<salidas>/.cache`) guarda cada respuesta por hash del archivo. Volver a correr retoma donde quedó y solo paga lo que falta.
- Si la cuenta se queda sin créditos o la clave es inválida, la corrida se detiene en la primera llamada fallida.

## Revisión humana

1. `inventario_soportes.xlsx`: columnas «¿Correcto? (Sí/No)» y «Corrección».
2. `cruce_acciones.xlsx`: columnas «Aprobado» y «Ajuste». La columna «Alertas» trae lo que marcó el verificador.
3. `borrador_cierre.docx`: lleva el encabezado «BORRADOR — requiere revisión y aprobación de la oficina de calidad, del Comité Asesor y del Consejo de Facultad». Las citas aparecen como `[S012 · archivo.pdf]`; las que no se verificaron, con ⚠.

## Límites conocidos

- De un PDF largo el modelo ve solo las primeras páginas: la descripción lo dice.
- De un xlsx el modelo no ve el contenido: no puede confirmar cifras.
- La fecha de metadatos suele ser la de la copia del archivo, no la del documento.
- De un xlsx el modelo solo sabe cuántas filas tiene: no puede verificar si los registros caen en el periodo del plan.

## Referencia de costo

Piloto de MCMA (153 archivos, 19 acciones): 5,91 USD en total y unos 7 minutos.
Sonnet describió los archivos por unos 4,3 USD y Opus hizo los cruces y el resumen por unos 1,6 USD.
