# Diseño del agente de actas (v0.2, 14-oct-2026)

## Objetivo
Ahorrar tiempo a las dos administrativas de la FCEN que preparan los casos para los comités asesores. Hay una por cada dirección de área curricular: Ciencias Naturales (Ing. Física, Ing. Biológica) y Matemáticas y Estadística (Matemáticas, Ciencias de la Computación, Estadística). Ellas pegan en Telegram el correo del estudiante y los pantallazos del SIA. El agente arma el oficio y el acta con un formato membreteado único y, cuando ellas lo indican, los firma y los devuelve en .docx y PDF.

## Decisiones (13-oct-2026)
- Usuarios: solo las dos administrativas, una por dirección. Están facultadas para firmar en nombre de los directores. La lista blanca son sus Telegram user ID, y cada una queda asociada a su dirección.
- La historia académica llega siempre como pantallazos del SIA.
- Cada programa curricular tiene su propio comité asesor, así que hay un acta y un oficio por programa.
- El radicado Mz.FCEN.1.0xx-NNN-26 lo lleva cada dirección por orden de envío. El bot propone el siguiente número y la administrativa lo confirma al firmar, porque la dirección emite otros oficios por fuera del bot.
- Plantilla: se parte del oficio de Matemáticas (.docx). Unificar formatos es parte del encargo de Carlos.

## Principio
El modelo extrae, clasifica y redacta. Las reglas verifican. El comité decide. La firma la autoriza una persona.

## Flujo
1. **Caso.** Se pega el correo y luego los pantallazos, que se adjuntan al caso abierto. El modelo lo procesa una sola vez, al llegar (visión + salida estructurada), y el bot responde con una ficha: tipo de solicitud, estudiante, documento, programa (por el código del plan, p. ej. 4030 Ing. Física, 4034 CC), créditos por tipología, P.A.P.A., % de avance, semana del periodo, norma aplicable y alertas. Las correcciones se hacen respondiendo a la ficha.
2. **Verificación de pantallazos.** La tabla "Resumen de créditos" del SIA tiene filas y columnas fijas. Se comprueba que los totales coincidan con la suma de las filas para detectar errores de lectura, y se avisa si un pantallazo está cortado o no se lee.
3. **Borrador diario.** A una hora fija (o con `/acta`): un .docx y un PDF por programa con casos nuevos. Se arma con plantilla, sin tokens, y los pantallazos se insertan tal cual.
4. **Comité asesor.** Para cada caso: aprueba, no aprueba o modifica. El concepto de un profesor queda en el acta interna y no pasa al oficio.
5. **Firma.** `/firmar <programa>`: muestra un resumen, pide confirmación y el radicado, inserta la firma y registra quién firmó, cuándo y el hash del documento. Devuelve el .docx y el PDF finales.

## Firmantes por programa (confirmar)
En los ejemplos, el oficio de Ing. Física lo firma el Director de Área Curricular de Ciencias Naturales, y el de Ciencias de la Computación lo firma el Coordinador del programa. Hace falta una tabla de programa → nombre, cargo, correo e imagen de firma.

## Tokens
El documento se arma con plantilla, sin modelo. Lo que cuesta es leer cada solicitud (del orden de 10 mil tokens por caso), y cuesta lo mismo hoy o al final del día. Procesar al llegar permite detectar a tiempo lo que falta.

## Normativa (RAG)
- Corpus de 19 PDF (~35 mil palabras), indexado por artículo con metadatos de norma, tema, vigencia y "modificado por".
- Mapa fijo de tipo de solicitud → normas base, más recuperación por artículo para los casos poco comunes.
- Citas textuales verificadas contra la fuente.
- Para cada caso: la norma que aplica, las condiciones que exige y si se cumplen.
- Faltantes: Acuerdo 008 de 2008, Res. CFCEN-060-2008, Acuerdo 033 de 2007, normativa propia de Biología, Estadística, Matemáticas y CC, y el calendario 2026-2S.

## Google Drive
- Con @unal.edu.co sí se puede, pero el administrador del dominio (DNTIC) debe marcar como confiable el client ID de OAuth, o habilitar que los usuarios pidan acceso. Alcance mínimo: `drive.file` (no sensible).
- Una cuenta de servicio sola no sirve: no tiene cuota de almacenamiento.
- v1: .docx y PDF por Telegram; al subir el .docx a Drive se abre como Documento de Google. v2: Drive institucional cuando DNTIC apruebe.

## Plantilla unificada
El membrete y el encabezado del oficio de Matemáticas, con el bloque de caso de Física, que es el más completo: identificación + cita del correo, ANÁLISIS en viñetas, pantallazos, RECOMENDACIÓN, tabla de asignaturas (apertura / inscripción / cancelación) y la norma textual. Se usa la fuente Ancízar si está disponible.

## Datos personales
Lista blanca de usuarios, borrado de imágenes después de firmar más un plazo de retención, no enviar al modelo soportes que no se necesiten (historias clínicas, certificados: basta registrar que se anexaron), y consulta a la Facultad sobre la Ley 1581 y el proveedor del modelo.

## Evaluación
Con los casos reales (Acta 19 y Acta 20 de Física, Acta 35 de CC): se alimentan los correos y los pantallazos, y se compara contra las actas reales.

## Estado (14-oct-2026)
- Fase 1 en producción: Railway (`fcenbot-production.up.railway.app`), bot @fcenpregrado_bot, webhook con secreto, cron diario de GitHub Actions, PERIODO_INICIO = 2026-08-24.
- Primer caso real (inscripción extemporánea de Sociología de la lectura, CC): programa, fecha, semana, créditos, avance y P.A.P.A. correctos; DNI faltante detectado.
- Ajustes después de ese caso: no deducir créditos de las horas de la oferta, no contar los pantallazos del SIA como anexos, dudas solo sobre datos ilegibles o contradictorios.
- Problemas de puesta en marcha ya resueltos: la API key debe pertenecer a un workspace (o definir ANTHROPIC_WORKSPACE_ID); Sonnet 5.5 no acepta tool_choice forzado.
- Pendiente: el despliegue automático de Railway no siempre se dispara (se puede lanzar con ⌘K → Deploy Latest Commit).

## Próxima pasada: medir
1. Set de evaluación con los casos de las actas 19 y 20 de Física y la 35 de CC (entrada: correo y pantallazos; esperado: nombre, DNI, tipo, créditos, asignaturas, objeto), revisado a mano porque las actas tienen errores. Va en `casos_reales/`, fuera del repo.
2. `scripts/evaluar.py`: aciertos campo por campo; se corre en local con la API key.
3. Ajustar el prompt y las reglas con los casos difíciles de Física (excepciones a la Res. 060, PAE, correos largos).
4. Ficha corta, con el detalle detrás de un botón.
5. Comparar un oficio completo generado por el bot con el original del Acta 35.

## Fases
1. Intake + extracción + ficha + plantilla + borrador diario. **Construida el 13-oct-2026 en github.com/cmorregof/fcen_bot (rama main, 42 pruebas).** Falta evaluarla con los casos reales cuando haya API key.
2. Índice de normativa y alertas por reglas.
3. Revisión del comité, firma y radicado.
4. Google Drive institucional.

## Pendiente de Carlos
- Confirmar que el token del bot se regeneró con /revoke.
- Visto bueno de la Facultad sobre el tratamiento de datos antes del uso diario.
- Tabla de firmantes por programa y las imágenes de firma (para la fase 3).
- La normativa faltante.
