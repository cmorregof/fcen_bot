# Respaldo nocturno y archivo oficial en Google Drive

MemorIA tiene dos usos de Google Drive. Los dos quedan apagados mientras falte alguna de las variables `DRIVE_*`: nada se sube y nada falla.

1. **Copia nocturna de la base.** Cada noche, cada servicio (actas, calidad y admisión) sube una copia comprimida de su propia base. Es una segunda línea, además de los respaldos del volumen que hace Railway Pro.
2. **Archivo oficial.** Las actas, los oficios y las resoluciones **firmados** quedan en Drive, ordenados por tipo, año, área curricular y programa, con un índice por año.

La cuenta dueña hoy es la cuenta @unal.edu.co de Carlos. Más adelante pasa a la de la Vicedecanatura (ver «Cambiar de cuenta»).

## Qué queda en Drive

```
MemorIA/                                     ← DRIVE_CARPETA_ID
├── Respaldos/
│   ├── actas/memoria_actas_20261031.db.gz
│   ├── calidad/memoria_calidad_20261031.db.gz
│   └── admision/memoria_admision_20261031.db.gz
├── Actas/
│   └── 2026/
│       ├── Índice Actas 2026.xlsx
│       └── Ciencias Naturales/
│           └── Ingeniería Física/Acta_019_ing_fisica_20261030.pdf
├── Oficios/2026/Índice Oficios 2026.xlsx, <área>/<programa>/Oficio_<número>_<programa>_<AAAAMMDD>.pdf
└── Resoluciones/2026/…
```

### Copia nocturna

- Con SQLite (sin `DATABASE_URL`), la copia se toma con el API de respaldo de SQLite (`sqlite3` `backup`): es consistente aunque el servicio esté escribiendo. El nombre es `memoria_<servicio>_<AAAAMMDD>.db.gz`.
- Con Postgres (`DATABASE_URL`, ver `docs/base-de-datos.md`), la copia es `pg_dump --schema=<DB_SCHEMA>` en formato custom (ya comprimido): solo el esquema del servicio, nunca el de otro. El nombre es `memoria_<servicio>_<AAAAMMDD>.dump`. La SQLite que haya quedado en el volumen ya no se copia.
  - `pg_dump` viene en la imagen (cliente 17 de PGDG, sirve para Postgres 16 y 17). Si falta, el endpoint responde `activo: false` con un `motivo` y no sube nada. Si `pg_dump` falla (por ejemplo, un servidor más nuevo que el cliente), responde 502 y el cron queda en rojo.
  - La clave va por `PGPASSWORD`, no en la línea de comandos.
- Si se corre dos veces el mismo día, se reemplaza la copia de ese día.
- Se conservan las últimas `DRIVE_RESPALDOS_CONSERVAR` copias (30 por defecto). Las más viejas van a la **papelera** de Drive, y solo las de `Respaldos/<servicio>/` con ese patrón de nombre. Drive vacía la papelera a los 30 días; mientras tanto se pueden recuperar.
- La programa `.github/workflows/respaldo-drive.yml` a las 2:15 a. m. (hora de Bogotá). Llama a `POST /internal/respaldo-drive` de cada servicio con el secreto `X-Cron-Secret`, igual que los otros cron. Usa los secrets de GitHub `APP_URL` (actas), `CALIDAD_APP_URL` y, si existe, `ADMISION_APP_URL`. Si la URL de un servicio no está, lo salta.
- El entorno de práctica (`MEMORIA_PRACTICA=true`) nunca sube nada.
- El volcado está detrás de la interfaz `Volcador` de `app/services/drive/respaldo.py` (`VolcadorSqlite` o `VolcadorPostgres`); la subida y la retención son las mismas. Las copias `.db.gz` de antes del corte y las `.dump` cuentan juntas para la retención.

### Archivo oficial: cuándo se archiva

MemorIA solo produce **borradores**: el oficio y el acta del comité salen en Word con «[la firma se agrega al firmar]», y el borrador del oficio o la resolución del Consejo sale con campos en amarillo y la marca «BORRADOR · pendiente de revisión, número y firma de la Secretaría de Facultad». La firma, el número y la expedición pasan fuera de MemorIA. No hay en MemorIA un estado «firmado» que se pueda detectar.

Por eso la decisión es: **se archiva el PDF firmado que una persona sube y confirma con un botón**. MemorIA no decide qué es definitivo.

