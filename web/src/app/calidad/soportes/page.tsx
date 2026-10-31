"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { ErrorApi, guardarArchivo, llamar } from "@/lib/api";
import { ResumenPlan } from "@/lib/calidad";
import { useSesion } from "@/lib/sesion";

type Estimacion = {
  archivos: number;
  acciones: number;
  al_modelo: number;
  en_cache: number;
  generales: number;
  acciones_sin_soportes: string[];
  carpetas_sin_accion: string[];
  costo_usd: number;
  tope_usd: number;
  excede_tope: string;
};

type Paso = { clave: string; titulo: string; hechos: number; total: number; estado: string };

type Resumen = {
  archivos: number;
  acciones: number;
  minutos: number;
  costo_usd: number;
  veredictos: Record<string, number>;
  sin_descripcion: number;
  alertas: number;
  sugerencias: number;
  detenida: string;
};

type Organizacion = {
  archivos_con_observaciones: number;
  acciones_con_observaciones: string[];
};

type Estado = {
  estado: "vacio" | "cargado" | "corriendo" | "terminado" | "fallido" | "interrumpido";
  carga_id?: string;
  programa?: string;
  estimacion?: Estimacion;
  organizacion?: Organizacion;
  pasos?: Paso[];
  costo_usd?: number;
  resumen?: Resumen | null;
  error?: string;
  soportes_presentes: boolean;
  descargas: string[];
  en_cache: number;
  tope_usd: number;
  max_mb: number;
  retencion_dias: number;
  revisor_activo: boolean;
};

const DESCARGAS: { clave: string; nombre: string; texto: string }[] = [
  { clave: "inventario", nombre: "inventario_soportes.xlsx", texto: "Inventario de soportes (Excel)" },
  { clave: "cruce", nombre: "cruce_acciones.xlsx", texto: "Cruce de acciones y soportes (Excel)" },
  { clave: "borrador", nombre: "borrador_cierre.docx", texto: "Borrador del cierre (Word)" },
  { clave: "organizacion", nombre: "organizacion_evidencias.xlsx", texto: "Carpetas y nombres de las evidencias (Excel)" },
  { clave: "indice", nombre: "indice_electronico.xlsx", texto: "Índice electrónico del expediente (Excel)" },
];

const usd = (n: number) => `${n.toFixed(2).replace(".", ",")} USD`;

function AvisoPropuesta() {
  return (
    <Mensaje tipo="info">
      <strong>Todo lo que entrega esta revisión es una propuesta.</strong> Los veredictos y los porcentajes de avance
      los revisa la oficina de calidad; el Comité Asesor recomienda aprobar o no aprobar el cierre y el Consejo de
      Facultad decide. Las citas marcadas con ⚠ no pasaron la verificación y no cuentan como evidencia.
    </Mensaje>
  );
}

function Titulo({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <h2>
      <span className="paso-numero">{n}</span>
      {children}
    </h2>
  );
}

