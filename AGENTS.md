# MemorIA (fcen_bot)

Sistema de agentes de Telegram para la Facultad de Ciencias Exactas y Naturales (UNAL Manizales).

El proyecto se llama **MemorIA**. Cuenta con tres servicios de Telegram que comparten núcleo técnico:
1. **actas**: Asistencia a comités asesores de área curricular (preparación de casos, fichas con alertas, extracción SIA y generación de oficios y actas).
2. **admision**: Gestión y verificación de documentación de admitidos.
3. **calidad**: Plan de mejoramiento, seguimiento de indicadores y acreditación.

El archivo `README.md` describe a fondo el flujo del bot de actas.

---

## Reglas que se mantienen

- **El modelo extrae y redacta; nunca decide el sentido de una recomendación ni despacha acciones.** Toda decisión pasa por un botón o un comando de una persona autorizada.
- **Reglas de la reunión del 28-oct (§5 de `docs/torre-de-control.md`):**
  - El comité asesor **NUNCA aprueba**, solo recomienda **APROBAR** o **NO APROBAR**.
  - Quien decide es el **Consejo de Facultad** (o el **Consejo de Sede** o el **Consejo Superior**, según la instancia competente).
  - Esta regla aplica a plantillas, prompts, botones y textos del bot.
- **Aislamiento de servicios:**
  - Cada servicio tiene su propio token de Telegram, su secreto de webhook y su propia base de datos SQLite.
  - Un servicio **nunca** lee la base de datos de otro.
- **Reglas deterministas y normativa:**
  - Las reglas de `app/services/reglas.py` son deterministas y citan su norma.
  - Las normas se citan con texto literal. No se parafrasean y no se inventan.
- **Privacidad y datos personales:**
  - **Ningún dato real entra al repositorio**: ni estudiantes, ni pruebas, ni fixtures, ni plantillas.
  - Las pruebas y simulaciones usan exclusivamente datos ficticios.
  - Los casos reales para evaluación van en `casos_reales/`, carpeta excluida en `.gitignore`.
- **Secretos:**
  - Los secretos (tokens de bots, secrets de webhooks, API keys) van únicamente en variables de entorno.
- **Verificación obligatoria antes de terminar:**
  - Antes de terminar cualquier tarea o hacer commit/push: `make test`, `make lint` y `make typecheck` en verde.
- **Convención de Git:**
  - Haz commits pequeños y con mensajes descriptivos en español.
  - **Nunca hagas push a `main`**. Trabaja siempre en ramas de tarea/feature/chore.

---

## Stack

Python 3.11+, FastAPI, Pydantic, aiosqlite, anthropic, python-docx y LibreOffice (PDF).
