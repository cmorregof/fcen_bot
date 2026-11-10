# Integrantes de los comités y firmas

El repositorio es público. Por eso aquí solo van los cargos institucionales
(profesores y coordinadores). El nombre de la representación estudiantil y las
imágenes de firma se configuran en el servicio de actas, fuera del código.

## Integrantes

Están en `app/core/programas.py`, en el campo `miembros` de cada programa,
con un comentario que dice de dónde salen. El primero de la lista firma el
oficio y el acta. Si cambia un integrante, se edita esa lista y se abre un PR.

Los de Matemáticas, Ciencias de la Computación y Estadística salen del correo
de la administrativa del área del 3-nov-2026.

En una dirección con comité único (el Área Curricular de Posgrados de Ciencias
Exactas, `docs/direcciones.md`), los integrantes están en la dirección, no en
cada programa. Los del comité de posgrados salen del acta 029, que envió la
administrativa de posgrados el 10-nov-2026. Firma el director, «Director Área
Curricular Posgrados Ciencias Exactas Naturales» (`cargo_firma`, el cargo bajo
la firma cuando no es el de ASISTENTES). El director también coordina la
Especialización en Actuaría y Finanzas: aparece dos veces en ASISTENTES, como
en el acta, y una sola vez en el botón **Concepto**.

En el bot y en la web, el botón **Concepto** ofrece los integrantes que tienen
nombre. Los demás se escriben a mano con «Otro miembro».

## Representación estudiantil

Un comité con representación estudiantil la declara en `programas.py` con su
cargo, por ejemplo `representante_estudiantil="Representante Estudiantil
(suplente)"` en Matemáticas. El nombre va en una variable de entorno del
servicio `actas`:

```
REPRESENTANTES_ESTUDIANTILES=matematicas=Nombre Apellido
```

Si hay varios comités, se separan con punto y coma:
`matematicas=Nombre Uno;estadistica=Nombre Dos`. La clave es la del programa
en `programas.py`.

- En Railway: servicio `actas` → **Variables** → `REPRESENTANTES_ESTUDIANTILES`.
  Railway reinicia el servicio al guardar.
- En local: en el archivo `.env`, que no se sube al repositorio.

Con la variable, el acta pone en ASISTENTES «Nombre Apellido, Representante
Estudiantil (suplente).», y el nombre aparece en el botón **Concepto**. Su
concepto sale como «Nombre Apellido expresa: …», sin «El profesor». Sin la
variable, el acta deja «[nombre]» en amarillo para completarlo en Word.

Cuando cambie la representante, basta con cambiar la variable.

## Firmas

Cada comité tiene una imagen de firma, la de quien firma (el primer
integrante). Las imágenes viven en el volumen del servicio de actas, en la
carpeta `firmas/`, con el nombre de la clave del comité: la del programa en
pregrado (`matematicas.jpg`, `ciencias_computacion.png`, `estadistica.jpg`) y
la de la dirección en un comité único (`posgrados_matematicas.jpg`). Se aceptan PNG o JPG de hasta
2 MB. En el documento se ajustan a 1,8 cm de alto y máximo 6 cm de ancho.

- El borrador nunca lleva la firma: dice «[la firma se agrega al firmar]».
- El documento final (`borrador=False`) la inserta encima del nombre y el
  cargo del firmante. Si falta la imagen, queda «[falta la imagen de la
  firma]» en amarillo.

El documento final sale del paso de firmar, descrito más abajo.

### Cargar las firmas en Railway

Requiere la CLI de Railway con sesión iniciada. Para cada firma:

1. En el Mac, copiar la imagen en base64 al portapapeles:

   ```bash
   base64 -i "Firma David.jpg" | pbcopy
   ```

2. Abrir una terminal en el contenedor de actas:

   ```bash
   railway ssh --service actas
   ```

3. Dentro, cargarla con la clave del programa, pegar (⌘V), Enter y Ctrl-D:

   ```bash
   uv run --no-dev python -m app.services.firmas cargar matematicas
   ```

   El comando revisa que sea PNG o JPG, la guarda y reemplaza la anterior.

4. Comprobar:

   ```bash
   uv run --no-dev python -m app.services.firmas
   ```

   Muestra la carpeta y, por programa, si tiene firma y quién firma.

Firmas del 3-nov-2026: «Firma David» → `matematicas`, «Firma prof Fabian» →
`ciencias_computacion`, «Firma Nubia» → `estadistica`.

**Comité de posgrados.** Su acta la firma David Ocampo, como director del área
de posgrados, y se busca con la clave de la dirección. La imagen cargada como
`matematicas.jpg` no se usa para esta acta: hay que cargar la misma imagen con
la otra clave. En el paso 3:

```bash
uv run --no-dev python -m app.services.firmas cargar posgrados_matematicas
```

Mientras no esté, el resumen de la firma avisa «Falta la imagen de firma de
David Leonardo Ocampo Rodríguez (posgrados_matematicas)».