export default function RevisionSoportes() {
  const { token } = useSesion();
  const t = token("calidad");
  const [estado, setEstado] = useState<Estado | null>(null);
  const [apagado, setApagado] = useState<string | null>(null);
  const [programas, setProgramas] = useState<ResumenPlan[]>([]);
  const [programa, setPrograma] = useState("");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [acepto, setAcepto] = useState(false);
  const [borrarCache, setBorrarCache] = useState(false);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Dónde mostrar el error: junto al botón que lo causó.
  const [errorDe, setErrorDe] = useState<string | null>(null);

  const consultar = useCallback(async () => {
    if (!t) return;
    try {
      setEstado(await llamar<Estado>("calidad", "/calidad/revisor", { token: t }));
      setApagado(null);
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === 403) setApagado(e.message);
      else {
        setError((e as Error).message);
        setErrorDe(null);
      }
    }
  }, [t]);

  useEffect(() => {
    consultar();
    if (!t) return;
    llamar<{ programas: ResumenPlan[] }>("calidad", "/calidad/programas", { token: t })
      .then((r) => setProgramas(r.programas))
      .catch(() => undefined);
  }, [consultar, t]);

  // Mientras corre, se pregunta cada 3 segundos en qué va.
  const corriendo = estado?.estado === "corriendo";
  useEffect(() => {
    if (!corriendo) return;
    const intervalo = setInterval(consultar, 3000);
    return () => clearInterval(intervalo);
  }, [corriendo, consultar]);

  const accion = async (nombre: string, hacer: () => Promise<Estado>) => {
    setOcupado(nombre);
    setError(null);
    try {
      setEstado(await hacer());
    } catch (e) {
      setError((e as Error).message);
      setErrorDe(nombre);
    }
    setOcupado(null);
  };

  const subir = () =>
    accion("subir", () =>
      llamar<Estado>("calidad", `/calidad/revisor/soportes?programa=${encodeURIComponent(programa)}`, {
        token: t,
        archivo: archivo ?? undefined,
      }),
    ).then(() => setAcepto(false));

  const correr = () =>
    accion("correr", () =>
      llamar<Estado>("calidad", "/calidad/revisor/correr", {
        token: t,
        // La carga y el costo que la persona vio: si cambiaron, el servidor no corre.
        json: { confirmo_costo: true, carga_id: estado?.carga_id, costo_usd: estado?.estimacion?.costo_usd },
      }),
    ).then(() => {
      setAcepto(false);
      consultar();
    });

  const borrar = () => {
    const texto = borrarCache
      ? "¿Borrar los soportes, los resultados y las descripciones guardadas? La próxima revisión las volverá a pagar."
      : "¿Borrar los soportes y los resultados de esta revisión?";
    if (!window.confirm(texto)) return;
    accion("borrar", () =>
      llamar<Estado>("calidad", `/calidad/revisor${borrarCache ? "?cache=true" : ""}`, { token: t, metodo: "DELETE" }),
    ).then(() => {
      setArchivo(null);
      setAcepto(false);
      setBorrarCache(false);
    });
  };

  const descargar = async (clave: string, nombre: string) => {
    setError(null);
    try {
      guardarArchivo(await llamar<Blob>("calidad", `/calidad/revisor/descargar/${clave}`, { token: t }), nombre);
    } catch (e) {
      setError((e as Error).message);
      setErrorDe("descargar");
    }
  };

  const est = estado?.estimacion;
  const org = estado?.organizacion;
  const hayAlgo = estado && (estado.estado !== "vacio" || estado.soportes_presentes || estado.descargas.length > 0 || estado.en_cache > 0);
  const puedeCorrer = estado && estado.estado === "cargado" && estado.soportes_presentes;

  return (
    <Pantalla
      titulo="Revisión de soportes"
      servicio="calidad"
      roles={["calidad", "admin"]}
      hace={[
        "Revisa las carpetas y los nombres de las evidencias según el instructivo de la Dirección Académica y prellena el índice electrónico del expediente, sin costo.",
        "Con la revisión con el modelo encendida: describe cada archivo y los cruza con las acciones del plan.",
        "Antes de empezar le dice cuántos archivos hay y cuánto costará, y solo empieza si usted confirma.",
        "Entrega tres archivos para revisar: inventario, cruce y borrador del cierre.",
      ]}
      noHace={[
        "No decide si una acción se cumplió: propone, y usted revisa.",
        "No cambia el % de avance del plan.",
        "No guarda los soportes: se borran al terminar. Los resultados se borran con el botón «Borrar soportes» o solos, pasado un tiempo.",
      ]}
    >
      {apagado ? (
        <Mensaje tipo="info">
          <strong>Pendiente del aval de tratamiento de datos.</strong> Los soportes traen nombres y listados de
          personas; esta herramienta se activará cuando la Universidad dé el aval. Mientras tanto no se puede subir
          nada.
        </Mensaje>
      ) : null}
      {error && !["subir", "correr", "borrar"].includes(errorDe ?? "") ? <Mensaje tipo="error">{error}</Mensaje> : null}

      {estado && !apagado ? (
        <>
          {estado.revisor_activo ? <AvisoPropuesta /> : null}

          {!corriendo ? (
            <>
              <Titulo n={1}>Elija el programa</Titulo>
              <label htmlFor="programa">
                Programa
                <span className="ayuda">Debe tener el plan cargado en «Cargar el plan».</span>
              </label>
              <select id="programa" value={programa} onChange={(e) => setPrograma(e.target.value)}>
                <option value="">— Elija un programa —</option>
                {programas.map((p) => (
                  <option key={p.programa} value={p.programa}>
                    {p.programa} ({p.acciones} acciones)
                  </option>
                ))}
              </select>

              <Titulo n={2}>Suba el zip de soportes</Titulo>
              <label htmlFor="zip">
                Archivo .zip con los soportes
                <span className="ayuda">
                  Descargue de Drive la carpeta «Soportes de acciones» del programa: una carpeta por acción («Acción 1.1»,
                  «Acción 1.2»…) con «Producto final» y «Soportes de producto final». Máximo {estado.max_mb}{" "}
                  MB. Subir un zip nuevo reemplaza el anterior.
                </span>
              </label>
              <input id="zip" type="file" accept=".zip" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
              <div className="botones">
                <button type="button" disabled={!programa || !archivo || ocupado !== null} onClick={subir}>
                  {ocupado === "subir"
                    ? "Subiendo y contando… puede tardar unos minutos"
                    : estado.revisor_activo
                      ? "Subir y calcular el costo"
                      : "Subir y revisar carpetas y nombres"}
                </button>
              </div>
              {error && errorDe === "subir" ? <Mensaje tipo="error">{error}</Mensaje> : null}
            </>
          ) : null}

          {org && estado.programa && !corriendo && estado.estado !== "vacio" ? (
            <>
              <Titulo n={3}>Revise carpetas, nombres e índice</Titulo>
              <p>
                <strong>{estado.programa}</strong>, según el instructivo de la Dirección Académica:{" "}
                {org.archivos_con_observaciones === 0 && org.acciones_con_observaciones.length === 0
                  ? "las carpetas y los nombres cumplen."
                  : `${org.archivos_con_observaciones} archivos con observaciones${
                      org.acciones_con_observaciones.length > 0
                        ? ` y estructura incompleta en las acciones ${org.acciones_con_observaciones.join(", ")}`
                        : ""
                    }.`}
              </p>
              <p>
                Descargue abajo «Carpetas y nombres de las evidencias» (con un nombre sugerido para cada archivo) y el
                «Índice electrónico del expediente» prellenado. No usa el modelo ni gasta créditos.
              </p>
            </>
          ) : null}

          {!estado.revisor_activo ? (
            <Mensaje tipo="info">
              La revisión con el modelo (cruce con el plan y borrador del cierre) sigue apagada, pendiente del aval de
              tratamiento de datos. Por eso los soportes se borran del servidor apenas se revisan carpetas y nombres.
            </Mensaje>
          ) : null}

          {est && estado.revisor_activo && estado.programa && ["cargado", "interrumpido"].includes(estado.estado) ? (
            <>
              <Titulo n={4}>Revise el costo y confirme</Titulo>
              <p>
                <strong>{estado.programa}</strong>: {est.archivos} archivos para {est.acciones} acciones.
              </p>
              <ul>
                <li>
                  Irán al modelo: <strong>{est.al_modelo} archivos</strong>
                  {est.en_cache > 0 ? ` (otros ${est.en_cache} ya se describieron antes y no se vuelven a pagar)` : ""}.
                </li>
                <li>
                  Costo aproximado: <strong>{usd(est.costo_usd)}</strong> (es una cota alta). Ninguna revisión pasa
                  de {usd(est.tope_usd)}.
                </li>
                {est.generales > 0 ? <li>{est.generales} archivos fuera de las carpetas de acción (documentos generales).</li> : null}
                {est.acciones_sin_soportes.length > 0 ? (
                  <li>Acciones sin carpeta de soportes: {est.acciones_sin_soportes.join(", ")}.</li>
                ) : null}
                {est.carpetas_sin_accion.length > 0 ? (
                  <li>
                    Carpetas cuyo código no está en el plan (no se cruzan): {est.carpetas_sin_accion.join(", ")}.
                  </li>
                ) : null}
              </ul>
              {est.excede_tope ? <Mensaje tipo="error">{est.excede_tope}</Mensaje> : null}
              {estado.estado === "interrumpido" ? (
                <Mensaje tipo="info">
                  La revisión anterior se interrumpió (el servicio se reinició) y sus soportes se borraron. Vuelva a
                  subir el zip: lo ya pagado no se cobra otra vez.
                </Mensaje>
              ) : null}
              {puedeCorrer && !est.excede_tope ? (
                <>
                  <label className="confirmar">
                    <input type="checkbox" checked={acepto} onChange={(e) => setAcepto(e.target.checked)} />
                    Entiendo que esta revisión gastará unos {usd(est.costo_usd)} de los créditos de la Facultad.
                  </label>
                  <div className="botones">
                    <button type="button" disabled={!acepto || ocupado !== null} onClick={correr}>
                      {ocupado === "correr" ? "Iniciando…" : "Iniciar la revisión"}
                    </button>
                  </div>
                  {error && errorDe === "correr" ? <Mensaje tipo="error">{error}</Mensaje> : null}
                </>
              ) : null}
            </>
          ) : null}

          {estado.pasos && ["corriendo", "terminado", "fallido"].includes(estado.estado) ? (
            <>
              <Titulo n={5}>Avance de la revisión</Titulo>
              {corriendo ? (
                <p>
                  Puede cerrar esta página: la revisión sigue. Tarda unos minutos. Gastado hasta ahora:{" "}
                  {usd(estado.costo_usd ?? 0)}.
                </p>
              ) : null}
              <ol className="pasos">
                {estado.pasos.map((p) => {
                  const pct = p.estado === "hecho" ? 100 : p.total ? Math.round((100 * p.hechos) / p.total) : 0;
                  return (
                    <li key={p.clave}>
                      <span className="titulo-paso">
                        <span>{p.titulo}</span>
                        <span>
                          {p.estado === "hecho" ? "Listo" : p.estado === "en curso" ? `${p.hechos} de ${p.total}` : "En espera"}
                        </span>
                      </span>
                      <span
                        className="barra grande"
                        role="progressbar"
                        aria-label={p.titulo}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={pct}
                      >
                        <span style={{ width: `${pct}%` }} />
                      </span>
                    </li>
                  );
                })}
              </ol>
            </>
          ) : null}

          {estado.estado === "fallido" && estado.error ? <Mensaje tipo="error">{estado.error}</Mensaje> : null}

          {estado.estado === "terminado" && estado.resumen ? (
            <>
              <Titulo n={6}>Descargue los resultados</Titulo>
              {estado.resumen.detenida ? (
                <Mensaje tipo="error">
                  La revisión no se completó ({estado.resumen.detenida}). Los archivos traen lo que alcanzó a
                  revisarse.
                </Mensaje>
              ) : (
                <Mensaje tipo="exito">
                  Revisión terminada en {String(estado.resumen.minutos).replace(".", ",")} minutos. Costo:{" "}
                  {usd(estado.resumen.costo_usd)}.
                </Mensaje>
              )}
              <p>Veredictos propuestos (para revisar, no son decisiones):</p>
              <ul>
                {Object.entries(estado.resumen.veredictos).map(([v, n]) => (
                  <li key={v}>
                    {v}: {n} {n === 1 ? "acción" : "acciones"}
                  </li>
                ))}
                {estado.resumen.sin_descripcion > 0 ? (
                  <li>{estado.resumen.sin_descripcion} archivos no se pudieron describir (ver el inventario).</li>
                ) : null}
                {estado.resumen.alertas > 0 ? <li>{estado.resumen.alertas} alertas del verificador de citas.</li> : null}
              </ul>
              <AvisoPropuesta />
            </>
          ) : null}

          {estado.descargas.length > 0 && !corriendo ? (
            <div className="botones">
              {DESCARGAS.filter((d) => estado.descargas.includes(d.clave)).map((d) => (
                <button key={d.clave} type="button" className="secundario" onClick={() => descargar(d.clave, d.nombre)}>
                  {d.texto}
                </button>
              ))}
            </div>
          ) : null}

          {hayAlgo && !corriendo ? (
            <>
              <h2>Borrar</h2>
              <p>
                Borra del servidor los soportes y los resultados de esta revisión. Descargue antes lo que necesite. Si
                no los borra, se borran solos a los {estado.retencion_dias} días.
              </p>
              <label className="confirmar">
                <input type="checkbox" checked={borrarCache} onChange={(e) => setBorrarCache(e.target.checked)} />
                Borrar también las descripciones guardadas (la próxima revisión las volverá a pagar).
              </label>
              <div className="botones">
                <button type="button" className="peligro" disabled={ocupado !== null} onClick={borrar}>
                  {ocupado === "borrar" ? "Borrando…" : "Borrar soportes"}
                </button>
              </div>
              {error && errorDe === "borrar" ? <Mensaje tipo="error">{error}</Mensaje> : null}
            </>
          ) : null}
        </>
      ) : null}
    </Pantalla>
  );
}
