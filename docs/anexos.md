# Anexos del estudiante

Cada caso tiene dos zonas de adjuntos, en la ficha (pestaña **Anexos**) y en el paso 1 del
asistente para crear un caso (`/actas/nuevo`):

| Zona | Qué va | Qué hace MemorIA |
|---|---|---|
| **Pantallazos del SIA** | Solo imágenes (JPG, PNG, WEBP) de la historia académica. | Las lee la extracción del caso (`DatosSIA`), como antes. |
| **Otros anexos del estudiante** | PDF, Word o imágenes: certificados, cartas, formatos, soportes médicos, constancias. | Resume cada uno y el resumen va al análisis del acta. |

En «Otros anexos», un PDF o Word cuyo título es «FORMATO DE …» sigue entrando como formato
de solicitud (su texto se agrega al caso). Un PDF escaneado ya no pregunta si es el formato:
es un anexo y se resume. En Telegram no hay zonas: el tipo se decide como antes
(`app/services/adjuntos.py`).

## El resumen

`app/services/anexos.py` lee cada anexo con el modelo y guarda en la fila del adjunto
(`caso_archivos.resumen`):

- tipo de documento, fecha, emisor y lo que acredita;
- hasta 5 datos relevantes para la solicitud;
- hasta 2 citas literales del documento.

Reglas:

- **Solo extrae.** No dice si el soporte es suficiente ni recomienda nada.
- **No inventa.** Lo que no lee queda como «[verificar en el anexo]», que en el acta sale en
  amarillo, igual que «[verificar en el SIA]».
- **Citas literales.** Si el anexo tiene texto (Word o PDF con texto), cada cita se comprueba
  contra ese texto; la que no aparece tal cual lleva «[verificar en el anexo]». En imágenes y
  PDF escaneados no hay con qué comprobarla, así que siempre la lleva.

En el acta (y el oficio), dentro de **ANÁLISIS**, sale una viñeta por anexo:

> • Se adjunta certificado médico de Clínica Ficticia del Café del 3 de septiembre de 2026 que
> acredita incapacidad médica entre el 1 y el 7 de septiembre de 2026. Siete días de
> incapacidad. Cita del anexo: “presenta incapacidad médica por siete (7) días”.

La ficha muestra el resumen, las citas y «Así va en el acta».

## Cuándo se lee

- Al **leer el caso** (paso 1 del asistente, «Procesar» o el bot): primero los anexos sin
  resumen, luego la extracción. Si un anexo falla, el caso se lee igual y se avisa.
- Al **agregar** un anexo a un caso ya creado: se resume enseguida.
- Con **«Leer con MemorIA» / «Leer de nuevo»** en la ficha
  (`POST /api/web/actas/casos/{id}/archivos/{archivo}/leer`, solo la administrativa).

Cada anexo se paga una sola vez: «Volver a leer el caso» no repite los anexos ya resumidos.

## Qué se le envía al modelo

| Archivo | Envío |
|---|---|
| Word | Su texto (lo extrae `app/services/formatos.py`, sin el modelo). |
| PDF con texto | Su texto (`pdftotext`). |
| PDF escaneado | El PDF como documento; si pasa de `ANEXOS_MAX_PAGINAS`, solo esas primeras páginas. |
| Imagen | La imagen reducida, como los pantallazos. |

El texto se corta en `ANEXOS_MAX_CARACTERES`; si se corta, la viñeta dice «Solo se leyó la
primera parte del archivo». También va, como contexto, el inicio del correo del estudiante
(2.000 caracteres).

## Configuración

| Variable | Por defecto | Para qué |
|---|---|---|
| `ANEXOS_MODELO` | `claude-sonnet-5-5` | Modelo que resume. |
| `ANEXOS_ESFUERZO` | `medium` | Esfuerzo (`output_config.effort`: `low`, `medium`, `high`…). |
| `ANEXOS_MAX_TOKENS` | `8000` | Tope de salida (incluye el razonamiento). |
| `ANEXOS_MAX_CARACTERES` | `30000` | Tope del texto de un Word o PDF. |
| `ANEXOS_MAX_PAGINAS` | `10` | Tope de páginas de un PDF escaneado. |

Usa la misma `ANTHROPIC_API_KEY`. Cada lectura queda en `uso_modelo` con la operación
`anexo`, así que entra en `/costo`.

## Costo estimado por anexo

Con Claude Sonnet 5.5 (USD 2 por millón de tokens de entrada y 10 de salida), esfuerzo medio:

| Anexo | Entrada | Salida | Costo aproximado |
|---|---|---|---|
| Word o PDF de 1–2 páginas | 2.500–4.000 | 800–2.000 | USD 0,01–0,03 |
| Foto o pantallazo | 2.500–5.000 | 800–2.000 | USD 0,01–0,03 |
| PDF escaneado de 10 páginas (el tope) | 20.000–35.000 | 1.000–2.500 | USD 0,05–0,10 |

Son estimaciones; el costo real se ve en `uso_modelo` (operación `anexo`).

## Borrar

Si la administrativa borra un anexo (PR #46), se borra la fila con su resumen: sale de la
ficha y del próximo borrador del acta. El aviso lo dice: «Su resumen también se quitó del
caso y del acta».
