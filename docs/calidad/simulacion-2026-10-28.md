# Simulación del servicio de calidad — 2026-10-28

Datos 100 % ficticios: los dos planes de `docs/calidad/` usan la plantilla institucional de cinco hojas. Base temporal; no se envió nada a Telegram.

> Te ayudo a seguir el plan de mejoramiento y a saber a quién acudir. No reemplazo el seguimiento de la DAMA ni las decisiones de los comités.

## Importación (`/importar_plan`)

### Resumen antes de guardar

**Resumen de plantilla_plan_mejoramiento.xlsx**
Programa: **Ejemplo Alfa (ficticio)** (nuevo)
• Objetivos: 3 · acciones: 7 · tareas del cronograma: 5 (años: 2025, 2026)
• Avance promedio de las acciones: 54 %
• Acciones nuevas: 7 · actualizadas: 0 · sin cambios: 0
• Cortes de avance: 5 nuevos, 0 con cambios. Los anteriores se conservan.

Sin alertas de lectura.

Nada se guarda hasta que confirmes.

Reimportar el mismo archivo: 0 nuevas, 0 actualizadas, 7 sin cambios, 0 cortes nuevos (no duplica).

### Resumen antes de guardar

**Resumen de plantilla_plan_mejoramiento_beta.xlsx**
Programa: **Ejemplo Beta (ficticio)** (nuevo)
• Objetivos: 2 · acciones: 5 · tareas del cronograma: 4 (años: 2026)
• Avance promedio de las acciones: 47 %
• Acciones nuevas: 5 · actualizadas: 0 · sin cambios: 0
• Cortes de avance: 8 nuevos, 0 con cambios. Los anteriores se conservan.

Sin alertas de lectura.

Nada se guarda hasta que confirmes.

Reimportar el mismo archivo: 0 nuevas, 0 actualizadas, 5 sin cambios, 0 cortes nuevos (no duplica).

**Soportes registrados con `/evidencia`:** Ejemplo Alfa (ficticio) 1.1.2, Ejemplo Beta (ficticio) 1.2 (quedan por revisar; no cambian el % de avance).

## Ejemplo Alfa (ficticio)

### Respuesta a `/plan`

**Plan de mejoramiento — Ejemplo Alfa (ficticio)**
7 acciones · avance promedio 54 % · 5 tareas en el cronograma (2025, 2026)
🔴 2 vencidas · ⛔ 0 marcadas «NO FUNCIONÓ» · 🔵 2 en curso · ⚪ 1 por iniciar · 🟢 2 cumplidas · 🔁 3 reprogramadas
Próximo corte: 2026-11-21 (estimado: último corte del plan + 6 meses)

**Acciones y % de avance**
🔵 1.1.1 60 % — Publicar piezas de difusión del proyecto educativo
🔴 1.1.2 50 % — Realizar jornadas con profesores y estudiantes
🔵 1.1.3 40 % — Aplicar la encuesta de conocimiento del proyecto educa…
🟢 1.2.1 100 % — Ajustar el documento según el plan de estudios
🟢 1.2.2 100 % — Obtener el aval del Consejo de Facultad
🔴 2.1.1 30 % — Crear canales de comunicación con egresados
⚪ 2.1.2 0 % — Actualizar la base de datos de egresados

**🔴 Vencidas (2)** — fin pasada y avance < 100 %
• **1.1.2** 50 % — Realizar jornadas con profesores y estudiantes (fin 2026-09-30)
   Responsables: Comité Asesor del programa (ejemplo)
• **2.1.1** 30 % — Crear canales de comunicación con egresados (fin 2026-09-30)
   Responsables: Dirección del programa (ejemplo)

**🔁 Reprogramadas (3)**
• **1.1.1** «Tercera reprogramación»; 1 tarea del cronograma
• **1.2.2** fin anterior 2025-02-01
• **2.1.1** «Tercera reprogramación»; 1 tarea del cronograma

**🔵 En curso (2)**: 1.1.1, 1.1.3

**⚪ Por iniciar (1)**: 2.1.2

**🟢 Cumplidas (2)**: 1.2.1, 1.2.2

**Responsables (acciones abiertas)**
• Dirección del programa (ejemplo): 1.1.1, 2.1.1
• Oficina de Calidad (ejemplo): 1.1.3, 2.1.2
• Comité Asesor del programa (ejemplo): 1.1.2

Soportes registrados en el bot, por revisar: 1.

### Alerta quincenal (`/alerta_vista_previa`)

**Alerta quincenal — Ejemplo Alfa (ficticio)** (2026-10-28)
Próximo corte: 2026-11-21 (estimado: último corte del plan + 6 meses)

**🔴 Vencidas (2)**
• **1.1.2** 50 % — Realizar jornadas con profesores y estudiantes (fin 2026-09-30)
   Responsables: Comité Asesor del programa (ejemplo)
• **2.1.1** 30 % — Crear canales de comunicación con egresados (fin 2026-09-30)
   Responsables: Dirección del programa (ejemplo)

