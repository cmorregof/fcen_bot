# Organización de las evidencias de los planes de mejoramiento

La Dirección Académica publicó un instructivo para cargar las evidencias de las
acciones de los planes de mejoramiento en el repositorio de cada programa.
MemorIA revisa el zip de soportes contra ese instructivo apenas se sube, antes
de estimar el costo del revisor y sin llamar al modelo.

## Lo que pide el instructivo

```
Soportes de acciones/
  Acción 1.1/
    Producto final/                un único PDF, consolidado, firmado por el
                                   director del área curricular o validado
                                   por el Comité Asesor
    Soportes de producto final/    los documentos que sustentan la acción
```

Los archivos de «Soportes de producto final» se nombran así:

```
01 Correo estudiantes PEP 20251001.pdf
^^ ^^^^^^^^^^^^^^^^^^^^^^ ^^^^^^^^ ^^^^
consecutivo  descripción   fecha   extensión
```

- Máximo 50 caracteres, con espacios y extensión.
- Sin tildes ni eñes.
- Sin caracteres especiales (`/ \ : * ? " < > | # % &`). MemorIA también
  señala los demás signos de los ejemplos que se deben evitar: `!`, `( )`,
  `_`, el punto después del número.
- Consecutivo de dos dígitos y en orden cronológico.

## Lo que hace MemorIA

`app/servicios/calidad/soportes/organizacion.py` (determinista):

- Por acción: si falta «Producto final» o «Soportes de producto final» o si
  está vacía, si la acción entera está vacía, si el producto final trae más de
  un archivo o no es PDF, si hay archivos dentro de subcarpetas de esas dos
  carpetas y si hay archivos sueltos en la carpeta de la acción.
- Por archivo de soportes: cada regla de nombre, consecutivos repetidos, fechas
  fuera de orden y archivos idénticos (mismo contenido) dentro de la acción.
- Un nombre sugerido: consecutivo según la fecha, la descripción sin tildes ni
  signos (cortada en la última palabra que cabe) y la fecha del nombre o de los
  metadatos. Si no hay fecha, queda `AAAAMMDD` para completarla.

### Carpetas descargadas de Drive

Las carpetas «Soportes de acciones» de los programas se bajan de Drive como
zip. MemorIA las reconoce con estas variantes:

- Nombres de acción con punto o espacio al final («Acción 6.1.», «Acción 2.1 »),
  en mayúsculas, sin tilde o con guion o guion bajo («Accion_3.1»).
- «Producto final» y «Soportes de producto final» en mayúsculas, con espacios
  o en plural («Productos finales»).
- Carpetas vacías: Drive las incluye en el zip y MemorIA las crea al
  descomprimir, así una acción sin archivos aparece con su observación en vez
  de desaparecer.
- Documentos, hojas y presentaciones de Google: llegan exportados a docx, xlsx
  y pptx, sin propiedades de documento. La fecha de creación queda vacía (en
  amarillo en el índice), no la del día de la descarga. Las presentaciones
  cuentan una página por diapositiva.
- Descargas grandes: Drive las divide en partes («…-1-001.zip», «…-2-001.zip»).
  La web recibe un solo zip; para revisar varias partes juntas está
  `scripts/organizacion_local.py`, que corre la misma revisión en el equipo,
  sin modelo y sin subir nada:

```
uv run python scripts/organizacion_local.py --salida ~/Downloads/resultados \
    "Soportes de acciones-…-1-001.zip" "Soportes de acciones-…-2-001.zip"
```

El resultado es `organizacion_evidencias.xlsx`, con las hojas «Acciones»,
«Archivos» y «Léeme». Se descarga en la web desde la página del revisor de
soportes, junto al costo estimado. Generarlo no gasta créditos.

MemorIA no renombra ni mueve archivos: señala y sugiere, y quien carga los
soportes decide. Tampoco revisa la firma del producto final ni si la
descripción es clara; eso queda para la persona.

## Índice electrónico del expediente

Con la misma carga sale `indice_electronico.xlsx`, en el formato de la
Vicedecanatura (`00IndiceElectronicoPlanesMejoraFCEN.xlsx`). El formato está en
`app/core/indice_electronico.py` y lo comparte el archivo oficial de actas en
Drive (`docs/respaldo-drive.md`). Tiene el
encabezado del fondo, la serie PLANES, la subserie PLANES DE MEJORAMIENTO DE
PROGRAMAS CURRICULARES y el expediente físico NO.

Cada documento ocupa una fila, ordenada por acción y carpeta. Las columnas se
llenan así:

- **Nombre:** sin la extensión.
- **Fecha de creación:** de los metadatos.
- **Orden:** el consecutivo dentro del índice.
- **Páginas:** contadas en PDF, imágenes y presentaciones (pptx).
- **Página inicio y página fin:** con las mismas fórmulas del formato.
- **Formato:** pdf, excel, word, powerpoint o imagen (también para xls, doc o ppt).
- **Tamaño:** en kb.
- **Origen:** Electrónico.
- **Observaciones:** acción y carpeta.

Queda en amarillo lo que llena la oficina productora:

- la identificación del expediente;
- la fecha de incorporación;
- las páginas de los Word y los Excel;
- la fecha de cierre y la firma.
