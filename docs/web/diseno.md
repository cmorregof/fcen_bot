# Web de MemorIA: diseño

Estado: propuesta implementada en la rama `claude/feat-web-memoria-2e5896`. Nada está desplegado.

## 1. Por qué una web

Las personas que usan MemorIA a diario rondan los 50 años y Telegram les resulta difícil
(responder a un mensaje concreto, botones que se pierden en el chat). La web es la interfaz
principal. Telegram sigue funcionando igual y queda pensado para la Decana y los vicedecanos (§7).

## 2. Roles y herramientas

Cada rol ve solo sus herramientas. El menú se arma con los roles que devuelve cada backend;
un backend rechaza (403) cualquier llamada de un rol que no le corresponde.

| Rol | Servicio | Qué puede hacer | Qué no puede hacer |
|---|---|---|---|
| `administrativa` (administrativa de área curricular) | actas | Crear casos (texto del correo y pantallazos), procesarlos, ver la ficha con alertas, corregirla, registrar la recomendación del comité («Recomendar aprobar», «Recomendar no aprobar», «Pendiente»), nota y conceptos, descargar oficio y acta (.docx). Solo los casos de **su** área curricular. | Ver casos de otra área. Decidir: el comité solo recomienda y decide el Consejo. |
| `comite` (director o miembro de comité asesor) | actas | Consultar los casos y fichas de su área y registrar su propio concepto. | Crear o procesar casos, registrar la recomendación, descargar documentos. |
| `calidad` | calidad | Importar el plan (.xlsx) con vista previa y confirmación, ver el estado por programa, registrar evidencias por enlace, vista previa de alertas, descargar el reporte, buscar en «¿A quién acudo?». | Enviar alertas (el envío real sigue apagado y se activa por variable de entorno). |
| `admision` (responsable del proceso) | admisión | Ver métricas agregadas y la lista de chequeo. | Ver documentos ni preguntas de admitidos: no se guardan. |
| `admitido` | admisión | Sin cuenta. Lee el aviso de datos, acepta (y, si es menor, su acudiente), pregunta por el listado y revisa un documento a la vez. | Nada más. No hay historial: cada visita empieza de cero. |
| `decanatura` (Decana y vicedecanos) | todos | Tableros de solo lectura: cifras agregadas de cada servicio. | Ver nombres de estudiantes ni documentos; modificar nada. |
| `admin` | cada servicio | Autorizar correos y asignar roles en ese servicio. | — |

**Ajustes respecto al pedido, y por qué:**

- **Decanatura y vicedecanatura son un solo rol.** Ven lo mismo (tableros de solo lectura); separarlos
  duplica permisos sin cambiar pantallas. Si más adelante un vicedecanato debe ver solo su parte, se
  agrega un filtro, no un rol.
- **`comite` queda atado a un área curricular**, igual que la administrativa: un director de área no
  necesita ver casos de otra, y así se reduce la exposición de datos de estudiantes.
- **Se agrega `admin`.** Alguien tiene que autorizar correos. Los primeros admins se declaran por
  variable de entorno (`WEB_ADMINS`); después se gestionan desde la pantalla «Usuarios».
- **Los tableros muestran solo cifras.** La Decana no necesita nombres para ver el avance; si un
  caso concreto le interesa, lo pide al área.

## 3. Autenticación

- **Personal: Google con dominio `@unal.edu.co`.** El navegador obtiene un *ID token* de Google
  (Google Identity Services) y lo envía a `POST /api/web/sesion` de cada backend. El backend:
  1. verifica la firma, la audiencia (`WEB_GOOGLE_CLIENT_ID`), la vigencia y que el dominio
     (`hd`) y el correo terminen en `@unal.edu.co`;
  2. busca el correo en su tabla `web_usuarios` (o en `WEB_ADMINS`);
  3. si está autorizado, entrega una **sesión propia** firmada con `WEB_SESSION_SECRET`
     (8 horas) con correo, rol y área. Si no, responde 403 «Tu correo no está autorizado».
- **Cada servicio tiene su propia tabla de usuarios autorizados**, en su propia base. Así ningún
  servicio lee la base de otro. Una persona con roles en dos servicios aparece en las dos tablas.
- **Admitidos sin cuenta.** Aceptan el aviso de datos y reciben una sesión anónima de 2 horas que
  solo dice «aceptó» (y si es menor, «acudiente aceptó»). No se guarda nada que los identifique.