**🟡 Vencen en las próximas 4 semanas (1)**
• **1.1.3** 40 % — Aplicar la encuesta de conocimiento del proyecto educativo (fin 2026-11-15)
   Responsables: Oficina de Calidad (ejemplo)

**🔁 Reprogramadas sin cumplir (2)**
• **1.1.1** «Tercera reprogramación»; 1 tarea del cronograma
• **2.1.1** «Tercera reprogramación»; 1 tarea del cronograma

Registra un soporte con /evidencia <programa> <código> [enlace].
_Te ayudo a seguir el plan de mejoramiento y a saber a quién acudir. No reemplazo el seguimiento de la DAMA ni las decisiones de los comités._

### Reporte `/reporte` (Excel)

Pestañas: estado, acciones, tareas, cortes, fuentes.

| Cifra | Valor | Filas en «fuentes» |
|---|---|---|
| Acciones | 7 | 7 |
| Acciones vencidas | 2 | 2 |
| Acciones marcadas «NO FUNCIONÓ» | 0 | — |
| Acciones en curso | 2 | 2 |
| Acciones por iniciar | 1 | 1 |
| Acciones cumplidas | 2 | 2 |
| Acciones reprogramadas | 3 | 3 |
| Acciones con soportes por revisar | 1 | 1 |
| Avance promedio (%) | 54.3 | — |
| Tareas del cronograma | 5 | — |
| Próximo corte (estimado) | 2026-11-21 | — |

## Ejemplo Beta (ficticio)

### Respuesta a `/plan`

**Plan de mejoramiento — Ejemplo Beta (ficticio)**
5 acciones · avance promedio 47 % · 4 tareas en el cronograma (2026)
🔴 1 vencidas · ⛔ 1 marcadas «NO FUNCIONÓ» · 🔵 1 en curso · ⚪ 1 por iniciar · 🟢 1 cumplidas · 🔁 1 reprogramadas
Próximo corte: 2026-12-25 (estimado: último corte del plan + 6 meses)

**Acciones y % de avance**
⛔ 1.1 20 % — Revisar el tiempo de permanencia por cohorte
🔴 1.2 40 % — Entregar la propuesta de asignatura de acompañamiento
🔵 2.1 75 % — Implementar el seminario permanente del programa
⚪ 2.2 0 % — Elaborar el diagnóstico de la situación laboral de egr…
🟢 2.3 100 % — Divulgar los resultados del seminario

**🔴 Vencidas (1)** — fin pasada y avance < 100 %
• **1.2** 40 % — Entregar la propuesta de asignatura de acompañamiento (fin 2026-06-30)
   Responsables: Comité Asesor del programa (ejemplo)

**🔁 Reprogramadas (1)**
• **1.1** «Tercera reprogramación»; 1 tarea del cronograma

**⛔ Marcadas «NO FUNCIONÓ» (1)**
• **1.1** 20 % — Revisar el tiempo de permanencia por cohorte (fin 2028-08-30)
   Responsables: Comité Asesor del programa (ejemplo)

**🔵 En curso (1)**: 2.1

**⚪ Por iniciar (1)**: 2.2

**🟢 Cumplidas (1)**: 2.3

**Responsables (acciones abiertas)**
• Comité Asesor del programa (ejemplo): 1.2
• Dirección del programa (ejemplo): 2.1
• Oficina de Calidad (ejemplo): 2.2

Soportes registrados en el bot, por revisar: 1.

### Alerta quincenal (`/alerta_vista_previa`)

**Alerta quincenal — Ejemplo Beta (ficticio)** (2026-10-28)
Próximo corte: 2026-12-25 (estimado: último corte del plan + 6 meses)

**🔴 Vencidas (1)**
• **1.2** 40 % — Entregar la propuesta de asignatura de acompañamiento (fin 2026-06-30)
   Responsables: Comité Asesor del programa (ejemplo)

**⛔ Marcadas «NO FUNCIONÓ» (1)**
• **1.1** 20 % — Revisar el tiempo de permanencia por cohorte (fin 2028-08-30)
   Responsables: Comité Asesor del programa (ejemplo)

**🔁 Reprogramadas sin cumplir (1)**
• **1.1** «Tercera reprogramación»; 1 tarea del cronograma

Registra un soporte con /evidencia <programa> <código> [enlace].
_Te ayudo a seguir el plan de mejoramiento y a saber a quién acudir. No reemplazo el seguimiento de la DAMA ni las decisiones de los comités._

### Reporte `/reporte` (Excel)

Pestañas: estado, acciones, tareas, cortes, fuentes.

| Cifra | Valor | Filas en «fuentes» |
|---|---|---|
| Acciones | 5 | 5 |
| Acciones vencidas | 1 | 1 |
| Acciones marcadas «NO FUNCIONÓ» | 1 | 1 |
| Acciones en curso | 1 | 1 |
| Acciones por iniciar | 1 | 1 |
| Acciones cumplidas | 1 | 1 |
| Acciones reprogramadas | 1 | 1 |
| Acciones con soportes por revisar | 1 | 1 |
| Avance promedio (%) | 47 | — |
| Tareas del cronograma | 4 | — |
| Próximo corte (estimado) | 2026-12-25 | — |
