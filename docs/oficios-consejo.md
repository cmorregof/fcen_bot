# Borrador del oficio de notificación del Consejo de Facultad

Cuando el Consejo de Facultad decide un caso, la Secretaría de Facultad le
notifica la decisión al estudiante con un oficio (`Mz.FCEN.1.004-NNN-AAAA`) o,
para el reingreso aprobado, con una resolución (`Res.CFCEN-NNN-AAAA`). MemorIA
arma el **borrador** en Word a partir del caso y de la decisión del Consejo ya
registrada (pantalla «Acta del Consejo»). La Secretaría lo revisa, completa lo
que está en amarillo, le pone número y lo firma.

El formato sale de los oficios que compartió la Secretaría. Los ejemplos no
están en el repositorio (tienen datos de estudiantes).

## Cuándo se puede bajar

Solo si el caso tiene una decisión del Consejo **confirmada por una persona** y:

- la decisión es del **Consejo de Facultad** (no de Sede ni del Superior), y
- el sentido es **aprobó** o **no aprobó** (un aplazamiento u otra decisión no
  se notifica todavía).

En la web, en la ficha del caso, bajo «Decisión del Consejo», aparece el botón
**«Borrador del oficio del Consejo (Word)»**. Lo pueden bajar las mismas
personas que pueden ver el caso (administrativa y comité de su área).

Endpoint: `GET /api/web/actas/casos/{id}/oficio-consejo` (409 si no aplica).
Servicio: `app/services/oficio_consejo.py`, función pura
`construir_oficio_consejo(caso, decision=None, *, fecha=None, periodo=None, elaboro="")`.
No usa el modelo.

## Estructura del oficio

1. `Manizales, <fecha>` y el radicado `Mz.FCEN.1.004-___-AAAA` (número en
   amarillo). La fecha es la de la sesión del Consejo, como en los ejemplos.
2. Estudiante: `NOMBRE con DNI …`, `Programa Curricular de …`, Facultad,
   Universidad, Sede.
3. `Asunto:` según el trámite (tabla abajo).
4. `Reciba un cordial saludo.`
5. Párrafo de decisión: «El Consejo de la Facultad de Ciencias Exactas y
   Naturales en sesión [presencial / no presencial] del <fecha del acta>, Acta
   <n>, APRUEBA | NO APRUEBA la solicitud de … en el periodo Académico …,
   realizada a través de correo electrónico el dd/mm/aaaa.»
6. Debajo, en amarillo y para borrar antes de firmar, el texto de la decisión y
   el fragmento del acta **literales**, para tomar de ahí la motivación.
7. Notificación (texto fijo, Resolución 1194 de 2013 de Rectoría).
8. Recursos (texto fijo: reposición ante el Consejo de Facultad y apelación ante
   el Consejo de Sede, artículo 77 de la Ley 1437 de 2011, diez días).
9. `Sin otro particular,` y la firma.
10. `Copia: Comité Asesor Programa Curricular <programa>` y, si la decisión
    afecta la historia académica, `Oficina de Registro y Matrícula`.

Los textos fijos están en `NOTIFICACION` y `RECURSOS` y las pruebas verifican
que no cambien.

## Trámites

| Trámite (tipo) | Asunto | Registro y Matrícula | Cuadro (si aprobó) |
|---|---|---|---|
| Cancelación de asignaturas | Cancelación Asignatura sin pérdida de créditos AAAA-nS. | sí | — (asignaturas en el párrafo: `NOMBRE (código)`) |
| Cancelación del periodo | Cancelación Periodo Académico AAAA-nS. | sí | — |
| Carga mínima | Cursar menos de la carga mínima AAAA-nS. | no | — |
| Inscripción extemporánea | Inscripción Extemporánea de asignatura. | sí | — (asignaturas en el párrafo) |
| Traslado | Respuesta a solicitud de Traslado AAAA-nS. | sí | cuadro de equivalencias |
| Permiso académico | Permiso Académico. | no | — |
| Homologación / convalidación / equivalencia | Equivalencia de asignatura. · Convalidación asignatura. · Homologación de asignatura. | sí | cuadro (el mismo del oficio del comité) |
| Designación de jurados | Designación de Jurados – Trabajo de Grado. (posgrado: – Tesis o Trabajo Final.) | sí | jurados |
| Proyecto de tesis | Inscripción de proyecto de tesis o trabajo final. | sí | datos del proyecto |
| Reexpedición de recibo | Reexpedición de recibo de pago AAAA-nS. | sí | — (+ párrafo del desbloqueo en amarillo, si aplica) |
| Reingreso no aprobado | Respuesta a solicitud de Reingreso AAAA-nS. | sí | — |
| Reingreso aprobado | **Resolución** (ver abajo) | en la copia | — |
| Otros | El título del trámite, en amarillo | en amarillo | — |

Si un caso trae varios trámites cubiertos, el asunto y el párrafo los unen
(«… y …») y el periodo va una sola vez al final. Si además trae uno no cubierto,
sale una nota en amarillo para que la Secretaría redacte esa parte. Un caso
cuyo trámite no está cubierto sale como oficio genérico con todo el párrafo de
decisión en amarillo.

Los cuadros (equivalencias, jurados, proyecto) solo salen si el Consejo aprobó.

## Resolución de reingreso

Estructura: `RESOLUCIÓN [Res.CFCEN-___-AAAA]` / `(DD DE MES, ACTA n)` /
«Por la cual se autoriza un Reingreso al programa curricular de …» / EL CONSEJO
DE LA FACULTAD… / atribuciones (Acuerdo 011 de 2005 del CSU) / CONSIDERANDO
(cinco QUE) / RESUELVE (artículos 1 a 3 y parágrafo) / NOTIFÍQUESE Y CÚMPLASE /
«Dada en Manizales, a …» / firmas Presidente(a) y Secretario(a) / copia a
Decanatura, Biblioteca, Registro y Matrícula y el programa.

Los tres considerandos normativos están copiados literalmente del modelo de la
Secretaría (`CONSIDERANDOS_REINGRESO`) y salen **en amarillo** para verificarlos
contra la norma: el primero habla de «estudiantes de posgrado» aunque el modelo
era de pregrado.

## Lo que sale en amarillo

MemorIA no inventa lo que no sabe. Sale resaltado:

- número del oficio o de la resolución;
- modalidad de la sesión (presencial / no presencial): el acta leída no la trae;
- motivación de una negación: `[motivación de la decisión según el acta]`;
- nombre, DNI, programa, código de asignatura, número o fecha del acta, fecha de
  la solicitud, si faltan;
- el periodo, cuando no aparece en el pantallazo del SIA (se usa
  `PERIODO_ACTUAL` para que lo revisen);
- el canal (correo electrónico / oficio) cuando la solicitud llegó como formato
  adjunto;
- la firma, si no está configurada;
- en la resolución: el periodo del reingreso, los datos de la sesión del comité,
  la declaración del estudiante sobre la normativa y los considerandos.

## Configuración

Variables de entorno (vacías por defecto; los nombres no van en el código):

| Variable | Uso |
|---|---|
| `SECRETARIA_FACULTAD_NOMBRE` | firma del oficio y de la resolución |
| `SECRETARIA_FACULTAD_CARGO` | por defecto «Secretario(a) de Facultad» |
| `SECRETARIA_FACULTAD_CORREO` | pie de página |
| `SECRETARIA_FACULTAD_EXTENSION` | pie de página |
| `PRESIDENTE_CONSEJO_NOMBRE` | firma de la resolución |
| `PRESIDENTE_CONSEJO_CARGO` | por defecto «Presidente(a)» |