| Documento | Quién lo archiva | Dónde, en la web | Qué exige |
| --- | --- | --- | --- |
| Acta del comité asesor | La administrativa del área | «Oficio y acta» → «Archivar el acta firmada» | Programa de su área, número del acta, fecha de la sesión y el PDF |
| Oficio o resolución del Consejo | Secretaría de Facultad (o admin) | «Notificaciones» → «Archivar firmado (PDF)» en la fila del caso | El caso con número y fecha de expedición ya guardados (acto expedido) |

Para no archivar borradores:

- Solo se acepta PDF. Un Word se rechaza.
- Se rechaza un PDF con las marcas de borrador de MemorIA (por ejemplo, un borrador exportado a PDF sin firmar).
- Para oficios y resoluciones, el botón aparece solo cuando la Secretaría ya registró número y fecha de expedición.
- Si ya hay un archivo con el mismo nombre en la carpeta, no se sobrescribe (responde 409).

El nombre del archivo es `<Tipo>_<número>_<programa>_<AAAAMMDD>.pdf`; la fecha es la de la sesión (acta) o la de expedición (oficio o resolución).

### Índice

En cada carpeta de año (`Actas/2026/`, `Oficios/2026/`, `Resoluciones/2026/`) hay un `Índice <Tipo> <año>.xlsx` con el estilo del índice electrónico de Calidad: encabezado del fondo y una fila por documento con número de orden, fecha del documento, tipo documental, número o radicado, área curricular, programa, nombre del archivo, fecha de incorporación, formato, tamaño y quién lo archivó. Cada archivo nuevo agrega su fila. El índice no lleva nombres de estudiantes.

## Activarlo (lo hace Carlos)

Nadie más escribe credenciales. Ni el token ni el secreto van al repositorio, a un chat o a un correo.

### 1. Crear el cliente OAuth en Google Cloud, con la cuenta @unal.edu.co

1. Entre a <https://console.cloud.google.com/> con la cuenta @unal.edu.co.
2. Cree un proyecto, por ejemplo `memoria-fcen`. Si la Universidad no deja crear proyectos a esa cuenta, hay que pedirlo a la Dirección de TI de la Sede.
3. **APIs y servicios → Biblioteca**: busque **Google Drive API** y actívela.
4. **APIs y servicios → Pantalla de consentimiento de OAuth** (Google Auth Platform → Público):
   - Tipo de usuario: **Interno**. Así solo cuentas @unal.edu.co pueden autorizarla, no hace falta verificación de Google y el refresh token no vence a los 7 días (eso pasa con apps «Externas» en modo de prueba).
   - Nombre: `MemorIA`; correo de asistencia: el suyo.
   - Alcances (Acceso a los datos): agregue solo `.../auth/drive.file`.
5. **Credenciales → Crear credenciales → ID de cliente de OAuth**, tipo **App de escritorio**, nombre `MemorIA Drive`. Copie el **ID de cliente** y el **secreto del cliente**.

**Por qué `drive.file`.** Es el alcance mínimo: la app solo ve los archivos y carpetas que ella misma creó, nada más del Drive de la cuenta. Sirve porque el script del paso 2 crea la carpeta raíz con esa misma autorización. Una carpeta creada a mano en Drive **no** sirve: la app no la vería.

### 2. Obtener el refresh token y crear la carpeta

En su máquina, desde el repositorio:

```bash
DRIVE_CLIENT_ID='<id de cliente>' DRIVE_CLIENT_SECRET='<secreto>' uv run python scripts/drive_autorizar.py
```

Se abre el navegador; ingrese con la cuenta @unal.edu.co y acepte. El script crea la carpeta `MemorIA` en su Drive e imprime `DRIVE_REFRESH_TOKEN` y `DRIVE_CARPETA_ID`. No guarda nada en disco. Con `--carpeta "Otro nombre"` cambia el nombre de la carpeta.

### 3. Poner las variables en Railway

En **cada** servicio que deba respaldarse (actas, calidad y admisión), en *Variables*:

```
DRIVE_CLIENT_ID=<id de cliente>
DRIVE_CLIENT_SECRET=<secreto>
DRIVE_REFRESH_TOKEN=<lo que imprimió el script>
DRIVE_CARPETA_ID=<lo que imprimió el script>
DRIVE_RESPALDOS_CONSERVAR=30
```

Los cuatro primeros son los mismos en los tres servicios. Cada servicio sube solo su propia base a su propia subcarpeta.

### 4. Secrets de GitHub para el cron

