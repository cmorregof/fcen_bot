# Borrador de la descripción de avance de un corte

Cada corte semestral, la oficina de Calidad escribe por acción la descripción del avance para el informe de autoevaluación. MemorIA arma un **borrador por acción** para que Calidad lo apruebe, lo edite o lo descarte. El modelo propone; no decide si una acción se cumplió, no cambia el % de avance y no escribe en el plan. Después, el Comité Asesor recomienda y el Consejo de Facultad decide.

Depende de la plantilla institucional (#14–#17) y del revisor de soportes de la web.

## Qué usa, por acción
| Fuente | ID | Origen |
|---|---|---|
| La acción y sus tareas del cronograma, con el % declarado | `[P1]`, `[P2]`… | Hoja y fila del plan, p. ej. «2. Plan de Mejora» fila 9 |
| Lo escrito en los dos cortes anteriores | `[C1]`, `[C2]` | Historial de `cal_cortes` |
| Enlaces de evidencia (del plan, del corte, de las tareas y los de `/evidencia`) | `[E1]`… | El enlace mismo; el modelo no ve su contenido |
| Descripciones de soportes del revisor | `[S012]` | Índice que el revisor deja en su caché por programa (ID del inventario, sin nombre de archivo) |

No se manda al modelo ningún responsable, correo ni teléfono, y los nombres de personas que el plan trae en los campos de responsables se reemplazan por «[responsable]».

## Evidencia nueva
Se decide **sin modelo** y solo con fechas reales: es nueva la fuente cuya fecha cae en `corte anterior < fecha <= corte`. Cuenta: un enlace registrado con `/evidencia` en esa ventana (fecha de registro); un enlace en la columna del corte que no estaba en cortes anteriores; un soporte del revisor cuya «fecha del documento» (día, mes o año completo) cae por entero en la ventana. Sin fecha legible, la fuente es contexto y no cuenta. Las tareas del cronograma son contexto: su fecha es la planeada, no la de cumplimiento.

Si no hay ninguna fuente nueva, el borrador dice «Sin evidencia nueva en el corte.» (citando el % declarado) y **no se llama al modelo**.

## Citas y verificación
Cada frase termina con sus citas. Un verificador determinista (`avance/borrador.py::verificar`, en la línea de `soportes/verificador.py`) rechaza la frase que:
1. no cita ninguna fuente en el texto, o cuyo campo `citas` no coincide con las del texto;
2. cita una fuente que no existe para esa acción;
3. trae cifras, fechas, enlaces (completos, con o sin esquema) o un % que no están como token literal en las fuentes que cita: una cifra suelta no vale si solo aparece dentro de una fecha o una URL; las fechas «12 de octubre» deben coincidir con una fecha de la fuente; un número o mes escrito con letras sin respaldo literal se marca «revisar». `[P1]` (la acción en el plan) es contexto: solo respalda el % declarado, no cifras ni fechas, y el código de la acción no cuenta como cifra;
4. se apoya solo en `[P1]` sin restituir el % declarado;
5. nombra a una persona.

La frase rechazada **no entra al texto propuesto**: sale aparte con ⚠ y el motivo. Si nombraba a una persona se reemplaza por «[frase omitida: menciona a una persona]»: ni las salidas ni la caché guardan el texto original.

Límite: las cifras escritas con letras («cuarenta») no se comparan.

## Privacidad
**Los filtros son una red de seguridad, no una garantía.** Con expresiones regulares no se detectan todos los nombres ni todas las cifras mal puestas. La revisión humana de Calidad es obligatoria antes de usar el borrador (el aviso sale en la pantalla, en el docx y en el Excel), y por eso la función sigue apagada hasta el aval de datos.

El campo `citas` solo conserva IDs válidos (`P1`, `E3`, `S012`…); lo demás se descarta antes de la caché. Todo texto del plan (objetivo, acción, indicador, cortes, tareas) y de las descripciones del revisor pasa por `ocultar` antes de ir al modelo o a las salidas: nombres de los campos de responsables (sin importar tildes ni mayúsculas, palabra completa), títulos con nombre o apellido («prof.», «dra.», «ing.», «sra.»…, también en minúsculas), «con/por + nombre completo», correos y teléfonos. Los cargos y dependencias («Facultad de Ciencias Exactas», «Dirección del programa») no se tocan. Los caracteres invisibles y los espacios dobles no evaden el filtro.

## Salidas
- `borrador_avance.docx`: encabezado «BORRADOR — propuesta…», una sección por objetivo y acción, el párrafo propuesto, sus fuentes con hoja y fila, y las frases sin fuente marcadas.
- `revision_avance.xlsx`: una fila por acción, con el borrador, las fuentes, lo ya escrito en el plan para ese corte y las columnas **Decisión** (Aprobado / Editar / Descartar), **Texto final** y **Observaciones**.

El texto aprobado se carga a mano en el plan o en el sistema de autoevaluación.

## Desde la web: Calidad → «Borrador de avance del corte»
1. Elegir programa y fecha de corte (la pantalla lista los cortes del plan y el próximo).
2. **Estimar el costo**: dice cuántas acciones irían al modelo y cuántas no. No llama al modelo.
3. Confirmar el costo y **generar** (corre en segundo plano). La confirmación va atada a la cifra mostrada: si la estimación cambió, hay que volver a estimar.
4. Descargar el Word y el Excel. «Borrar» quita las salidas.

API (rol `calidad` o `admin`): `GET /calidad/avance`, `GET /calidad/avance/cortes?programa=`, `POST /calidad/avance/estimar`, `POST /calidad/avance/generar` (exige `confirmo_costo` y el `costo_usd` mostrado), `GET /calidad/avance/descargar/{docx|xlsx}`, `DELETE /calidad/avance`.

## Variables de entorno
| Variable | Por defecto | Uso |
|---|---|---|
| `CALIDAD_AVANCE_ACTIVO` | `false` | Apagado: todas las rutas responden 403 y no se llama al modelo |
| `CALIDAD_AVANCE_TOPE_USD` | `2.0` | Ningún borrador gasta más; la estimación que pasa del tope no corre y el cliente se detiene si el gasto real lo alcanza |

Usa `CALIDAD_REVISOR_DIR` (o la carpeta junto a la base) para salidas y caché, y `ANTHROPIC_API_KEY`. Modelo: `claude-sonnet-5-5`; las propuestas ya pagadas se guardan en `cache/avance/` y no se vuelven a cobrar.

## Para encenderlo
1. El mismo aval de tratamiento de datos que el revisor: el contenido del plan (tareas, cortes anteriores, enlaces) sale hacia la API de Anthropic.
2. `CALIDAD_AVANCE_ACTIVO=true` y la API key en el servicio de calidad.
3. Para citar soportes `[S…]`, correr antes el revisor de soportes del programa: es lo que deja el índice de descripciones. Sin él, el borrador usa solo el plan.
4. Que Calidad pruebe con un programa real fuera del repositorio y confirme el estilo de las frases.

## Límites conocidos
- Los soportes del revisor solo cuentan como nuevos si el modelo leyó una fecha del documento.
- Los nombres se detectan por los campos de responsables del plan y por patrones («profesor + nombre»); un nombre ajeno al plan escrito sin título puede pasar. Calidad revisa cada texto antes de aprobarlo.
- No compara el % declarado con el del corte anterior.
