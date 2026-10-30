"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { ErrorApi, guardarArchivo, llamar } from "@/lib/api";
import { ResumenPlan } from "@/lib/calidad";
import { useSesion } from "@/lib/sesion";

type Estimacion = {
  acciones: number;
  sin_evidencia_nueva: number;
  al_modelo: number;
  en_cache: number;
  costo_usd: number;
  tope_usd: number;
  excede_tope: string;
};

type Resumen = {
  acciones: number;
  sin_evidencia_nueva: number;
  con_propuesta: number;
  sin_propuesta: number;
  frases_rechazadas: number;
  costo_usd: number;
  detenido: string;
};

type Estado = {
  estado: "vacio" | "corriendo" | "terminado" | "fallido" | "interrumpido";
  programa?: string;
  corte?: string;
  hechas?: number;
  total?: number;
  costo_usd?: number;
  resumen?: Resumen | null;
  error?: string;
  descargas: string[];
  tope_usd: number;
};

type Cortes = { cortes: string[]; proximo: { fecha: string; estimado: boolean } | null };

const DESCARGAS: { clave: string; nombre: string; texto: string }[] = [
  { clave: "docx", nombre: "borrador_avance.docx", texto: "Borrador de avance (Word)" },
  { clave: "xlsx", nombre: "revision_avance.xlsx", texto: "Hoja para aprobar, editar o descartar (Excel)" },
];

const usd = (n: number) => `${n.toFixed(2).replace(".", ",")} USD`;

