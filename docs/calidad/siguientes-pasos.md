# Calidad: siguientes pasos (propuesta, sin implementar)

El cronograma 2026 de la oficina de calidad describe el trabajo de cada corte: revisar soportes, describir el avance de cada acción, controlar reprogramaciones, llevar el cierre al Comité Asesor y luego al Consejo de Facultad, y cargar todo en el sistema de autoevaluación. Hoy el bot lee el plan y muestra el estado. Estos son los tres pasos que seguirían, en orden.

En los tres rige la misma regla: el modelo extrae y redacta, nunca decide. Ningún % de avance, estado ni texto entra al plan sin que una persona lo apruebe con un botón, y todo queda con quién lo aprobó y cuándo.

## 1. Revisión asistida de soportes contra el indicador

**Entrada.** La acción con su indicador de cumplimiento («Dos correos enviados al semestre», «Acta del Comité Asesor con…») y los soportes del corte: los registrados con `/evidencia` y los enlaces del plan.

**Qué haría el bot.**
- Una lista de chequeo determinista sale del indicador: cada elemento verificable («dos correos», «un acta», «lista de asistencia») es una casilla.
- El modelo lee cada soporte (PDF, imagen o documento) y propone, por casilla: qué soporte la cubre, la cita textual que lo muestra (fecha, número de asistentes, número de acta) y qué falta.
- Las reglas fijas marcan lo que no necesita modelo: soporte con fecha fuera del periodo del corte, enlace vacío o sin permiso, archivo repetido en otra acción.

**Qué decide la persona.** Por cada casilla: «cubierta», «no cubierta» o «pedir otro soporte». El bot no cambia el % de avance; muestra el % que resultaría de las casillas cubiertas y la persona lo confirma o lo corrige.

**Pendientes.** Acceso de lectura al Drive de cada programa (hoy los enlaces apuntan a carpetas con permisos variados) y un formato acordado para los indicadores que no son medibles tal como están escritos.

## 2. Borrador de la descripción del avance por corte

**Entrada.** La descripción del corte anterior (historial de `cal_cortes`), las casillas revisadas en el paso 1, las tareas del cronograma del año y sus reprogramaciones.

**Qué haría el bot.**
- Un borrador por acción, con el estilo de las descripciones existentes: qué se hizo, con qué soporte y qué queda pendiente. Cada afirmación cita su soporte; si no hay soporte, el borrador lo dice («No se evidencia cumplimiento de…») en vez de suponerlo.
- Señala las diferencias con el corte anterior: % que sube sin soporte nuevo, tareas que pasan de reprogramadas a cumplidas, acciones marcadas «NO FUNCIONÓ» sin propuesta de reemplazo.

**Qué decide la persona.** Edita y aprueba cada descripción. Al aprobar, el bot genera la columna del nuevo corte («DESCRIPCIÓN DE AVANCE ACTUAL (fecha)») en una copia del plan para cargarla al Drive o al sistema de autoevaluación; no escribe sobre el archivo original.

## 3. Cierre del plan

**Entrada.** El plan con todos sus cortes, la hoja «4. Evaluación» (avance declarado frente al real) y las acciones vencidas, reprogramadas y «NO FUNCIONÓ».

**Qué haría el bot.**
- Un informe de cierre por objetivo: meta, línea base, avance final por acción con su soporte, diferencias entre el % declarado y el real, y la lista de acciones que no se cumplieron, con su historial de reprogramaciones.
- El borrador del oficio para el Comité Asesor, que **recomienda** aprobar o no aprobar el cierre; quien decide es el Consejo de Facultad. El texto usa los verbos de la regla del 28-oct: el comité nunca aprueba, solo recomienda.
- Una lista de lo que hay que cargar en el sistema de autoevaluación, con el soporte de cada elemento.

**Qué decide la persona.** El Comité Asesor revisa el informe y emite su recomendación; el Consejo de Facultad decide. El bot registra ambas decisiones con fecha y acta, pero no las toma ni las envía.

## Orden sugerido
1. Revisión asistida de soportes: es lo que más tiempo toma hoy y prepara los otros dos pasos.
2. Borrador por corte: el próximo corte estimado de varios programas cae entre noviembre y diciembre de 2026.
3. Cierre: cuando un plan llegue a su fecha final (los planes reales vigentes terminan entre 2027 y 2028).
