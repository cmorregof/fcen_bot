"use client";

// Asistente para preparar un caso nuevo: una cosa por pantalla.
// 1) correo y anexos; 2) revisar lo que leyó MemorIA; 3) prerrevisión; 4) listo.
// El paso y el caso van en la dirección (?id=…&paso=…): si recarga, sigue donde iba.

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { type Detalle, PRERREVISION } from "@/lib/actas";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";
import { ACEPTA, Adjuntos } from "../caso/Adjuntos";

const PASOS = ["Correo y anexos", "Revisar los datos", "Prerrevisión", "Listo para el comité"];

const NIVEL: Record<string, "error" | "info" | "exito"> = { error: "error", aviso: "info", info: "exito" };

const OPCIONES_PRERREVISION: { valor: string; accion: string; texto: string; ayuda: string }[] = [
  { valor: "procedente", accion: "prerrevisar_procedente", texto: "Procedente", ayuda: "La solicitud está completa y pasa al comité." },
  { valor: "incompleto", accion: "prerrevisar_incompleto", texto: "Incompleta", ayuda: "Falta un documento o un dato. El caso espera a que llegue." },
  { valor: "improcedente", accion: "prerrevisar_improcedente", texto: "Improcedente", ayuda: "La solicitud no procede según la norma. Queda registrada." },
];

function Indicador({ paso }: { paso: number }) {
  return (
    <ol className="asistente-pasos" aria-label={`Paso ${paso} de ${PASOS.length}`}>
      {PASOS.map((p, i) => (
        <li key={p} className={i + 1 < paso ? "hecho" : undefined} aria-current={i + 1 === paso ? "step" : undefined}>
          {p}
        </li>
      ))}
    </ol>
  );
}

