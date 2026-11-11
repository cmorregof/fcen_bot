"use client";

// Ficha del caso por pestañas. «Resumen» va primero y dice lo que hay que
// hacer ahora, con un solo botón principal; lo demás queda a un clic.

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { CANAL, claseEtapa, type Cuadro, type DecisionConsejo, type Detalle, type LadoCuadro, PRERREVISION } from "@/lib/actas";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";
import { Adjuntos } from "./Adjuntos";

type Pestana = "resumen" | "datos" | "comite" | "anexos" | "documentos" | "historial";

const NIVEL: Record<string, "error" | "info" | "exito"> = { error: "error", aviso: "info", info: "exito" };
const CIFRAS: Record<string, string> = {
  creditos_inscritos: "Créditos inscritos",
  creditos_tras_solicitud: "Créditos tras la solicitud",
  papa: "P.A.P.A.",
  porcentaje_avance: "Avance (%)",
  semana: "Semana del periodo",
};
const FIGURA: Record<string, string> = {
  equivalencia: "Cuadro de equivalencias",
  homologacion: "Cuadro de homologaciones",
  convalidacion: "Cuadro de convalidaciones",
};
const OPCIONES_PRERREVISION = [
  { valor: "procedente", accion: "prerrevisar_procedente", texto: "Procedente" },
  { valor: "incompleto", accion: "prerrevisar_incompleto", texto: "Incompleta" },
  { valor: "improcedente", accion: "prerrevisar_improcedente", texto: "Improcedente" },
];

type Hacer = (ruta: string, json: object | undefined, exito: string) => Promise<boolean>;

function celdas(l: LadoCuadro) {
  return [l.codigo, l.nombre, l.tipologia, l.creditos, l.nota].map((v, i) => <td key={i}>{v ?? ""}</td>);
}

// ---------------------------------------------------------------------------
// Resumen: lo de ahora
// ---------------------------------------------------------------------------