Ya existen `APP_URL`, `CALIDAD_APP_URL` e `INTERNAL_CRON_SECRET`. Si quiere respaldar también admisión, agregue `ADMISION_APP_URL` con la URL pública del servicio de admisión (y `INTERNAL_CRON_SECRET` igual en ese servicio).

### 5. Probar

En GitHub → *Actions* → «Respaldo nocturno en Drive» → *Run workflow*. Cada servicio debe responder `{"ok": true, "activo": true, "archivo": "memoria_<servicio>_<fecha>.db.gz", …}` y el archivo debe aparecer en `MemorIA/Respaldos/<servicio>/`. Si responde `"activo": false`, falta alguna variable en ese servicio.

Para el archivo oficial: en la web, «Oficio y acta» muestra «Archivar el acta firmada» solo cuando Drive está activo.

## Restaurar desde una copia

### Ver una copia en su computador

1. En Drive, `MemorIA/Respaldos/<servicio>/`, descargue la copia (por ejemplo `memoria_actas_20261030.db.gz`).
2. Descomprima: `gunzip memoria_actas_20261030.db.gz`.
3. Verifique: `sqlite3 memoria_actas_20261030.db "PRAGMA integrity_check"` debe responder `ok`.

Contiene datos de estudiantes: no la copie al repositorio ni la deje en carpetas compartidas.

### Ponerla en uso en Railway

Hágalo en un momento sin uso: lo que se escriba entre la copia y la restauración se pierde.

```bash
railway ssh --service <servicio>
uv run --no-dev python scripts/drive_restaurar.py                                    # lista las copias
uv run --no-dev python scripts/drive_restaurar.py --archivo memoria_actas_20261030.db.gz            # descarga y verifica
uv run --no-dev python scripts/drive_restaurar.py --archivo memoria_actas_20261030.db.gz --aplicar  # la pone en uso
```

Con `--aplicar`, la base actual queda al lado como `fcen.db.antes-<fecha>` (con sus `-wal` y `-shm`), y la copia ocupa su lugar. Después reinicie el servicio en Railway (*Restart*). Si algo sale mal, vuelva a poner el archivo `.antes-<fecha>` con su nombre original y reinicie.

Si el volumen se perdió por completo, primero cree el volumen `/data` en el servicio (ver `docs/despliegue-servicios.md`), despliegue, y luego restaure como arriba.

### Postgres (copias `.dump`)

Primero mire si basta un respaldo de Railway Pro del servicio `Postgres`: es lo más directo. La copia de Drive es para cuando ese no sirve.

```bash
railway ssh --service <servicio>
uv run --no-dev python scripts/drive_restaurar.py --archivo memoria_actas_20261030.dump   # la descarga en /data
pg_restore --list /data/memoria_actas_20261030.dump | head                               # verifica que se lee
```

Para ponerla en uso, en un momento sin uso y después de un respaldo manual de Railway del servicio `Postgres`:

```bash
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$DATABASE_URL" /data/memoria_actas_20261030.dump
```

Eso reemplaza solo el esquema del servicio (el `.dump` no trae otros). Después reinicie el servicio y borre el `.dump` de `/data`.

## Cambiar de cuenta (a la Vicedecanatura)

1. Con la cuenta de la Vicedecanatura, repita los pasos 1 y 2 (o use el mismo proyecto de Google Cloud si la Vicedecanatura queda como propietaria).
2. Cambie `DRIVE_REFRESH_TOKEN` y `DRIVE_CARPETA_ID` (y, si es otro cliente, `DRIVE_CLIENT_ID` y `DRIVE_CLIENT_SECRET`) en los tres servicios.
3. Lo ya archivado en la cuenta de Carlos se mueve a mano: comparta la carpeta `MemorIA` con la Vicedecanatura o transfiera la propiedad desde Drive. La app nueva no ve lo que creó la anterior; los índices nuevos empiezan en la carpeta nueva.
4. Quite el acceso de la app anterior en <https://myaccount.google.com/permissions>.

## Errores comunes

- `Google no renovó el acceso: invalid_grant`: el refresh token se revocó o venció (por ejemplo, app «Externa» en modo de prueba, o cambio de contraseña). Repita el paso 2 y actualice `DRIVE_REFRESH_TOKEN`.
- `Drive respondió 404` al subir: `DRIVE_CARPETA_ID` no es una carpeta creada por esta app. Use la que entrega el script.
- El cron responde 502: el servicio no pudo leer su base o Drive falló. El detalle queda en los logs de Railway.
