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

Cada programa tiene una imagen de firma, la de quien firma (el primer
integrante). Las imágenes viven en el volumen del servicio de actas, en la
carpeta `firmas/`, con el nombre de la clave del programa: `matematicas.jpg`,
`ciencias_computacion.png`, `estadistica.jpg`. Se aceptan PNG o JPG de hasta
2 MB. En el documento se ajustan a 1,8 cm de alto y máximo 6 cm de ancho.

- El borrador nunca lleva la firma: dice «[la firma se agrega al firmar]».
- El documento final (`borrador=False`) la inserta encima del nombre y el
  cargo del firmante. Si falta la imagen, queda «[falta la imagen de la
  firma]» en amarillo.

Hoy el bot y la web solo generan borradores: el paso de firmar (`/firmar`,
fase 3 del README) todavía no existe. Las firmas quedan cargadas para cuando
ese paso genere el documento final.

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

En local se usa el mismo comando con la ruta del archivo:
`uv run python -m app.services.firmas cargar estadistica "Firma Nubia.jpg"`.
La carpeta local es `data/actas/firmas/`, que está fuera de git.

### Dónde quedan

En `FIRMAS_DIR`. Si no se define, `<DATA_DIR>/actas/firmas` (en Railway,
`/data/actas/firmas`). Si el servicio de actas todavía usa la base antigua en
`/data/fcen.db`, la carpeta es `/data/firmas`. El comando del paso 4 muestra la
ruta real.

La copia nocturna a Drive respalda la base, no esta carpeta. Guarde las
imágenes originales en un lugar seguro, fuera del repositorio, para volver a
cargarlas si se pierde el volumen.
