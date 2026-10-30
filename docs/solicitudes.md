# Rutas de decisión y umbrales: `config/solicitudes.yaml`

**Responsable: Vicedecanatura Académica.** El equipo técnico revisa el cambio y
lo despliega, pero no decide los valores.

El comité asesor **nunca decide**: solo recomienda APROBAR o NO APROBAR. Decide
el Consejo de Facultad, el Consejo de Sede o el Consejo Superior, según el
trámite. Este archivo dice cuál es cuál y guarda los umbrales que usan las
alertas del bot (carga mínima, semanas límite, créditos para el Trabajo de
Grado, mínimo de jurados). Se edita sin tocar el código.

## Dónde se ve

- **Ficha de Telegram:** «Recomienda: comité asesor · Decide: Consejo de
  Facultad». Si la instancia está por confirmar, lo dice.
- **Web, ficha del caso:** sección «Quién decide», con el acto y la nota de
  cada trámite cuando el caso trae varios.
- **Oficio:** la redacción no cambia. Si el trámite lo decide una instancia
  distinta del Consejo de Facultad, aparece una nota en amarillo: «Este trámite
  lo decide el Consejo de Sede: revise el destinatario».
- **Alertas:** los umbrales salen del archivo; cambiar un valor cambia la
  alerta.

## Cómo editar

1. Abra `config/solicitudes.yaml` (en GitHub: botón del lápiz).
2. Cambie solo los valores. Las claves (`carga_minima`, `decide`, `valor`…) no
   se renombran.
3. Guarde el cambio en una rama y pida la revisión (pull request).
4. Al desplegar, el servicio valida el archivo. **Si tiene un error, el servicio
   de actas no arranca** y el registro dice exactamente qué línea revisar. Es a
   propósito: es mejor no arrancar que alertar con un umbral equivocado.

### Quién decide un trámite

```yaml
solicitudes:
  cancelacion:
    recomienda: comite_asesor    # siempre el comité asesor
    decide: por_confirmar        # consejo_facultad | consejo_sede | consejo_superior | por_confirmar
    acto: por_confirmar          # el acto que se expide, en texto (p. ej. «Resolución»)
    normas: []                   # normas transcritas en app/normativa/base.py
    nota: Lo confirma la Vicedecanatura Académica.
```

- `decide` no admite `comite_asesor`: el comité no decide.
- Están todos los tipos de solicitud del bot. Si falta uno, el servicio no
  arranca.
- `normas` usa los nombres de `app/normativa/base.py` (por ejemplo
  `ACUERDO_008_ART_10`). Aquí no se escribe el texto de una norma: las normas
  se citan literalmente, así que si hace falta una nueva, primero el equipo
  técnico transcribe su texto allí, a partir del PDF.

### Un umbral

```yaml
umbrales:
  carga_minima:
    valor: 10
    norma: ACUERDO_008_ART_10    # o «fuente:» si no hay texto transcrito
```

Cada umbral necesita `norma` o `fuente`, para que la alerta diga de dónde sale.
Si un umbral cambia porque cambió la norma (por ejemplo, si el Acuerdo 230 de
2026 deja la carga mínima en 9), hay que actualizar también el texto literal de
la norma en `app/normativa/base.py`: si no, la alerta dirá 9 y la norma citada
seguirá diciendo diez.

| Umbral | Valor actual | De dónde sale |
|---|---|---|
| `carga_minima` | 10 | Acuerdo 008 de 2008, art. 10 |
| `semana_limite_asignaturas` | 10 | Acuerdo 027 de 2024, art. 1 |
| `semana_limite_tdg_actividades` | 13 | Acuerdo 027 de 2024, art. 1 |
| `semana_limite_traslado` | 7 | Acuerdo 089 de 2014, art. 2 (sin transcribir) |
| `jurados_minimo` | 6 | Instrucción del Consejo de Facultad, 28-oct-2026 (no es norma) |
| `tdg_creditos_disciplinares.ing_fisica` | 46 | Res. CFCEN-060 de 2008, art. 5 |

`jurados_minimo` también se puede fijar con la variable de entorno
`JURADOS_MINIMO`; si está definida, gana al archivo.

Para usar otro archivo (por ejemplo, en pruebas), defina `SOLICITUDES_PATH`.

### Plazos (indicador «fuera de plazo»)

```yaml
plazos:
  comite:            # de la solicitud a la recomendación del comité
    dias: 15
    fuente: <norma, circular o instrucción que fija el plazo>
  consejo: null      # de la recomendación a la decisión del Consejo
```

Son días calendario y cada plazo necesita `fuente`. Hoy los dos están en
`null`: ninguna norma transcrita fija esos plazos, y el indicador dice «sin
plazo configurado» hasta que la Vicedecanatura los defina. Ver
`docs/indicadores.md`.

## Pendiente de confirmar

Solo se llenó lo que dicen las normas transcritas: decide el Consejo de
Facultad la carga mínima (Acuerdo 008 de 2008, art. 10), la inscripción
extemporánea (Acuerdo 350 de 2021, arts. 1 y 2) y la PAE (procedimiento
U.PR.05.007.008). Todo lo demás, y el acto que se expide en cada trámite, está
`por_confirmar` hasta que lo confirme la Vicedecanatura Académica.