function Resumen({
  caso,
  administrativa,
  ocupado,
  hacer,
  bandeja,
  bajarOficio,
  ver,
}: {
  caso: Detalle;
  administrativa: boolean;
  ocupado: boolean;
  hacer: Hacer;
  bandeja: (archivar: boolean) => void;
  bajarOficio: () => void;
  ver: (p: Pestana) => void;
}) {
  const [eleccion, setEleccion] = useState("");
  const prerrevisables = OPCIONES_PRERREVISION.filter((o) => caso.acciones.includes(o.accion));
  const errores = caso.alertas.filter((a) => a.nivel === "error");
  const puedeRecomendar = caso.acciones.includes("recomendar");

  // Un solo botón principal: el de la tarea de ahora.
  let tarea: React.ReactNode = null;
  if (administrativa) {
    if (caso.archivado) {
      tarea = (
        <>
          <p>Este caso está archivado: no aparece en su bandeja. Su etapa no cambió.</p>
          <div className="botones">
            <button type="button" disabled={ocupado} onClick={() => bandeja(false)}>
              Devolver a la bandeja
            </button>
          </div>
        </>
      );
    } else if (!caso.extraccion) {
      tarea = (
        <div className="botones">
          <button type="button" disabled={ocupado} onClick={() => hacer("/procesar", undefined, "Caso leído.")}>
            {ocupado ? "Leyendo… (puede tardar un minuto)" : "Leer el caso"}
          </button>
        </div>
      );
    } else if (caso.etapa === "llegada" && prerrevisables.length > 0) {
      tarea = (
        <>
          <fieldset>
            <legend>Prerrevisión del programa</legend>
            {prerrevisables.map((o) => (
              <label key={o.valor} className="opcion">
                <input type="radio" name="pre" checked={eleccion === o.valor} onChange={() => setEleccion(o.valor)} />
                {o.texto}
              </label>
            ))}
          </fieldset>
          <div className="botones">
            <button
              type="button"
              disabled={ocupado || !eleccion}
              onClick={() => hacer("/prerrevision", { resultado: eleccion }, `Prerrevisión: ${PRERREVISION[eleccion]}.`)}
            >
              Guardar la prerrevisión
            </button>
          </div>
        </>
      );
    } else if (caso.acciones.includes("completar")) {
      tarea = (
        <div className="botones">
          <button type="button" disabled={ocupado} onClick={() => hacer("/completar", undefined, "El caso volvió a la llegada.")}>
            Ya llegó lo que faltaba
          </button>
        </div>
      );
    } else if (puedeRecomendar && caso.etapa !== "recomendada") {
      tarea = (
        <>
          <fieldset>
            <legend>¿Qué recomendó el comité en su sesión?</legend>
            <label className="opcion">
              <input type="radio" name="sentido" checked={eleccion === "aprobar"} onChange={() => setEleccion("aprobar")} />
              Recomendar aprobar
            </label>
            <label className="opcion">
              <input type="radio" name="sentido" checked={eleccion === "no_aprobar"} onChange={() => setEleccion("no_aprobar")} />
              Recomendar no aprobar
            </label>
          </fieldset>
          <div className="botones">
            <button
              type="button"
              disabled={ocupado || !eleccion}
              onClick={() =>
                hacer("/recomendacion", { sentido: eleccion }, `Se registró: ${eleccion === "aprobar" ? "Recomendar aprobar" : "Recomendar no aprobar"}.`)
              }
            >
              Registrar la recomendación
            </button>
          </div>
        </>
      );
    } else if (caso.acciones.includes("enviar_consejo")) {
      tarea = (
        <>
          <p>
            Recomendación registrada: <strong>{caso.sentido_texto}</strong>.
          </p>
          <div className="botones">
            <button type="button" disabled={ocupado} onClick={() => hacer("/enviar-consejo", undefined, "El caso quedó en el Consejo.")}>
              Enviar al Consejo
            </button>
          </div>
          <small>
            También puede firmar el oficio y el acta de todos los casos juntos en <Link href="/actas/documentos">Oficio y acta</Link>.
          </small>
        </>
      );
    } else if (caso.etapa === "en_consejo") {
      tarea = (
        <div className="botones">
          <Link href="/actas/consejo" className="boton">
            Registrar el acta del Consejo
          </Link>
        </div>
      );
    } else if (caso.oficio_consejo) {
      tarea = (
        <div className="botones">
          <button type="button" disabled={ocupado} onClick={bajarOficio}>
            Descargar el borrador del oficio (Word)
          </button>
        </div>
      );
    } else if (caso.archivable) {
      tarea = (
        <>
          <p>El caso terminó. Puede sacarlo de su bandeja: no se borra y lo encuentra en «Archivados».</p>
          <div className="botones">
            <button type="button" disabled={ocupado} onClick={() => bandeja(true)}>
              Archivar de la bandeja
            </button>
          </div>
        </>
      );
    }
  } else {
    tarea = (
      <div className="botones">
        <button type="button" onClick={() => ver("comite")}>
          Dejar mi concepto
        </button>
      </div>
    );
  }

  // Acciones secundarias: a un clic, en un menú.
  const secundarias: React.ReactNode[] = [];
  if (administrativa && !caso.archivado && caso.extraccion) {
    if (caso.etapa !== "llegada") {
      for (const o of prerrevisables) {
        secundarias.push(
          <button key={o.valor} type="button" className="enlace" disabled={ocupado} onClick={() => hacer("/prerrevision", { resultado: o.valor }, `Prerrevisión: ${o.texto}.`)}>
            Prerrevisión: {o.texto.toLowerCase()}
          </button>,
        );
      }
    }
    if (caso.etapa === "recomendada") {
      secundarias.push(
        <button key="cambiar" type="button" className="enlace" onClick={() => ver("comite")}>
          Cambiar la recomendación
        </button>,
      );
    }
    if (caso.acciones.includes("volver_al_comite")) {
      secundarias.push(
        <button key="volver" type="button" className="enlace" disabled={ocupado} onClick={() => hacer("/volver-al-comite", undefined, "El caso volvió al comité.")}>
          Volver al comité
        </button>,
      );
    }
    if (caso.archivable && caso.oficio_consejo) {
      secundarias.push(
        <button key="archivar" type="button" className="enlace" disabled={ocupado} onClick={() => bandeja(true)}>
          Archivar de la bandeja
        </button>,
      );
    }
  }

  return (
    <>
      <p>
        <span className={`estado ${claseEtapa(caso.etapa)}`}>{caso.etapa_texto}</span>
        {caso.archivado ? (
          <>
            {" "}
            <span className="estado archivado">Archivado</span>
          </>
        ) : null}
      </p>
      <dl className="datos-clave">
        <dt>Solicitud</dt>
        <dd>{caso.objeto ?? "sin leer"}</dd>
        <dt>Programa</dt>
        <dd>{caso.programa ?? "sin identificar"}</dd>
        {caso.prerrevision ? (
          <>
            <dt>Prerrevisión</dt>
            <dd>{PRERREVISION[caso.prerrevision] ?? caso.prerrevision}</dd>
          </>
        ) : null}
        {caso.sentido !== "pendiente" ? (
          <>
            <dt>Comité</dt>
            <dd>{caso.sentido_texto}</dd>
          </>
        ) : null}
        {caso.consejo ? (
          <>
            <dt>Consejo</dt>
            <dd>
              {caso.consejo.instancia_texto}: {caso.consejo.sentido_texto}
            </dd>
          </>
        ) : null}
      </dl>

      {caso.siguiente || tarea ? (
        <section className="ahora" aria-labelledby="ahora">
          <span className="rotulo">Lo que sigue</span>
          <h2 id="ahora">{caso.archivado ? "Caso archivado" : (caso.siguiente?.paso ?? "Nada pendiente")}</h2>
          {caso.siguiente && !caso.archivado ? <small>Responsable: {caso.siguiente.responsable}</small> : null}
          {tarea}
        </section>
      ) : null}

      {secundarias.length > 0 ? (
        <details className="menu">
          <summary>Más acciones</summary>
          <div className="opciones">{secundarias}</div>
        </details>
      ) : null}

      {administrativa && caso.extraccion && !caso.programa_clave ? (
        <>
          <label htmlFor="programa">
            ¿A qué programa pertenece?
            <span className="ayuda">Sin programa, el caso no entra al oficio del comité.</span>
          </label>
          <select id="programa" value="" disabled={ocupado} onChange={(e) => e.target.value && hacer("/programa", { programa: e.target.value }, "Programa guardado.")}>
            <option value="">Elija el programa</option>
            {caso.programas.map((p) => (
              <option key={p.clave} value={p.clave}>
                {p.nombre}
              </option>
            ))}
          </select>
        </>
      ) : null}

      {errores.length > 0 ? (
        <>
          <h2>Alertas</h2>
          {errores.map((a) => (
            <Mensaje key={a.mensaje} tipo="error">
              {a.mensaje}
            </Mensaje>
          ))}
        </>
      ) : null}
      {caso.extraccion ? (
        <p>
          <button type="button" className="enlace" onClick={() => ver("datos")}>
            Ver todos los datos del SIA{caso.alertas.length > errores.length ? ` y ${caso.alertas.length - errores.length} aviso(s) más` : ""}
          </button>
        </p>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Datos del SIA
// ---------------------------------------------------------------------------

function Datos({ caso, administrativa, ocupado, hacer }: { caso: Detalle; administrativa: boolean; ocupado: boolean; hacer: Hacer }) {
  const [correccion, setCorreccion] = useState("");
  const ext = caso.extraccion;
  if (!ext) return <Mensaje tipo="info">Este caso todavía no se ha leído.</Mensaje>;
  return (
    <>
      <dl className="datos-clave">
        <dt>Estudiante</dt>
        <dd>{caso.estudiante ?? "no aparece"}</dd>
        <dt>Documento</dt>
        <dd>{ext.documento ?? "no aparece"}</dd>
        <dt>Programa</dt>
        <dd>{caso.programa ?? "sin identificar"}</dd>
        <dt>Fecha</dt>
        <dd>{ext.fecha_solicitud ?? "no aparece"}</dd>
        <dt>Solicitud</dt>
        <dd>{caso.objeto}</dd>
        <dt>Justificación</dt>
        <dd>{ext.justificacion_breve}</dd>
        <dt>Recomienda</dt>
        <dd>{caso.ruta.recomienda}</dd>
        <dt>Decide</dt>
        <dd>{caso.ruta.decide}</dd>
      </dl>
      {caso.ruta.tramites.length > 1 ? (
        <ul>
          {caso.ruta.tramites.map((r) => (
            <li key={r.tipo}>
              {r.titulo}: decide {r.decide}; acto: {r.acto}
            </li>
          ))}
        </ul>
      ) : null}
      {caso.ruta.por_confirmar ? (
        <Mensaje tipo="info">La instancia que decide este trámite está por confirmar: lo confirma la Vicedecanatura Académica.</Mensaje>
      ) : null}
      {caso.ruta.fuera_de_facultad.map((instancia) => (
        <Mensaje key={instancia} tipo="info">
          Este trámite lo decide el {instancia}: revise el destinatario del oficio.
        </Mensaje>
      ))}

      {caso.cifras ? (
        <div className="tarjetas">
          {Object.entries(caso.cifras)
            .filter(([, v]) => v !== null)
            .map(([k, v]) => (
              <div key={k} className="tarjeta">
                <span className="cifra">{v}</span>
                {CIFRAS[k] ?? k}
              </div>
            ))}
        </div>
      ) : null}

      <h2>Alertas</h2>
      {caso.alertas.length === 0 ? <p>Sin alertas.</p> : null}
      {caso.alertas.map((a) => (
        <Mensaje key={a.mensaje} tipo={NIVEL[a.nivel] ?? "info"}>
          {a.mensaje}
        </Mensaje>
      ))}
      {ext.dudas && ext.dudas.length > 0 ? (
        <>
          <h3>Datos que conviene verificar</h3>
          <ul>
            {ext.dudas.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </>
      ) : null}

      {ext.asignaturas && ext.asignaturas.length > 0 ? (
        <details className="plegable">
          <summary>Asignaturas ({ext.asignaturas.length})</summary>
          <ul>
            {ext.asignaturas.map((a, i) => (
              <li key={i}>
                {a.accion}: {a.codigo ?? ""} {a.nombre} {a.grupo ? `(grupo ${a.grupo})` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {ext.proyecto ? (
        <details className="plegable">
          <summary>Proyecto de tesis o trabajo final</summary>
          <ul>
            <li>Título: {ext.proyecto.titulo ?? "no aparece"}</li>
            <li>Director(a): {ext.proyecto.director ?? "no aparece"}</li>
            {ext.proyecto.codirector ? <li>Codirector(a): {ext.proyecto.codirector}</li> : null}
            {ext.proyecto.linea ? <li>Línea: {ext.proyecto.linea}</li> : null}
          </ul>
        </details>
      ) : null}
      {ext.jurados && ext.jurados.length > 0 ? (
        <details className="plegable">
          <summary>Jurados de Trabajo de Grado ({ext.jurados.length})</summary>
          <p>
            <small>Se recomiendan tal como los trae la solicitud.</small>
          </p>
          <div className="tabla">
            <table>
              <thead>
                <tr>
                  <th>Nombre</th>
                  <th>Vinculación o institución</th>
                  <th>Correo</th>
                </tr>
              </thead>
              <tbody>
                {ext.jurados.map((j, i) => (
                  <tr key={i}>
                    <td>{j.nombre}</td>
                    <td>{j.vinculacion ?? ""}</td>
                    <td>{j.correo ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
      {(ext.equivalencias ?? [])
        .filter((c: Cuadro) => c.filas.length > 0)
        .map((c: Cuadro, n: number) => (
          <details key={n} className="plegable">
            <summary>
              {FIGURA[c.figura] ?? "Cuadro"} ({c.filas.length})
            </summary>
            <div className="tabla">
              <table>
                <thead>
                  <tr>
                    <th colSpan={5}>Cursada{c.origen ? ` en ${c.origen}` : ""}</th>
                    <th colSpan={5}>Se reconoce{c.destino ? ` en ${c.destino}` : ""}</th>
                  </tr>
                  <tr>
                    {["Código", "Asignatura", "Tipología", "Créditos", "Nota", "Código", "Asignatura", "Tipología", "Créditos", "Nota"].map((t, i) => (
                      <th key={i}>{t}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {c.filas.map((f, i) => (
                    <tr key={i}>
                      {celdas(f.origen)}
                      {celdas(f.destino)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ))}

      {administrativa ? (
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
              disabled={ocupado || !correccion.trim()}
              onClick={() => hacer("/correccion", { texto: correccion }, "Corrección aplicada.").then((ok) => ok && setCorreccion(""))}
            >
              Aplicar corrección
            </button>
          </div>
        </details>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Comité: recomendación, nota y conceptos
// ---------------------------------------------------------------------------

function Comite({ caso, administrativa, ocupado, hacer }: { caso: Detalle; administrativa: boolean; ocupado: boolean; hacer: Hacer }) {
  const [sentido, setSentido] = useState(caso.sentido);
  const [nota, setNota] = useState(caso.nota_comite ?? "");
  const [miembro, setMiembro] = useState("");
  const [concepto, setConcepto] = useState("");
  const puede = caso.acciones.includes("recomendar") || caso.etapa === "recomendada";
  return (
    <>
      <h2 style={{ marginTop: 0 }}>Recomendación del comité</h2>
      <p>
        Registrada: <strong>{caso.sentido_texto}</strong>
      </p>
      {administrativa && puede ? (
        <>
          <fieldset>
            <legend>Regístrela después de la sesión del comité</legend>
            {[
              ["aprobar", "Recomendar aprobar"],
              ["no_aprobar", "Recomendar no aprobar"],
              ["pendiente", "Pendiente"],
            ].map(([v, t]) => (
              <label key={v} className="opcion">
                <input type="radio" name="sentido-comite" checked={sentido === v} onChange={() => setSentido(v)} />
                {t}
              </label>
            ))}
          </fieldset>
          <div className="botones">
            <button
              type="button"
              disabled={ocupado || sentido === caso.sentido}
              onClick={() => hacer("/recomendacion", { sentido }, sentido === "pendiente" ? "El caso quedó pendiente." : "Recomendación registrada.")}
            >
              Guardar la recomendación
            </button>
          </div>
        </>
      ) : null}

      {administrativa ? (
        <details className="plegable" open={Boolean(caso.nota_comite)}>
          <summary>Nota del comité (va en el oficio)</summary>
          <label htmlFor="nota">Nota (opcional)</label>
          <textarea id="nota" value={nota} onChange={(e) => setNota(e.target.value)} />
          <div className="botones">
            <button type="button" className="secundario" disabled={ocupado || nota === (caso.nota_comite ?? "")} onClick={() => hacer("/nota", { texto: nota }, "Nota guardada.")}>
              Guardar nota
            </button>
          </div>
        </details>
      ) : null}

      <h2>Conceptos de los miembros</h2>
      <p>
        <small>Van al acta, no al oficio.</small>
      </p>
      {caso.conceptos.length === 0 ? <p>Aún no hay conceptos.</p> : null}
      <ul>
        {caso.conceptos.map((c) => (
          <li key={c.miembro}>
            <strong>{c.miembro}:</strong> {c.texto}
          </li>
        ))}
      </ul>
      <details className="plegable" open={!administrativa}>
        <summary>Agregar un concepto</summary>
        <label htmlFor="miembro">Miembro del comité</label>
        <select id="miembro" value={miembro} onChange={(e) => setMiembro(e.target.value)}>
          <option value="">Elija el miembro</option>
          {caso.miembros.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <label htmlFor="concepto">Concepto</label>
        <textarea id="concepto" value={concepto} onChange={(e) => setConcepto(e.target.value)} />
        <div className="botones">
          <button
            type="button"
            className={administrativa ? "secundario" : undefined}
            disabled={ocupado || !miembro || !concepto.trim()}
            onClick={() => hacer("/concepto", { miembro, texto: concepto }, "Concepto guardado.").then((ok) => ok && setConcepto(""))}
          >
            Guardar concepto
          </button>
        </div>
      </details>
    </>
  );
}

// ---------------------------------------------------------------------------
// Documentos e historial
// ---------------------------------------------------------------------------

function Documentos({ d, oficio, administrativa, ocupado, onOficio }: { d: DecisionConsejo | null; oficio: boolean; administrativa: boolean; ocupado: boolean; onOficio: () => void }) {
  return (
    <>
      <h2 style={{ marginTop: 0 }}>Decisión del Consejo</h2>
      {d ? (
        <div className="tarjeta">
          <strong>
            {d.instancia_texto}: {d.sentido_texto}
          </strong>{" "}
          («{d.texto_decision}»)
          <div>
            <small>
              Acta {d.acta_numero ?? "sin número"}
              {d.acta_fecha ? ` del ${d.acta_fecha}` : ""} · confirmó {d.confirmado_por}
            </small>
          </div>
          <details>
            <summary>Ver el fragmento del acta</summary>
            <blockquote style={{ margin: "0.5rem 0", whiteSpace: "pre-wrap" }}>
              <small>{d.fragmento}</small>
            </blockquote>
          </details>
        </div>
      ) : (
        <p>Pendiente de acta del Consejo.</p>
      )}
      {oficio ? (
        <>
          <div className="botones">
            <button type="button" className="secundario" disabled={ocupado} onClick={onOficio}>
              Borrador del oficio o resolución del Consejo (Word)
            </button>
          </div>
          <small>Lo que falta (número, modalidad de la sesión, motivación, firma) sale en amarillo.</small>
        </>
      ) : null}
      {administrativa ? (
        <>
          <h2>Oficio y acta del comité</h2>
          <p>
            Se arman con todos los casos del comité en <Link href="/actas/documentos">Oficio y acta</Link>.
          </p>
        </>
      ) : null}
    </>
  );
}

function Historial({ caso }: { caso: Detalle }) {
  return (
    <>
      <ol>
        {caso.linea.map((e, i) => (
          <li key={i}>
            <strong>{e.texto}</strong> → {e.hacia_texto}
            <div>
              <small>
                {e.fecha ?? "fecha no registrada"} · {e.rol}
                {e.persona ? ` (${e.persona})` : ""} · {CANAL[e.canal] ?? e.canal}
              </small>
            </div>
            {e.detalle ? (
              <div>
                <small>{e.detalle}</small>
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      <h2>Tiempos</h2>
      <ul>
        {caso.tramos.map((t) => (
          <li key={t.nombre}>
            {t.nombre}: {t.dias === null ? "—" : `${t.dias} días`}
          </li>
        ))}
      </ul>
    </>
  );
}

// ---------------------------------------------------------------------------
// Ficha
// ---------------------------------------------------------------------------

function Ficha() {
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id");
  const pestana = (params.get("ver") as Pestana | null) ?? "resumen";
  const { token, tieneRol } = useSesion();
  const t = token("actas");
  const administrativa = tieneRol("actas", "administrativa");
  const [caso, setCaso] = useState<Detalle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(async () => {
    try {
      setCaso(await llamar<Detalle>("actas", `/actas/casos/${id}`, { token: t }));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id, t]);

  useEffect(() => {
    if (t && id) cargar();
  }, [t, id, cargar]);

  const ver = (p: Pestana) => {
    setAviso(null);
    router.replace(`/actas/caso?id=${id}${p === "resumen" ? "" : `&ver=${p}`}`, { scroll: false });
  };

  const hacer: Hacer = async (ruta, json, exito) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    try {
      setCaso(await llamar<Detalle>("actas", `/actas/casos/${id}${ruta}`, { token: t, json, metodo: "POST" }));
      setAviso(exito);
      setOcupado(false);
      return true;
    } catch (e) {
      setError((e as Error).message);
      setOcupado(false);
      return false;
    }
  };

  const bandeja = async (archivar: boolean) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    try {
      await llamar("actas", `/actas/casos/${archivar ? "archivar" : "desarchivar"}`, { token: t, json: { ids: [Number(id)] }, metodo: "POST" });
      await cargar();
      setAviso(archivar ? "Caso archivado: ya no aparece en su bandeja. Lo encuentra en «Archivados»." : "El caso volvió a su bandeja.");
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(false);
  };

  const bajarOficio = async () => {
    setOcupado(true);
    setError(null);
    try {
      const blob = await llamar<Blob>("actas", `/actas/casos/${id}/oficio-consejo`, { token: t });
      guardarArchivo(blob, `Borrador_Consejo_caso_${id}.docx`);
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(false);
  };

  const pestanas: { clave: Pestana; texto: string; cuenta?: number }[] = [
    { clave: "resumen", texto: "Resumen" },
    { clave: "datos", texto: "Datos del SIA" },
    { clave: "comite", texto: "Comité" },
    { clave: "anexos", texto: "Anexos", cuenta: caso?.adjuntos.length },
    { clave: "documentos", texto: "Documentos" },
    { clave: "historial", texto: "Línea de tiempo" },
  ];

  const teclas = (e: React.KeyboardEvent, i: number) => {
    const n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (n === null) return;
    const destino = pestanas[(n + pestanas.length) % pestanas.length].clave;
    ver(destino);
    document.getElementById(`pestana-${destino}`)?.focus();
  };

  return (
    <Pantalla
      titulo={caso ? (caso.estudiante ?? `Caso #${caso.id}`) : "Ficha del caso"}
      servicio="actas"
      roles={["administrativa", "comite"]}
      hace={
        administrativa
          ? [
              "«Resumen» dice lo que hay que hacer ahora; el resto de la ficha está en las pestañas.",
              "Muestra los datos leídos del correo y del SIA, con alertas según la norma.",
              "Registra la recomendación del comité, la nota y los conceptos de sus miembros.",
              "Con la decisión del Consejo confirmada, arma el borrador del oficio de notificación para la Secretaría.",
              "Archiva el caso terminado para sacarlo de su bandeja, sin borrarlo.",
            ]
          : ["Muestra la ficha del caso y le permite dejar su concepto."]
      }
      noHace={[
        "No decide el caso: el comité recomienda y decide el Consejo de Facultad, el de Sede o el Superior, según el trámite.",
        "Las alertas no reemplazan la lectura de la norma.",
      ]}
    >
      <p>
        <Link href="/actas">← Volver a los casos</Link>
        {caso ? <small> · Caso #{caso.id}</small> : null}
      </p>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso ? <Mensaje tipo="exito">{aviso}</Mensaje> : null}
      {!caso && !error ? <p>Cargando…</p> : null}
      {caso ? (
        <>
          <div className="pestanas" role="tablist" aria-label="Secciones del caso">
            {pestanas.map((p, i) => (
              <button
                key={p.clave}
                id={`pestana-${p.clave}`}
                type="button"
                role="tab"
                aria-selected={pestana === p.clave}
                aria-controls="panel-caso"
                tabIndex={pestana === p.clave ? 0 : -1}
                onClick={() => ver(p.clave)}
                onKeyDown={(e) => teclas(e, i)}
              >
                {p.texto}
                {p.cuenta ? <span className="cuenta"> ({p.cuenta})</span> : null}
              </button>
            ))}
          </div>
          <div id="panel-caso" role="tabpanel" aria-labelledby={`pestana-${pestana}`}>
            {pestana === "resumen" ? (
              <Resumen caso={caso} administrativa={administrativa} ocupado={ocupado} hacer={hacer} bandeja={bandeja} bajarOficio={bajarOficio} ver={ver} />
            ) : null}
            {pestana === "datos" ? <Datos caso={caso} administrativa={administrativa} ocupado={ocupado} hacer={hacer} /> : null}
            {pestana === "comite" ? <Comite key={caso.sentido} caso={caso} administrativa={administrativa} ocupado={ocupado} hacer={hacer} /> : null}
            {pestana === "anexos" ? (
              <Adjuntos<Detalle> casoId={caso.id} adjuntos={caso.adjuntos} leido={caso.extraccion !== null} editable={administrativa} token={t} onFicha={setCaso} />
            ) : null}
            {pestana === "documentos" ? (
              <Documentos d={caso.consejo} oficio={caso.oficio_consejo} administrativa={administrativa} ocupado={ocupado} onOficio={bajarOficio} />
            ) : null}
            {pestana === "historial" ? <Historial caso={caso} /> : null}
          </div>
        </>
      ) : null}
    </Pantalla>
  );
}

export default function PaginaFicha() {
  return (
    <Suspense fallback={<p>Cargando…</p>}>
      <Ficha />
    </Suspense>
  );
}
