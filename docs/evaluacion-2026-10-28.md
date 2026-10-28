# Evaluación contra casos reales — 2026-10-28

Segunda corrida de `scripts/evaluar.py` sobre los 32 casos reales (fuera del
repositorio), con todos los cambios hechos desde la primera corrida.
Modelo de extracción: `claude-sonnet-5-5`. Sin errores de ejecución.

Costo: 220 494 tokens de entrada y 45 647 de salida, unos **0,90 USD**
(0,028 por caso). La primera corrida costó 0,87 USD.

## Aciertos por campo

| Campo | 1ª corrida | 2ª corrida | Cambio |
|---|---|---|---|
| nombre | 32/32 | 32/32 | = |
| documento | 25/32 | 32/32 | +7 (corrección del set) |
| trato | 32/32 | 32/32 | = |
| fecha | 31/32 | 32/32 | +1 |
| programa | 27/27 | 27/27 | = |
| tipos | 24/32 | 30/32 | +6 |
| inscritos | 26/27 | 27/27 | +1 |
| tras_solic | 2/3 | 3/3 | +1 |
| disciplin | 12/12 | 12/12 | = |
| papa | 3/3 | 3/3 | = |
| avance | 3/3 | 3/3 | = |
| codigos | 6/6 | 6/6 | = |
| cuerpo | 32/32 | 30/32 | **−2 (regresión)** |
| tabla_sia | 27/27 | 27/27 | = |
| privacidad | 0/1 | 1/1 | +1 |

Fallos marcados: 19 → 4. Fallos reales del modelo: 12 → 4.

## Seguimiento de los 12 fallos reales de la primera corrida

| Fallo | Casos | Estado |
|---|---|---|
| Carga mínima en trabajo de grado con menos de 10 créditos | 7 | 6 resueltos, **1 persiste** |
| Doble conteo de créditos inscritos (inscritos y tras la solicitud) | 2 | resuelto |
| Práctica profesional clasificada como PAE | 1 | parcial: ya no sale PAE, pero **tampoco sale trabajo de grado** |
| Detalle de salud copiado en los anexos | 1 | resuelto |
| Fecha sin año | 1 | resuelto |

## Fallos del modelo frente a errores del set

**Errores del set.** Los 7 fallos de `documento` de la primera corrida venían
del `esperado.json`, no del modelo. Ya se corrigieron y ahora salen bien. En
esta corrida no apareció ningún error nuevo del set.

**Fallos del modelo (4):**

1. *tipos — carga mínima (1 caso, persiste).* Trabajo de grado con 9 créditos
   inscritos: el modelo marca `trabajo_grado` pero no `carga_minima`.
2. *tipos — práctica profesional (1 caso, persiste en parte).* El modelo
   quitó `pae`, pero ahora no marca `trabajo_grado`. Solo devuelve
   `excepcion_norma`.
3. *cuerpo — encabezados de Gmail (2 casos, nuevo).* El rango del cuerpo
   empieza en la línea 1 e incluye la línea «para mí» del encabezado. Los
   `correo.txt` no cambiaron desde la primera corrida, así que es una
   regresión del modelo o del prompt, no del set.

## Arreglos propuestos (implementados después; ver abajo)

- **Carga mínima:** que sea una regla determinista en `reglas.py`. Si los
  tipos incluyen `trabajo_grado` y hay menos de 10 créditos inscritos, se
  agrega `carga_minima`. Así no depende del modelo. *(Al revisarlo, la causa
  era otra: ver la tercera corrida.)*
- **Práctica profesional:** decir explícitamente en el prompt de extracción
  que la práctica profesional es una modalidad de trabajo de grado (tipo
  `trabajo_grado`, nunca `pae`). Añadir un caso de prueba unitario.
- **Cuerpo con encabezados:** en `cuerpo_del_correo`, después de aplicar el
  rango del modelo, recortar desde la última línea de encabezado de Gmail
  («para mí», «Para:», remitente con fecha). Es el mismo criterio que ya usa
  la evaluación y no depende del modelo.

Muestra pequeña en `tras_solic`, `papa`, `avance` y `privacidad` (1–3 casos):
esos aciertos al 100 % no prueban mucho.

## Tercera corrida, con los arreglos

Arreglos aplicados:

- **Carga mínima:** la regla determinista ya existía. El fallo venía de un
  doble conteo: el Trabajo de Grado se pedía sin código y el SIA ya lo
  mostraba inscrito, así que se sumaba otra vez (9 → 15 créditos).
  `creditos_tras_solicitud` ya no lo vuelve a sumar.
- **Práctica profesional:** el prompt pide incluir `trabajo_grado` aunque el
  trámite principal sea otro.
- **Cuerpo:** `cuerpo_del_correo` empieza después de la última línea de
  encabezado de Gmail que haya dentro del rango del modelo.

Resultado: **32/32 casos sin fallos** en todos los campos (nombre, documento,
trato, fecha y tipos 32/32; programa, inscritos y tabla_sia 27/27; disciplin
12/12; codigos 6/6; tras_solic, papa y avance 3/3; privacidad 1/1).
Un caso dio error de conexión con la API y se volvió a correr solo.

Costo: unos 0,90 USD (0,87 de la corrida completa y 0,03 de repetir el caso).
Las reevaluaciones previas de los 4 casos afectados costaron 0,13 USD.

## Cuarta corrida, sobre `main` con los arreglos

Las tres corridas anteriores se hicieron con una copia local del commit
`d4972d3`. `main` tiene tres commits posteriores (formatos de solicitud en PDF
o Word, acta del comité y formato único de oficio y acta). Los arreglos se
aplicaron sobre `main` sin conflictos, los tests pasan (61, 1 omitido) y se
volvieron a evaluar los 32 casos.

Resultado: **32/32 casos sin fallos** en todos los campos, sin errores de
ejecución. Costo: 0,93 USD (234 638 tokens de entrada y 45 817 de salida).