function Asistente() {
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id");
  const paso = Math.min(4, Math.max(1, Number(params.get("paso")) || 1));
  const { token } = useSesion();
  const t = token("actas");
  const [caso, setCaso] = useState<Detalle | null>(null);
  const [texto, setTexto] = useState("");
  const [archivos, setArchivos] = useState<FileList | null>(null);
  const [correccion, setCorreccion] = useState("");
  const [prerrevision, setPrerrevision] = useState("");
  const [notaPre, setNotaPre] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const titulo = useRef<HTMLHeadingElement>(null);

  const ir = useCallback(
    (n: number, casoId: string | number | null = id) => {
      setError(null);
      setAviso(null);
      router.push(`/actas/nuevo?${casoId ? `id=${casoId}&` : ""}paso=${n}`);
    },
    [id, router],
  );

  useEffect(() => {
    if (!t || !id) return;
    llamar<Detalle>("actas", `/actas/casos/${id}`, { token: t })
      .then((d) => {
        setCaso(d);
        if (d.prerrevision) setPrerrevision(d.prerrevision);
      })
      .catch((e: Error) => setError(e.message));
  }, [t, id]);

  // Al cambiar de paso, el foco va al título del paso (lectores de pantalla y teclado).
  useEffect(() => {
    titulo.current?.focus();
  }, [paso]);

  const accion = async (ruta: string, json: object | undefined, exito: string | null, nombre = ruta) => {
    setOcupado(nombre);
    setError(null);
    setAviso(null);
    try {
      const d = await llamar<Detalle>("actas", `/actas/casos/${id}${ruta}`, { token: t, json, metodo: "POST" });
      setCaso(d);
      if (exito) setAviso(exito);
      setOcupado(null);
      return true;
    } catch (e) {
      setError((e as Error).message);
      setOcupado(null);
      return false;
    }
  };

  const crear = async () => {
    setError(null);
    const form = new FormData();
    form.append("texto", texto);
    for (const f of Array.from(archivos ?? [])) form.append("archivos", f);
    try {
      setOcupado("guardando");
      const { id: nuevo } = await llamar<{ id: number }>("actas", "/actas/casos", { token: t, form });
      setOcupado("leyendo");
      try {
        await llamar("actas", `/actas/casos/${nuevo}/procesar`, { token: t, metodo: "POST" });
      } catch {
        /* el paso 2 muestra que no se leyó y permite reintentar */
      }
      setOcupado(null);
      ir(2, nuevo);
    } catch (e) {
      setError((e as Error).message);
      setOcupado(null);
    }
  };

  const prerrevisables = OPCIONES_PRERREVISION.filter((o) => caso?.acciones.includes(o.accion));
  const ext = caso?.extraccion;

  let cuerpo: React.ReactNode = null;
  let siguiente: React.ReactNode = null;
  let atras: React.ReactNode = (
    <Link href="/actas" className="boton secundario">
      Cancelar
    </Link>
  );

  if (paso === 1 && !id) {
    cuerpo = (
      <>
        <label htmlFor="correo">
          Pegue aquí el correo del estudiante
          <span className="ayuda">Tal como llegó: con la fecha, el nombre y el cuerpo del mensaje.</span>
        </label>
        <textarea id="correo" value={texto} onChange={(e) => setTexto(e.target.value)} />
        <label htmlFor="pantallazos">
          Adjunte los pantallazos del SIA y los archivos del estudiante
          <span className="ayuda">PDF, Word o imágenes. Hasta 20 archivos. Puede agregar más después.</span>
        </label>
        <input id="pantallazos" type="file" accept={ACEPTA} multiple onChange={(e) => setArchivos(e.target.files)} />
        {ocupado === "leyendo" ? <Mensaje tipo="info">MemorIA está leyendo el caso. Puede tardar un minuto.</Mensaje> : null}
      </>
    );
    siguiente = (
      <button type="button" disabled={ocupado !== null || (!texto.trim() && !archivos?.length)} onClick={crear}>
        {ocupado === "guardando" ? "Guardando…" : ocupado === "leyendo" ? "Leyendo el caso…" : "Siguiente: leer el caso"}
      </button>
    );
  } else if (paso === 1 && caso) {
    cuerpo = (
      <>
        <Mensaje tipo="exito">El correo ya quedó guardado en el caso #{caso.id}. Aquí puede agregar o quitar archivos.</Mensaje>
        <Adjuntos<Detalle> casoId={caso.id} adjuntos={caso.adjuntos} leido={caso.extraccion !== null} editable token={t} onFicha={setCaso} />
      </>
    );
    siguiente = (
      <button type="button" onClick={() => ir(2)}>
        Siguiente
      </button>
    );
  } else if (paso === 2 && caso) {
    atras = (
      <button type="button" className="secundario" onClick={() => ir(1)}>
        Atrás
      </button>
    );
    if (!ext) {
      cuerpo = <Mensaje tipo="info">MemorIA todavía no pudo leer este caso. Intente de nuevo; si sigue fallando, revise los archivos en el paso anterior.</Mensaje>;
      siguiente = (
        <button type="button" disabled={ocupado !== null} onClick={() => accion("/procesar", undefined, "Caso leído.")}>
          {ocupado ? "Leyendo… (puede tardar un minuto)" : "Leer el caso"}
        </button>
      );
    } else {
      const errores = caso.alertas.filter((a) => a.nivel === "error");
      const otras = caso.alertas.filter((a) => a.nivel !== "error");
      cuerpo = (
        <>
          <p>Compare con el correo y los pantallazos. Si algo está mal, corríjalo abajo.</p>
          <dl className="datos-clave">
            <dt>Estudiante</dt>
            <dd>{caso.estudiante ?? "no aparece"}</dd>
            <dt>Documento</dt>
            <dd>{ext.documento ?? "no aparece"}</dd>
            <dt>Solicitud</dt>
            <dd>{caso.objeto ?? "no aparece"}</dd>
            <dt>Programa</dt>
            <dd>{caso.programa ?? "sin identificar"}</dd>
            <dt>Fecha</dt>
            <dd>{ext.fecha_solicitud ?? "no aparece"}</dd>
            <dt>Decide</dt>
            <dd>{caso.ruta.decide}</dd>
          </dl>
          {!caso.programa_clave ? (
            <>
              <label htmlFor="programa">
                ¿A qué programa pertenece?
                <span className="ayuda">MemorIA no lo identificó. Sin programa, el caso no entra al oficio.</span>
              </label>
              <select
                id="programa"
                value=""
                disabled={ocupado !== null}
                onChange={(e) => e.target.value && accion("/programa", { programa: e.target.value }, "Programa guardado.")}
              >
                <option value="">Elija el programa</option>
                {caso.programas.map((p) => (
                  <option key={p.clave} value={p.clave}>
                    {p.nombre}
                  </option>
                ))}
              </select>
            </>
          ) : null}
          {errores.length > 0 ? <h2>Alertas</h2> : null}
          {errores.map((a) => (
            <Mensaje key={a.mensaje} tipo="error">
              {a.mensaje}
            </Mensaje>
          ))}
          {otras.length > 0 || (ext.dudas && ext.dudas.length > 0) ? (
            <details className="plegable">
              <summary>Otros avisos y datos por verificar ({otras.length + (ext.dudas?.length ?? 0)})</summary>
              {otras.map((a) => (
                <Mensaje key={a.mensaje} tipo={NIVEL[a.nivel] ?? "info"}>
                  {a.mensaje}
                </Mensaje>
              ))}
              {ext.dudas && ext.dudas.length > 0 ? (
                <ul>
                  {ext.dudas.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              ) : null}
            </details>
          ) : null}
          <details className="plegable">
            <summary>¿Algún dato está mal?</summary>
            <label htmlFor="correccion">
              Escriba qué está mal y cuál es el dato correcto
              <span className="ayuda">Ejemplo: el documento es 1000000001, no 1000000000.</span>
            </label>
            <textarea id="correccion" value={correccion} onChange={(e) => setCorreccion(e.target.value)} />
            <div className="botones">
              <button
                type="button"
                className="secundario"
                disabled={ocupado !== null || !correccion.trim()}
                onClick={() => accion("/correccion", { texto: correccion }, "Corrección aplicada.").then((ok) => ok && setCorreccion(""))}
              >
                {ocupado === "/correccion" ? "Corrigiendo…" : "Aplicar corrección"}
              </button>
            </div>
          </details>
        </>
      );
      siguiente = (
        <button type="button" disabled={ocupado !== null} onClick={() => ir(3)}>
          Siguiente: prerrevisión
        </button>
      );
    }
  } else if (paso === 3 && caso) {
    atras = (
      <button type="button" className="secundario" onClick={() => ir(2)}>
        Atrás
      </button>
    );
    if (prerrevisables.length === 0) {
      cuerpo = (
        <Mensaje tipo="info">
          {caso.prerrevision
            ? `La prerrevisión ya quedó: ${PRERREVISION[caso.prerrevision] ?? caso.prerrevision}.`
            : "Este caso no necesita prerrevisión en su etapa actual."}
        </Mensaje>
      );
      siguiente = (
        <button type="button" onClick={() => ir(4)}>
          Siguiente
        </button>
      );
    } else {
      cuerpo = (
        <>
          <fieldset>
            <legend>¿Cómo encuentra la solicitud?</legend>
            {prerrevisables.map((o) => (
              <label key={o.valor} className="opcion">
                <input type="radio" name="prerrevision" value={o.valor} checked={prerrevision === o.valor} onChange={() => setPrerrevision(o.valor)} />
                <span>
                  <strong>{o.texto}</strong>
                  <span className="ayuda">{o.ayuda}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <label htmlFor="nota-pre">
            Nota (opcional)
            <span className="ayuda">Por ejemplo, qué documento falta. Queda en la línea del caso.</span>
          </label>
          <textarea id="nota-pre" value={notaPre} onChange={(e) => setNotaPre(e.target.value)} />
          <div className="botones">
            <button type="button" className="enlace" onClick={() => ir(4)}>
              Hacerla después
            </button>
          </div>
        </>
      );
      siguiente = (
        <button
          type="button"
          disabled={ocupado !== null || !prerrevision}
          onClick={async () => {
            const ok = await accion("/prerrevision", { resultado: prerrevision, nota: notaPre.trim() }, null);
            if (ok) ir(4);
          }}
        >
          {ocupado ? "Guardando…" : "Guardar y seguir"}
        </button>
      );
    }
  } else if (paso === 4 && caso) {
    atras = (
      <button type="button" className="secundario" onClick={() => ir(3)}>
        Atrás
      </button>
    );
    cuerpo = (
      <>
        <Mensaje tipo="exito">
          El caso #{caso.id}
          {caso.estudiante ? ` de ${caso.estudiante}` : ""} quedó en la etapa «{caso.etapa_texto}».
        </Mensaje>
        {caso.siguiente ? (
          <div className="ahora">
            <span className="rotulo">Lo que sigue</span>
            <h2>{caso.siguiente.paso}</h2>
            <small>Responsable: {caso.siguiente.responsable}</small>
          </div>
        ) : null}
        <p>
          <Link href="/actas/nuevo">Preparar otro caso</Link> · <Link href="/actas">Volver a los casos</Link>
        </p>
      </>
    );
    siguiente = (
      <Link href={`/actas/caso?id=${caso.id}`} className="boton">
        Abrir la ficha del caso
      </Link>
    );
  } else if (id && !caso && !error) {
    cuerpo = <p>Cargando el caso…</p>;
    siguiente = null;
  }

  return (
    <Pantalla
      titulo="Preparar un caso nuevo"
      servicio="actas"
      roles={["administrativa"]}
      hace={[
        "Guía la preparación de un caso en cuatro pasos: correo y anexos, revisión de los datos, prerrevisión y listo.",
        "MemorIA lee el correo y los pantallazos y arma la ficha con alertas según la norma.",
      ]}
      noHace={[
        "No decide: la prerrevisión la hace usted, el comité recomienda y decide el Consejo.",
        "No envía nada al estudiante.",
      ]}
    >
      <Indicador paso={paso} />
      <h2 ref={titulo} tabIndex={-1} style={{ marginTop: 0 }}>
        Paso {paso} de {PASOS.length}: {PASOS[paso - 1]}
      </h2>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso ? <Mensaje tipo="exito">{aviso}</Mensaje> : null}
      {cuerpo}
      <div className="navegacion">
        {atras}
        {siguiente}
      </div>
    </Pantalla>
  );
}

export default function PaginaNuevo() {
  return (
    <Suspense fallback={<p>Cargando…</p>}>
      <Asistente />
    </Suspense>
  );
}
