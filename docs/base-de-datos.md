# Base de datos: SQLite y Postgres

MemorIA corre con dos motores sin cambiar la lógica de negocio:

| | Sin `DATABASE_URL` | Con `DATABASE_URL=postgresql://…` |
|---|---|---|
| Motor | SQLite en `DB_PATH` (por defecto `<DATA_DIR>/<servicio>/fcen.db`) | Postgres, en el esquema del servicio |
| Dónde se usa | Local, pruebas y el despliegue actual | Producción, después del corte |
| Archivos (`media`, `out`) | `<DATA_DIR>/<servicio>/` (volumen) | Igual: siguen en el volumen |

## Cómo funciona

- `app/core/conexion.py` es la capa de conexión. Con Postgres expone la misma interfaz que `aiosqlite` (`execute`, `fetchone`, `fetchall`, `rowcount`, `lastrowid`, `commit`) y traduce lo poco que cambia:
  - marcadores `?` y `:nombre` → los de psycopg;
  - en `CREATE TABLE`: `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGSERIAL`, `INTEGER` → `BIGINT` (los ids de Telegram no caben en 32 bits) y `TIMESTAMP` → `TEXT`;
  - `CURRENT_TIMESTAMP` y `CURRENT_DATE` → texto UTC con el formato de SQLite (`AAAA-MM-DD HH:MM:SS`). El código lee y compara las fechas como texto; así no cambia nada;
  - `lastrowid`: a un `INSERT` en una tabla con `id` serial se le agrega `RETURNING id`.
- El SQL del código está escrito en el dialecto común: `INSERT … ON CONFLICT DO NOTHING` en vez de `INSERT OR IGNORE`, `substr(creado, 1, 7)` en vez de `strftime`. Lo propio de SQLite (`PRAGMA`, `sqlite_master`, `INSERT OR …`, `strftime`, `date('now')`) falla con un error claro (`SQLNoPortable`) si llega a Postgres.
- `app/db/session.py` elige el motor: con `DATABASE_URL`, Postgres; sin ella, SQLite como siempre.

### Un esquema por servicio

Los tres servicios pueden compartir el mismo servidor Postgres, pero cada uno usa su esquema: `actas`, `calidad` o `admision` (en el entorno de práctica, `practica_<servicio>`). La conexión fija `search_path` solo en ese esquema, sin `public`, así que un servicio no ve las tablas de otro. Actas sigue pidiendo a calidad y admisión sus cifras agregadas por HTTP (`/internal/cifras`); eso no cambia.

- `DB_SCHEMA` cambia el esquema (casi nunca hace falta). Debe ser un nombre simple (`[a-z_][a-z0-9_]*`).
- Calidad o admisión con `DB_SCHEMA=actas` no arrancan.

Endurecimiento opcional: un rol de Postgres por servicio, dueño solo de su esquema, para que el aislamiento no dependa del código.

```sql
CREATE ROLE memoria_calidad LOGIN PASSWORD '<otra clave>';
CREATE SCHEMA IF NOT EXISTS calidad AUTHORIZATION memoria_calidad;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
```

En ese caso, la `DATABASE_URL` del servicio se arma con ese usuario en vez de la referencia común.

## Crear el Postgres en Railway

