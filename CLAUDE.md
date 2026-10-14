# fcen_bot

Bot de Telegram para los comités asesores de la FCEN (UNAL Manizales). El README describe el flujo.

## Reglas que se mantienen

- El modelo extrae y redacta; nunca decide el sentido de una recomendación ni despacha acciones. Toda decisión pasa por un botón o un comando.
- Las reglas de `app/services/reglas.py` son deterministas y citan su norma.
- Las normas se citan con texto literal. No se parafrasean y no se inventan.
- Ningún dato real de estudiantes entra al repositorio: ni pruebas, ni fixtures, ni plantillas. Los casos de evaluación van en `casos_reales/`, que está en .gitignore.
- Los secretos (token del bot, API key) van solo en variables de entorno.
- Antes de un push: `make test`, `make lint` y `make typecheck`.

## Stack

Python 3.11+, FastAPI, Pydantic, aiosqlite, anthropic, python-docx y LibreOffice (PDF).
