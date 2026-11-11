# Solicitudes y acta del Comité Asesor de Posgrados

Cómo arma MemorIA el acta del **Comité Asesor de Posgrados del Área Curricular
de Ciencias Exactas** (dirección `posgrados_matematicas`, `docs/direcciones.md`)
y qué tipos de solicitud reconoce en un correo de posgrado.

Sale de las actas 022, 024, 025, 026, 027, 028 y 029 de 2026 de ese comité,
que se leyeron fuera del repositorio. Aquí no hay datos de estudiantes: los
ejemplos y las pruebas (`tests/test_acta_posgrado.py`) son inventados. La 023
no estaba entre las actas de referencia.

## Inventario de solicitudes

«Reutiliza» quiere decir que el tipo ya existía en `TipoSolicitud`
(`app/schemas/caso.py`); «nuevo», que se agregó para posgrado. Todos están en
`config/solicitudes.yaml`; mientras la Vicedecanatura no confirme quién decide,
quedan `por_confirmar`.

| Solicitud en las actas | Tipo | Cómo se presenta en el acta | Norma que cita el acta |
|---|---|---|---|
| Cancelación de asignatura (curso) | `cancelacion` (reutiliza) | Estudiante, DNI y periodo; «Asignatura: nombre, código, tipología (L) de N créditos»; justificación del estudiante | Ninguna |
| Permiso académico (congresos, workshops) | `permiso_academico` (reutiliza) | Estudiante, programa y director; por evento: nombre, fechas de participación, fechas del evento y lugar; justificación; aval del director y documento adjunto | Ninguna |
| Reingreso (también extemporáneo) | `reingreso` (reutiliza); el extemporáneo, con `excepcion_norma` | «El exestudiante …, solicita reingreso al programa …, para el período académico …»; número de radicado del portal; documentos adjuntos | Ninguna |
| Reexpedición de recibos, desbloqueo de la historia y registro de asignaturas | `reexpedicion_recibo` (reutiliza), `desbloqueo_historia` (nuevo), `inscripcion_extemporanea` (reutiliza) | Contexto del caso y, por estudiante, los cursos con código y tipología | Ninguna |
| Sustentación de tesis de maestría | `sustentacion_tesis` (nuevo) | Fecha de la defensa, título, director y codirector, jurados evaluadores con su institución; se remite el acta de sustentación para registrar «Aprobado (Ap)» en la actividad con su código | Ninguna |
| Nota definitiva o evaluación del trabajo final de maestría | `calificacion_trabajo_final` (nuevo) | Cuadro: actividad (con código y periodo), título, director, evaluador; fechas de recepción y de entrega de la evaluación | Ninguna |
| Entrega de tesis o TFM y nombramiento de evaluadores | `nombramiento_evaluadores` (nuevo) | Título, estudiante, director, aval del director y los evaluadores puestos a consideración, con institución, correo y perfil | Ninguna |
| Entrega de la propuesta de TFM: aval del título y nombramiento del director | `proyecto_tesis` (reutiliza) | Por estudiante: título, director, objetivo general y objetivos específicos | Ninguna |
| Cambio de título (y objetivos) del TFM | `modificacion_proyecto` (nuevo) | Director, título anterior, título nuevo, nuevo objetivo general y nuevos objetivos específicos; aval del director | Ninguna |
| Tránsito entre programas de posgrado | `transito_posgrado` (nuevo) | Estudiantes, programa de origen, programa de destino y periodo; motivación; si el destino tiene otro comité, se remite a ese comité | Res. 035 de 2014 VRA (arts. 17, 18 y 21) y Res. 016 de 2025 VRA: **sin texto literal en el repositorio** |
| Homologación o convalidación del examen de calificación | `examen_calificacion` (nuevo) | Estudiante, actividad con código y tipología, matrícula en curso y la productividad que aporta | Acuerdo 033 de 2008 CSU, art. 17 (transcrito literal en `app/normativa/base.py`, `verificada=False`) |
| Exención de pago de derechos académicos | `exencion_pago` (nuevo) | Estudiante, programa y periodo | Ninguna |
| Cronograma y cupos de admisión, aplicación no masiva | `admision_no_masiva` (nuevo, asunto del programa) | Programas con cupos regulares y de admisión anticipada; cuadro Actividad / Fecha | Ninguna |
| Creación de asignatura (curso) | `creacion_curso` (nuevo, asunto del programa) | Lo presenta el coordinador: nombre, programa, nivel, tipo, área, créditos, horas, duración y tipología; se anexa el formato | Ninguna |
| Convenio y modificación de un acuerdo del plan de estudios | `propuesta_programa` (nuevo, asunto del programa) | Lo presenta el coordinador: la propuesta, el texto vigente y el propuesto y la justificación | El acuerdo que se modifica |

En las actas de referencia **no** aparecen prórrogas, movilidad, cambio de
director, reserva de cupo ni cancelación del periodo. Movilidad, reserva de
cupo y cancelación del periodo ya existían para pregrado y sirven igual. El
cambio de director va en `modificacion_proyecto` (`director_anterior`). La
prórroga no tiene tipo propio: va en `otro` hasta ver un caso.

### Asuntos del programa

Cronograma de admisión, creación de cursos, convenios y cambios del plan de
estudios no son de un estudiante: los presenta un coordinador o el director.
MemorIA los trata como un caso más (se pega el correo del coordinador), pero:

- el modelo registra quién lo presenta en `presenta` y deja vacíos el nombre y
  el documento del estudiante;
- las reglas no piden nombre, documento ni pantallazos del SIA, y avisan si
  falta quién lo presenta;
- el acta dice «<quién> presenta a consideración del Comité la solicitud de …»
  y transcribe el texto de la solicitud, sin ANÁLISIS.