- **Sin contraseñas propias.** Nunca se pide ni se guarda una contraseña.
- **Modo local.** Con `WEB_AUTH_DEV=true` existe `POST /api/web/sesion/dev` para entrar con un
  correo ficticio sin Google. El backend lo rechaza si detecta Railway (`RAILWAY_ENVIRONMENT`).

## 4. Arquitectura

```
Navegador ──(páginas y JS)──► Vercel: web/ (Next.js, sin datos)
    │
    ├──► Railway actas     /api/web/actas/*     base actas
    ├──► Railway calidad   /api/web/calidad/*   base calidad
    └──► Railway admisión  /api/web/admision/*  base admisión
```

- **Frontend `web/`**: Next.js con TypeScript. Solo sirve páginas; **no tiene rutas de servidor que
  toquen datos**. El navegador llama directo al backend del servicio (`NEXT_PUBLIC_API_ACTAS`,
  `…_CALIDAD`, `…_ADMISION`). Así los datos de estudiantes nunca pasan por Vercel.
- **Backends**: el mismo FastAPI de hoy. `app/api/web/` agrega el router web y **solo monta las
  rutas del servicio que indica `BOT_SERVICIO`**: el backend de calidad no tiene rutas de actas.
- **Lógica compartida con Telegram.** Las funciones que hacen el trabajo viven en el servicio y
  sirven a los dos canales:
  - calidad: `app/servicios/calidad/plan.py`, `directorio.py`, `reporte.py`, `alertas.py`
    (ya separados) más `operaciones.py` (vista previa y confirmación de importación).
  - admisión: `app/servicios/admision/flujo.py` (responder una pregunta, revisar un documento y
    contar métricas). El manejador de Telegram ahora llama a estas funciones.
  - actas: `app/services/casos.py` (procesar, corregir, analizar). `bot.py` las usa.
- **Tableros de la Decana**: el navegador llama `GET /api/web/<servicio>/tablero` en cada backend
  y los muestra juntos. Ningún backend consulta a otro.
- **CORS**: cada backend acepta solo los orígenes de `WEB_ORIGINS`.

## 5. Accesibilidad (usuarios de unos 50 años)

- Letra base de 20 px, títulos de 32 px, interlineado amplio; contraste AA o mejor (texto casi
  negro sobre blanco, azul oscuro para acciones). Funciona con el zoom del navegador.
- Todo en español, sin jerga: «Revisar documento», no «Upload»; «Recomendar aprobar», no «OK».
- **Pocos pasos**: cada pantalla tiene una tarea principal y un botón grande para hacerla.
- **Etiquetas explícitas** en cada campo, nunca solo un ícono ni un *placeholder*.
- Cada pantalla abre con un recuadro **«Qué hace esta pantalla / Qué no hace»**.
- Mensajes de error que dicen qué pasó y qué hacer.
- Foco visible para teclado, botones de al menos 48 px de alto.
- Estilo sobrio, sin logos oficiales hasta tener aval. El nombre es «MemorIA · FCEN».

## 6. Datos y privacidad

- Los documentos de admitidos se revisan en memoria y se descartan; solo se suman contadores.
- Las fichas y documentos de actas viven en el volumen de Railway del servicio de actas.
- El frontend guarda la sesión en `sessionStorage` (se borra al cerrar la pestaña).
- Datos ficticios para correrlo en local: `scripts/datos_web_ficticios.py`.

## 7. Telegram para la Decana y los vicedecanos (no implementado)

Lo que tendría sentido allí, por ser avisos breves que se leen en el celular:

- **Resumen semanal** (lunes 7 a. m.): casos recibidos y con recomendación por área; tareas del plan
  vencidas y próximas a vencer por programa; admitidos atendidos y errores más frecuentes.
- **Avisos puntuales**: una tarea del plan que vence en 7 días sin evidencia; un área con casos
  pendientes de comité por más de dos semanas.
- **Indicadores a pedido**: `/tablero` devuelve las mismas cifras de la web.
- Siempre cifras, nunca datos de un estudiante. Se armaría con los mismos endpoints `tablero`.

## 8. Pendientes y decisiones para Carlos

- Crear el cliente OAuth de Google (tipo web) con los orígenes de Vercel y pasar el *client ID*.
- Definir quién es `admin` en cada servicio.
- Revisar con María José que el aviso de datos sirva también para la web.
- Las evidencias de calidad por archivo siguen en Telegram; en la web se registran por enlace.