En local se usa el mismo comando con la ruta del archivo:
`uv run python -m app.services.firmas cargar estadistica "Firma Nubia.jpg"`.
La carpeta local es `data/actas/firmas/`, que está fuera de git.

## Firmar el oficio y el acta

Firmar es una acción explícita de una persona autorizada: la administrativa
de la dirección, facultada para firmar en nombre de quien preside el comité, o
admin, siempre de su propia dirección. El modelo no interviene. Código:
`app/services/firma.py`. Pruebas: `tests/test_firma.py`.

**En el bot.** `/firmar` muestra un botón por programa con casos recomendados
(en posgrados, uno solo: «Firmar Comité de posgrados»).
`/firmar <programa>` acepta la clave o el nombre, por ejemplo `/firmar
estadistica` o `/firmar ciencias de la computación`.

1. **Resumen.** Quién firma, los casos que entran (los que tienen
   recomendación del comité: aprobar o no aprobar) y las advertencias: los
   casos que quedan fuera (pendientes o sin ficha), **la falta de la imagen de
   firma del programa**, la falta del nombre de la representación estudiantil
   y la falta de LibreOffice (sin PDF). No se puede firmar si no hay casos
   recomendados, si el programa no tiene integrantes del comité en
   `programas.py` o si un caso está en una etapa que no puede ir al Consejo.
2. **Datos.** El bot pide responder a su mensaje con esta plantilla:

   ```
   Radicado: Mz.FCEN.1.065-012-26
   Acta: 019
   Fecha: 05/11/2026
   Hora: 10:00 a. m.
   Lugar: Sala de reuniones del bloque …
   ```

   El radicado viene propuesto: el siguiente consecutivo de la dirección en el
   año, con el prefijo del programa (`radicado_prefijo` en `programas.py`) o,
   si no lo tiene, el último que confirmó la dirección. La dirección emite
   otros oficios por fuera de MemorIA, así que la persona lo corrige si ese
   número ya se usó. Debe tener la forma `Mz.FCEN.1.0xx-NNN-AA` y el año en
   curso, y no puede repetirse. La fecha va como DD/MM/AAAA o AAAA-MM-DD. El
   lugar puede ser «sesión ad referéndum».
3. **Confirmación.** El bot repite el resumen con los datos y muestra
   **✍️ Firmar** y **Cancelar**. Nada se firma antes.
4. **Documentos finales.** Genera el oficio y el acta con `borrador=False`:
   sin la marca de borrador, con el radicado, el número y los datos de la
   sesión, y con la imagen de firma encima del nombre y el cargo (si falta,
   «[falta la imagen de la firma]» en amarillo). Envía el .docx y el PDF de
   cada uno y el SHA-256 de cada archivo.

**En la web.** Pantalla «Oficio y acta», botón **Firmar…** de cada programa:
el mismo resumen, un formulario con el radicado propuesto y los datos de la
sesión, «Revisar antes de firmar» y, para firmar, la casilla «Confirmo que el
comité trató estos casos y que firmo en nombre de …» y el botón **Firmar**. La
lista «Documentos firmados» guarda las firmas de la dirección para volver a
descargarlas. La descarga comprueba el SHA-256: si el archivo del volumen no
coincide con el que se firmó, no se entrega.

Si los casos del programa cambian entre el resumen y la confirmación (llega
una recomendación nueva, por ejemplo), no se firma y hay que revisar de nuevo.

### Qué se registra

En la base del servicio (SQLite o Postgres, `docs/base-de-datos.md`):

- `firmas`: dirección, programa, radicado (único), número de acta, fecha,
  hora y lugar de la sesión, casos incluidos, quién firma (el integrante del
  comité), quién firmó en su nombre (`firmado_por`), su rol, el canal
  (telegram o web), si llevaba la imagen de firma y cuándo se firmó (`firmado`,
  UTC).
- `firma_archivos`: por cada documento (oficio o acta) y formato (docx o
  pdf), la ruta en el volumen y su SHA-256.
- `firmas_pendientes`: los datos que esperan la confirmación en el bot, uno
  por chat. Se borran al confirmar o cancelar.

Los archivos quedan en el volumen, en `<OUTPUT_DIR>/firmados/<año>/<dirección>/`.

En la línea del caso (`docs/flujo-solicitudes.md`), la firma registra la
transición `enviar_consejo` (oficio del comité al Consejo) con el radicado en
el detalle: el caso pasa a «en el Consejo» y sale del borrador. Desde ahí
sigue igual que siempre: decisión del Consejo, expedición y notificación.
`/cerrar_acta` sigue disponible para los oficios que se firman por fuera de
MemorIA.

### Dónde quedan

En `FIRMAS_DIR`. Si no se define, `<DATA_DIR>/actas/firmas` (en Railway,
`/data/actas/firmas`). Si el servicio de actas todavía usa la base antigua en
`/data/fcen.db`, la carpeta es `/data/firmas`. El comando del paso 4 muestra la
ruta real.

La copia nocturna a Drive respalda la base, no esta carpeta. Guarde las
imágenes originales en un lugar seguro, fuera del repositorio, para volver a
cargarlas si se pierde el volumen.