## Datos nuevos de la extracción

En `ExtraccionCaso` (el modelo copia, nunca decide):

- `periodo_solicitado`: periodo para el que pide el trámite (2027-1S).
- `programa_destino`: solo en un tránsito.
- `radicado_portal`: número de la solicitud en el portal, si aparece.
- `eventos`: en un permiso académico, cada evento con nombre, fechas de
  participación, fechas del evento, lugar y en calidad de qué participa.
- `presenta`: en un asunto del programa, quién lo presenta.
- En `proyecto` (tesis o trabajo final): `titulo_anterior`,
  `director_anterior`, `objetivo_general`, `objetivos_especificos`,
  `actividad` (con su código), `fecha_sustentacion`, `fecha_entrega` y
  `calificacion` (la que emitieron los jurados, tal como aparece).
- Los jurados de una sustentación y los evaluadores de una tesis o un TFM van
  en `jurados`.

El prompt (`app/prompts/extraccion.py`, reglas 18 y 19) explica cuándo usar
cada tipo y pide escribir «cursos» en lugar de «asignaturas».

## Estructura del acta

`app/services/acta_posgrado.py`. Usa la misma plantilla y los mismos estilos
que el acta de pregrado; cambia el contenido:

1. **Encabezado**: UNIVERSIDAD NACIONAL DE COLOMBIA / SEDE MANIZALES / COMITÉ
   ASESOR DE POSGRADOS DEL ÁREA CURRICULAR DE CIENCIAS EXACTAS / ACTA-030, y
   FECHA, HORA y LUGAR.
2. **MIEMBROS DEL COMITÉ ASISTENTES**: «Profesor NOMBRE, en calidad de cargo;»,
   con los integrantes de `programas.py`. Sin INVITADOS.
3. **ORDEN DEL DÍA**: un punto por solicitud, «N) Solicitud de …: Nombre
   (Programa)». Las actas reales lo dejan vacío; MemorIA lo llena.
4. **DESARROLLO**: «El Comité …, en sesión realizada el …, según Acta 30 de
   2026, estudió las solicitudes que se relacionan a continuación, de acuerdo
   con su respectivo programa curricular.», la lista de programas y un punto
   por solicitud. Las solicitudes van por programa: doctorado, maestrías y
   especializaciones.
5. **Cada punto**: el título en mayúsculas con el programa y el periodo
   («1) SOLICITUD DE CANCELACIÓN DE CURSOS – DOCTORADO EN CIENCIAS -
   MATEMÁTICAS 2026-2S»); la presentación («NOMBRE, identificada con DNI No. …,
   estudiante del …, mediante correo del día …, solicita …»); los datos del
   trámite (cursos, programa de destino, eventos, tesis o trabajo final,
   jurados o evaluadores, cuadro de homologación); «Justificación emitida por
   el estudiante: “…”», literal; los anexos; el ANÁLISIS del SIA si hay
   pantallazos; los conceptos de los integrantes; la **RECOMENDACIÓN** y, si el
   tipo tiene norma, la norma literal.
6. **Cierre**: la firma del director. Sin «Varios» ni verificación del quórum.

La recomendación es «El Comité Asesor de Posgrados del Área Curricular de
Ciencias Exactas recomienda al Consejo de Facultad APROBAR | NO APROBAR la
solicitud de …». El sentido lo registra una persona; sin él queda «[APROBAR /
NO APROBAR]» en amarillo. ZAPC sigue la regla de siempre (`lleva_zapc`).

El oficio al Consejo conserva su formato; en posgrado, sus títulos dicen
«cursos».

### Reglas que cambian en posgrado

- **Carga mínima**: el art. 10 del Acuerdo 008 de 2008 es para pregrado. En un
  programa de posgrado, MemorIA no agrega «carga mínima» ni avisa por ella.
- **Mínimo de jurados**: el de Trabajo de Grado de pregrado no se aplica a los
  jurados de una sustentación ni a los evaluadores de una tesis o un TFM.
- **Avisos nuevos**: falta el título o el director en un trámite de tesis;
  faltan los jurados o los evaluadores; falta el programa de destino de un
  tránsito; un trámite de posgrado en un programa de pregrado.

## Por confirmar con las administrativas de posgrado

- **Quién decide y con qué acto** cada tipo nuevo (todos `por_confirmar` en
  `config/solicitudes.yaml`).
- **Fórmula de la recomendación.** Las actas usan varias («recomienda
  aprobar», «recomienda la solicitud», «se escala al Consejo de Facultad»,
  «continuar con el trámite ante las instancias competentes»). MemorIA usa una
  sola, con el sentido explícito y dirigida al Consejo de Facultad. ¿Sirve así?
- **«Sesión no presencial».** Las actas dicen «en sesión no presencial» aunque
  el LUGAR sea la Coordinación. MemorIA escribe «en sesión realizada el …».
- **Orden del día.** Las actas lo dejan vacío; ¿se deja la lista de puntos?
- **Normas del tránsito** (Res. 035 de 2014 y Res. 016 de 2025 de la
  Vicerrectoría Académica): hace falta el texto literal para citarlas.
- **Acuerdo 033 de 2008, art. 17**: cotejar con el PDF (se copió del acta
  029) y conseguir la reglamentación del examen de calificación de la
  Facultad.
- **Varios estudiantes en un punto.** Las actas agrupan a veces dos
  estudiantes con la misma solicitud (dos tránsitos, dos reexpediciones). En
  MemorIA cada estudiante es un caso y un punto.
- **Asuntos del programa.** ¿Se registran en MemorIA o se siguen escribiendo
  a mano en el acta?
- **Ficha del caso**: los datos nuevos (eventos, programa de destino,
  objetivos) salen en el acta; falta mostrarlos en la ficha web y del bot.
