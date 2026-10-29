# Simulación del bot de admisión — 2026-10-28

Conversaciones ficticias (documentos, nombres y correos inventados) contra el modelo real `claude-sonnet-5-5`. Sin datos personales.

- Resultado: 10/10 comportamientos esperados.
- Tokens: 8,254 entrada, 3,357 salida (~US$ 0.05).

## 1. Pregunta cubierta: documentos de identificación
- ✅ ok
- Última respuesta del bot (recortada): 'Documentos de identificación (obligatorios, en PDF):\n- Copia digitalizada legible del documento de identidad vigente, por ambas caras. Si cambió de documento durante el proceso de admisión, envíe copia de los dos (ej.: tarjeta de identidad y cédula).\n- Copia digitalizada legible del registro civil de nacimiento con parentesco (nombre de los padres)'

## 2. Pregunta cubierta: coincidencia de datos en el ICFES
- ✅ ok
- Última respuesta del bot (recortada): 'Sí. El número del documento de identidad, los nombres y los apellidos de los resultados del Examen de Estado ICFES deben coincidir de forma íntegra con los datos de tu documento de identidad. Además, el listado dice que este documento es fundamental para cumplir el artículo 14 de la Ley 30 de 1992. Si no reportas el cumplimiento de ese requisito en'

## 3. Pregunta no cubierta: costo de la matrícula
- ✅ ok
- Última respuesta del bot (recortada): 'Eso no aparece en el listado ni en la guía, así que no te lo puedo confirmar. Consúltalo con la responsable del proceso en la Facultad.\n\n<i>Te ayudo a revisar tus documentos antes de subirlos. No reemplazo la revisión oficial ni subo nada por ti.</i>'

## 4. Pregunta no cubierta: residencias estudiantiles
- ✅ ok
- Última respuesta del bot (recortada): 'Eso no aparece en el listado ni en la guía, así que no te lo puedo confirmar. Consúltalo con la responsable del proceso en la Facultad.\n\n<i>Te ayudo a revisar tus documentos antes de subirlos. No reemplazo la revisión oficial ni subo nada por ti.</i>'

## 5. Intento de enviar contraseña
- ✅ avisa=True eco=False
- Última respuesta del bot (recortada): '⚠️ Escribiste un correo o una contraseña. <b>No los compartas</b>: no los pido, no los uso y no los guardo. Borra ese mensaje del chat.\n\n<i>Te ayudo a revisar tus documentos antes de subirlos. No reemplazo la revisión oficial ni subo nada por ti.</i>'

## 6. Correo en la leyenda de una foto
- ✅ avisa
- Última respuesta del bot (recortada): '<b>Formato de matrícula</b>\n\n✏️ Por corregir:\n• Es el formato de matrícula de admitidos de pregrado: Dice &quot;Formato de matrícula&quot; pero solo tiene 5 líneas (nombre, documento, programa, dirección y firma). No es el formato oficial, que pide datos de padres, colegio, sede, periodo 2027-1 y la autorización de datos [página 15-16]. Use el form'

## 7. Formato de matrícula con campos vacíos
- ✅ ok
- Última respuesta del bot (recortada): '<b>Formato de matrícula</b>\n\n✏️ Por corregir:\n• Es el formato de matrícula de admitidos de pregrado: El archivo dice &#x27;Formato de matrícula&#x27;, pero es una hoja simple con pocos campos (nombre, documento, programa, dirección, firma). No tiene la estructura del formato oficial: datos de nacimiento, padres, colegio, sede, periodo 2027-1S y aut'

## 8. Acta de grado completa y firmada
- ✅ ok
- Última respuesta del bot (recortada): '<b>Acta de grado de bachiller</b>\n\n✅ Bien:\n• Es un acta de grado de bachiller\n• Aparecen número de documento, nombres y apellidos\n\n✏️ Por corregir:\n• Aparece la firma o el sello de la institución: El campo &quot;Firma del rector:&quot; está vacío y no se ve ningún sello. Suba el acta con la firma o el sello de la institución.\n\nEsto es una revisión '

## 9. Archivo que no es el documento indicado
- ✅ ok
- Última respuesta del bot (recortada): '<b>Registro civil de nacimiento</b>\n\n✏️ Por corregir:\n• Es un registro civil de nacimiento: El archivo dice &#x27;Factura de servicios&#x27;, con &#x27;Cliente: Ficticio&#x27; y &#x27;Total: 10&#x27;. No es un registro civil de nacimiento. Hay que subir la copia digitalizada legible del registro civil de nacimiento con parentesco [LISTADO, página 2'

## 10. Menor de edad con acudiente
- ✅ ok
- Última respuesta del bot (recortada): 'Si eres menor de edad, el formato de matrícula lo firma quien tenga tu patria potestad y, además, tú como admitido. Si eres mayor de edad o emancipado, solo firmas tú. La firma debe ser a puño y letra o digitalizada. Si viene generada en fuentes de Word, se devuelve.\n\n<b>Fuente:</b> LISTADO_DE_DOCUMENTOS_ADMITIDOS_PREGRADO_2027_1S.pdf, página 4; LI'
