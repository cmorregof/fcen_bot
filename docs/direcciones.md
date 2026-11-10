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
| `posgrados_matematicas` | Dirección de Posgrados de Matemáticas | Especialización en Actuaría (`esp_actuaria`), Especialización en Estadística (`esp_estadistica`), MECEN (`mecen`), Maestría en Ciencias - Matemática Aplicada (`mcma`), Doctorado en Ciencias - Matemáticas (`dcm`) |

Si una dirección tiene un solo programa, el caso queda en ese programa sin
preguntar. El programa se reconoce por el código del plan o, si no se conoce,
por el nombre del plan; gana el alias más largo, para que «Doctorado en
Ciencias - Matemáticas» no se tome por el pregrado de Matemáticas.

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
**Dirección de Posgrados de Matemáticas** y guardar. Al guardar, los casos que
esa cuenta registró pasan a la nueva dirección. No hace falta que vuelva a
ingresar: la dirección se lee de la base en cada petición.

Si alguna administrativa de posgrado usa el bot de Telegram, su dirección quedó
en `usuarios.direccion` cuando la eligió. Se cambia en la base (no hay comando).

## Pendientes

- Confirmar el nombre oficial de la dirección («Dirección de Posgrados de
  Matemáticas» es provisional).
- Especialización en Actuaría, Especialización en Estadística y Doctorado en
  Ciencias - Matemáticas: código del plan, correo, extensión, prefijo del
  radicado e integrantes del comité. No están en el repositorio.
- MCMA y MECEN: los mismos datos, que tampoco están.
- Maestría en Ciencias - Física (`mcf`): sigue en Ciencias Naturales. El
  repositorio no dice si hay una dirección de posgrados de Física aparte
  (existe el buzón `posfisica_man`). Si la hay, se crea igual que esta.
- Las actas ya archivadas en Drive de `mcma` y `mecen` quedaron en la carpeta
  «Matemáticas y Estadística»; las nuevas van a «Posgrados de Matemáticas».
