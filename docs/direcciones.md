# Direcciones y programas

Cada administrativa (y cada integrante de comité) está autorizada con una
dirección (`web_usuarios.direccion` en la web, `usuarios.direccion` en el bot).
Solo ve los casos, borradores, firmas, actas del Consejo e indicadores de esa
dirección, y el selector de programa le muestra solo los programas de esa
dirección. La lista está en `app/core/programas.py`.

| Clave | Dirección | Programas |
|---|---|---|
| `ciencias_naturales` | Área Curricular de Ciencias Naturales | Ingeniería Física, Ingeniería Biológica, Maestría en Ciencias - Física (`mcf`) |
| `matematicas` | Área Curricular de Matemáticas y Estadística | Matemáticas, Estadística, Ciencias de la Computación |
| `posgrados_matematicas` | Área Curricular de Posgrados de Ciencias Exactas | Especialización en Actuaría y Finanzas (`esp_actuaria`), Especialización en Estadística (`esp_estadistica`), MECEN (`mecen`), Maestría en Ciencias - Matemática Aplicada (`mcma`), Doctorado en Ciencias - Matemáticas (`dcm`) |

Si una dirección tiene un solo programa, el caso queda en ese programa sin
preguntar. El programa se reconoce por el código del plan o, si no se conoce,
por el nombre del plan; gana el alias más largo, para que «Doctorado en
Ciencias - Matemáticas» no se tome por el pregrado de Matemáticas.

## Comité único de posgrados

En pregrado cada programa tiene su comité, su acta y su consecutivo. El Área
Curricular de Posgrados de Ciencias Exactas tiene un solo comité para todos sus
programas: el **Comité Asesor de Posgrados del Área Curricular de Ciencias
Exactas**, que firma su director. Se declara en `app/core/programas.py` con
`comite_unico=True` en la dirección, junto con el nombre del comité, sus
integrantes y la última acta numerada por fuera de MemorIA (`ultima_acta`).

En esa dirección:

- Hay un solo borrador, un solo botón **Firmar** y una sola acta en curso con
  los casos de todos sus programas. Cada caso dice de qué programa es.
- El acta, la firma, el consecutivo y la imagen de firma usan la clave de la
  dirección, `posgrados_matematicas` (`COMITES` y `comite_de` en
  `programas.py`). `/firmar mecen` o `/firmar posgrados_matematicas` llevan al
  mismo comité.
- El acta lleva el encabezado del acta 029 («UNIVERSIDAD NACIONAL DE COLOMBIA /
  SEDE MANIZALES / COMITÉ ASESOR DE POSGRADOS DEL ÁREA CURRICULAR DE CIENCIAS
  EXACTAS / ACTA-030») y los asistentes como en ella: «Profesor NOMBRE, en
  calidad de cargo;».
- El consecutivo sigue a `ultima_acta` (029 de 2026): la siguiente que se
  propone es la 030, y no se puede cerrar un número igual o menor en ese año.
  Si la numeración real es otra, se corrige `ultima_acta` en `programas.py`.
- En Drive, las actas van a «Actas/<año>/Posgrados de Ciencias Exactas/Comité
  Asesor de Posgrados del Área Curricular de Ciencias Exactas»; los oficios de
  cada caso, a la carpeta de su programa.

## Paso de los posgrados a su dirección (noviembre de 2026)

Hasta noviembre de 2026, `mcma` y `mecen` colgaban de `matematicas`, y la
administrativa de pregrado veía los casos de posgrado. `app/db/reubicar.py`
pasa a `posgrados_matematicas`, sin duplicar nada si corre otra vez:

1. los casos de `matematicas` cuyo programa es de posgrado de matemáticas;
2. los casos de `matematicas` cuyo plan leído es de un posgrado de matemáticas
   (antes el doctorado quedaba como pregrado de Matemáticas);
3. los casos de `matematicas` que registró una persona que hoy está en
   `posgrados_matematicas`. Si tenían un programa de pregrado, quedan sin
   programa y la administrativa lo elige de nuevo;
4. las firmas de programas de posgrado de matemáticas.

Corre al iniciar la base (SQLite y Postgres) y cada vez que un admin guarda un
usuario en `/usuarios`.

### Lo que hace el admin en `/usuarios`

En la web de actas, `/usuarios`, cambiar el área de `posmate_man@unal.edu.co` a
**Área Curricular de Posgrados de Ciencias Exactas** y guardar. Al guardar, los casos que
esa cuenta registró pasan a la nueva dirección. No hace falta que vuelva a
ingresar: la dirección se lee de la base en cada petición.

Si alguna administrativa de posgrado usa el bot de Telegram, su dirección quedó
en `usuarios.direccion` cuando la eligió. Se cambia en la base (no hay comando).

## Pendientes

- Matemática Aplicada (`mcma`) y el Doctorado en Ciencias - Matemáticas (`dcm`)
  entran al comité único, pero sus coordinadores no aparecen entre los
  integrantes del acta 029. Falta confirmar que el comité los trata y quién
  los coordina.
- Maestría en Ciencias - Física (`mcf`): sigue en Ciencias Naturales. Falta
  confirmar si pertenece al Área Curricular de Posgrados de Ciencias Exactas.
  Si es así, basta con cambiar su `direccion` en `programas.py`.
- ¿El consecutivo del comité de posgrados vuelve a 001 cada año, como en
  pregrado? Hoy sí (la 029 solo cuenta para 2026).
- Correo, extensión y prefijo del radicado del comité de posgrados, y el código
  del plan de cada programa: no están en el repositorio.
- Las actas ya archivadas en Drive de `mcma` y `mecen` quedaron en la carpeta
  «Matemáticas y Estadística»; lo que se haya archivado con el nombre anterior
  de la dirección, en «Posgrados de Matemáticas». Lo nuevo va a «Posgrados de
  Ciencias Exactas».