1. En el proyecto de Railway: **+ New → Database → PostgreSQL**. Railway crea un servicio `Postgres` con su volumen y las variables `DATABASE_URL` (red privada, `postgres.railway.internal`) y `DATABASE_PUBLIC_URL`.
2. En el servicio `Postgres` → **Backups**: activar los respaldos diario, semanal y mensual. **Los respaldos los hace Railway Pro**, igual que los de los volúmenes de los servicios; MemorIA no hace copias propias de la base.
3. En cada servicio (actas, calidad, admision), la variable se define como **referencia**, no copiando la URL:

   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ```

   Así la clave nunca queda escrita en otro lado y, si Railway la rota, los servicios la toman en el siguiente despliegue. Usar la URL privada, no `DATABASE_PUBLIC_URL`.
4. El volumen de cada servicio se queda: ahí siguen `media`, `out` y la SQLite de antes del corte (sirve para volver atrás).

## Migración (un servicio a la vez)

Empezar por el que tenga menos uso (admision), luego calidad y al final actas. Hacerlo en un horario sin actividad: lo que llegue entre la copia y el cambio de variable queda solo en SQLite.

1. **Respaldo del volumen.** Servicio → volumen → **Backups → Back up now**. Anotar la hora.
2. **Ver qué base usa hoy.** `GET /health` → `almacenamiento.db_path` (actas puede seguir en `/data/fcen.db`, la ruta antigua).
3. **Dar acceso a Postgres sin cortar.** En el servicio, agregar `MIGRACION_DATABASE_URL=${{Postgres.DATABASE_URL}}`. El servicio no la usa: sigue en SQLite.
4. **Copiar.** Desde una terminal en el contenedor (`railway ssh --service <servicio>`):

   ```bash
   uv run --no-dev python scripts/migrar_sqlite_a_postgres.py --sqlite /data/<servicio>/fcen.db --servicio <servicio>
   ```

   El script lee la SQLite en solo lectura y en una sola foto, crea el esquema y las tablas, copia las filas en una transacción y ajusta los contadores de id. Es idempotente: correrlo dos veces no duplica nada.
5. **Verificar conteos.** El script imprime `tabla / sqlite / postgres`. Si alguna no coincide, deshace la copia, no guarda nada y sale con código 1. Para repetir solo la comparación:

   ```bash
   uv run --no-dev python scripts/migrar_sqlite_a_postgres.py --sqlite /data/<servicio>/fcen.db --servicio <servicio> --solo-verificar
   ```

6. **Cambiar la variable.** Agregar `DATABASE_URL=${{Postgres.DATABASE_URL}}` al servicio. Railway redespliega. El healthcheck (`/health`) solo pasa si Postgres responde; si no, Railway deja corriendo el despliegue anterior (en SQLite).
7. **Comprobar.** `GET /health` debe mostrar `"base": {"motor": "postgres", "esquema": "<servicio>", "conectada": true, …}`. Entrar a la web y abrir un caso (o el tablero) conocido.
8. Quitar `MIGRACION_DATABASE_URL`.

### Vuelta atrás

Quitar `DATABASE_URL` del servicio. Railway redespliega y el servicio vuelve a la SQLite del volumen, que el script no tocó. Lo que se haya guardado en Postgres después del corte no está en la SQLite: si hay que conservarlo, se recupera del esquema en Postgres antes de borrarlo.

## `/health`

- `base`: el motor y dónde está la base, sin credenciales.
  - SQLite: `{"motor": "sqlite", "db_path": …}`.
  - Postgres: `{"motor": "postgres", "esquema": …, "servidor": "host:puerto/base", "conectada": true}`.
- Con SQLite, en Railway responde 503 si `DATA_DIR` no es un volumen montado (cada despliegue arrancaría con la base vacía).
- Con Postgres no exige el volumen para la base: responde 200 con un `aviso` si falta, porque `media` y `out` sí se perderían. Responde 503 si Postgres no responde.
- `almacenamiento` sigue listando las bases SQLite del volumen (después del corte, la de antes).

## Pruebas

- `make test`: toda la suite con SQLite, como siempre.
- Con `TEST_DATABASE_URL=postgresql://…`, la misma suite corre contra Postgres: cada prueba en un esquema propio que se borra al terminar. Las pocas pruebas que abren el archivo SQLite directamente llevan `@pytest.mark.solo_sqlite` y se saltan.
- `tests/test_postgres.py`: traducción de SQL (siempre) y, con servidor, aislamiento entre esquemas, ids grandes, `lastrowid` y el script de migración (copia, idempotencia, contadores y verificación de conteos).
- En CI, el job `postgres` levanta un `postgres:16` y corre la suite con `TEST_DATABASE_URL`.

Sin Docker, un Postgres local para pruebas: `pip install pgserver` en un entorno aparte (no es dependencia del proyecto) y `pgserver.get_server(<carpeta>).get_uri()`.