export default function BorradorAvance() {
  const { token } = useSesion();
  const t = token("calidad");
  const [estado, setEstado] = useState<Estado | null>(null);
  const [apagado, setApagado] = useState<string | null>(null);
  const [programas, setProgramas] = useState<ResumenPlan[]>([]);
  const [programa, setPrograma] = useState("");
  const [cortes, setCortes] = useState<Cortes | null>(null);
  const [corte, setCorte] = useState("");
  const [est, setEst] = useState<Estimacion | null>(null);
  const [acepto, setAcepto] = useState(false);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const consultar = useCallback(async () => {
    if (!t) return;
    try {
      setEstado(await llamar<Estado>("calidad", "/calidad/avance", { token: t }));
      setApagado(null);
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === 403) setApagado(e.message);
      else setError((e as Error).message);
    }
  }, [t]);

  useEffect(() => {
    consultar();
    if (!t) return;
    llamar<{ programas: ResumenPlan[] }>("calidad", "/calidad/programas", { token: t })
      .then((r) => setProgramas(r.programas))
      .catch(() => undefined);
  }, [consultar, t]);

  const corriendo = estado?.estado === "corriendo";
  useEffect(() => {
    if (!corriendo) return;
    const intervalo = setInterval(consultar, 3000);
    return () => clearInterval(intervalo);
  }, [corriendo, consultar]);

  const elegirPrograma = async (p: string) => {
    setPrograma(p);
    setCorte("");
    setCortes(null);
    setEst(null);
    setAcepto(false);
    if (!p) return;
    try {
      setCortes(
        await llamar<Cortes>("calidad", `/calidad/avance/cortes?programa=${encodeURIComponent(p)}`, { token: t }),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const accion = async (nombre: string, hacer: () => Promise<void>) => {
    setOcupado(nombre);
    setError(null);
    try {
      await hacer();
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(null);
  };

  const estimar = () =>
    accion("estimar", async () => {
      setAcepto(false);
      setEst(await llamar<Estimacion>("calidad", "/calidad/avance/estimar", { token: t, json: { programa, corte } }));
    });

  const generar = () =>
    accion("generar", async () => {
      setEstado(
        await llamar<Estado>("calidad", "/calidad/avance/generar", {
          token: t,
          json: { programa, corte, confirmo_costo: true, costo_usd: est?.costo_usd },
        }),
      );
      setEst(null);
      setAcepto(false);
    });

  const borrar = () => {
    if (!window.confirm("¿Borrar el borrador y las hojas de esta generación?")) return;
    accion("borrar", async () => {
      setEstado(await llamar<Estado>("calidad", "/calidad/avance", { token: t, metodo: "DELETE" }));
    });
  };

  const descargar = (clave: string, nombre: string) =>
    accion("descargar", async () => {
      guardarArchivo(await llamar<Blob>("calidad", `/calidad/avance/descargar/${clave}`, { token: t }), nombre);
    });

  const pct = estado?.total ? Math.round((100 * (estado.hechas ?? 0)) / estado.total) : 0;

  return (
    <Pantalla
      titulo="Borrador de avance del corte"
      servicio="calidad"
      roles={["calidad", "admin"]}
      hace={[
        "Propone, para cada acción de un programa, la descripción de avance de un corte, con las tareas del cronograma, el % declarado, lo escrito en cortes anteriores, los enlaces de evidencia y los soportes que el revisor ya describió.",
        "Cada frase cita su fuente (hoja y fila del plan, enlace o soporte). Lo que no tiene fuente se marca y no se afirma.",
        "Si una acción no tiene evidencia nueva, lo dice: «Sin evidencia nueva en el corte».",
      ]}
      noHace={[
        "No decide si una acción se cumplió ni cambia el % de avance: propone, y la oficina de calidad aprueba, edita o descarta en el Excel.",
        "No escribe nombres de personas: solo cargos y dependencias.",
        "No escribe en el plan: el texto aprobado se carga a mano en el plan o en el sistema de autoevaluación.",
      ]}
    >
      {apagado ? (
        <Mensaje tipo="info">
          <strong>Apagado.</strong> Esta herramienta manda al modelo contenido del plan de mejoramiento y está apagada
          en este servicio hasta que se active.
        </Mensaje>
      ) : null}
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}

      {estado && !apagado ? (
        <>
          <Mensaje tipo="info">
            <strong>Todo lo que entrega es una propuesta.</strong> La oficina de calidad la revisa; el Comité Asesor
            recomienda y el Consejo de Facultad decide.
          </Mensaje>

          {!corriendo ? (
            <>
              <h2>1. Elija el programa y el corte</h2>
              <label htmlFor="programa">Programa</label>
              <select id="programa" value={programa} onChange={(e) => elegirPrograma(e.target.value)}>
                <option value="">— Elija un programa —</option>
                {programas.map((p) => (
                  <option key={p.programa} value={p.programa}>
                    {p.programa} ({p.acciones} acciones)
                  </option>
                ))}
              </select>
              {cortes ? (
                <>
                  <label htmlFor="corte">
                    Fecha del corte
                    <span className="ayuda">
                      {cortes.cortes.length > 0 ? `Cortes que el plan ya tiene: ${cortes.cortes.join(", ")}. ` : ""}
                      {cortes.proximo
                        ? `Próximo corte: ${cortes.proximo.fecha}${cortes.proximo.estimado ? " (estimado)" : ""}.`
                        : ""}
                    </span>
                  </label>
                  <input
                    id="corte"
                    type="date"
                    value={corte}
                    onChange={(e) => {
                      setCorte(e.target.value);
                      setEst(null);
                      setAcepto(false);
                    }}
                  />
                </>
              ) : null}
              <div className="botones">
                <button type="button" disabled={!programa || !corte || ocupado !== null} onClick={estimar}>
                  {ocupado === "estimar" ? "Calculando…" : "Estimar el costo"}
                </button>
              </div>
            </>
          ) : null}

          {est ? (
            <>
              <h2>2. Revise el costo y confirme</h2>
              <ul>
                <li>
                  {est.acciones} acciones: <strong>{est.al_modelo}</strong> irán al modelo
                  {est.en_cache > 0 ? ` (otras ${est.en_cache} ya se redactaron antes y no se vuelven a pagar)` : ""}; en{" "}
                  {est.sin_evidencia_nueva} no hay evidencia nueva en el corte y se marcan así, sin costo.
                </li>
                <li>
                  Costo aproximado: <strong>{usd(est.costo_usd)}</strong> (es una cota alta). Ningún borrador pasa de{" "}
                  {usd(est.tope_usd)}.
                </li>
              </ul>
              {est.excede_tope ? <Mensaje tipo="error">{est.excede_tope}</Mensaje> : null}
              {!est.excede_tope ? (
                <>
                  <label className="confirmar">
                    <input type="checkbox" checked={acepto} onChange={(e) => setAcepto(e.target.checked)} />
                    Entiendo que este borrador gastará unos {usd(est.costo_usd)} de los créditos de la Facultad.
                  </label>
                  <div className="botones">
                    <button type="button" disabled={!acepto || ocupado !== null} onClick={generar}>
                      {ocupado === "generar" ? "Iniciando…" : "Generar el borrador"}
                    </button>
                  </div>
                </>
              ) : null}
            </>
          ) : null}

          {corriendo ? (
            <>
              <h2>Generando el borrador</h2>
              <p>
                {estado.programa}, corte {estado.corte}. Puede cerrar esta página: sigue en segundo plano. Gastado hasta
                ahora: {usd(estado.costo_usd ?? 0)}.
              </p>
              <span
                className="barra grande"
                role="progressbar"
                aria-label="Avance del borrador"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
              >
                <span style={{ width: `${pct}%` }} />
              </span>
            </>
          ) : null}

          {estado.estado === "interrumpido" ? (
            <Mensaje tipo="info">
              El borrador anterior se interrumpió (el servicio se reinició). Genérelo de nuevo: lo ya pagado no se cobra
              otra vez.
            </Mensaje>
          ) : null}
          {estado.estado === "fallido" && estado.error ? <Mensaje tipo="error">{estado.error}</Mensaje> : null}

          {estado.estado === "terminado" && estado.resumen ? (
            <>
              <h2>3. Descargue y revise</h2>
              <p>
                {estado.programa}, corte {estado.corte}.
              </p>
              {estado.resumen.detenido ? (
                <Mensaje tipo="error">
                  El borrador no se completó ({estado.resumen.detenido}). Los archivos traen lo que alcanzó a hacerse.
                </Mensaje>
              ) : (
                <Mensaje tipo="exito">Borrador listo. Costo: {usd(estado.resumen.costo_usd)}.</Mensaje>
              )}
              <ul>
                <li>{estado.resumen.con_propuesta} acciones con propuesta.</li>
                <li>{estado.resumen.sin_evidencia_nueva} acciones sin evidencia nueva en el corte.</li>
                {estado.resumen.sin_propuesta > 0 ? (
                  <li>{estado.resumen.sin_propuesta} acciones sin propuesta del modelo (ver el Excel).</li>
                ) : null}
                {estado.resumen.frases_rechazadas > 0 ? (
                  <li>
                    {estado.resumen.frases_rechazadas} frases sin fuente verificada: aparecen marcadas con ⚠ y no se
                    afirman.
                  </li>
                ) : null}
              </ul>
            </>
          ) : null}

          {estado.descargas.length > 0 && !corriendo ? (
            <div className="botones">
              {DESCARGAS.filter((d) => estado.descargas.includes(d.clave)).map((d) => (
                <button
                  key={d.clave}
                  type="button"
                  className="secundario"
                  disabled={ocupado !== null}
                  onClick={() => descargar(d.clave, d.nombre)}
                >
                  {d.texto}
                </button>
              ))}
              <button type="button" className="peligro" disabled={ocupado !== null} onClick={borrar}>
                Borrar
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </Pantalla>
  );
}
