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

- Por acción: si falta «Producto final» o «Soportes de producto final», si el
  producto final trae más de un archivo o no es PDF, y si hay archivos sueltos
  en la carpeta de la acción.
- Por archivo de soportes: cada regla de nombre, consecutivos repetidos, fechas
  fuera de orden y archivos idénticos (mismo contenido) dentro de la acción.
- Un nombre sugerido: consecutivo según la fecha, la descripción sin tildes ni
  signos (cortada en la última palabra que cabe) y la fecha del nombre o de los
  metadatos. Si no hay fecha, queda `AAAAMMDD` para completarla.

El resultado es `organizacion_evidencias.xlsx`, con las hojas «Acciones»,
«Archivos» y «Léeme». Se descarga en la web desde la página del revisor de
soportes, junto al costo estimado. Generarlo no gasta créditos.

MemorIA no renombra ni mueve archivos: señala y sugiere, y quien carga los
soportes decide. Tampoco revisa la firma del producto final ni si la
descripción es clara; eso queda para la persona.

## Pendiente

- **Índice electrónico de gestión documental.** La Vicedecanatura compartió el
  índice electrónico para registrar la gestión documental de los planes de
  mejoramiento. Cuando tengamos el formato, el inventario puede llenarlo con
  nombre, fecha, páginas, formato y tamaño de cada evidencia. Las columnas no
  se adivinan: se toman del formato.
