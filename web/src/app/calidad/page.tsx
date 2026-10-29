"use client";

import { useCallback, useEffect, useState } from "react";
import { Estado } from "@/components/Estado";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { Accion, PlanCompleto, ResumenPlan, porcentaje } from "@/lib/calidad";
import { useSesion } from "@/lib/sesion";

const ORDEN = ["no funcionó", "vencida", "en curso", "por iniciar", "cumplida"];

function Avance({ valor }: { valor: number | null }) {
  return (
    <span>
      <span className="barra" aria-hidden="true">
        <span style={{ width: `${Math.min(100, valor ?? 0)}%` }} />
      </span>
      {porcentaje(valor)}
    </span>
  );
}

function Cifras({ r }: { r: ResumenPlan }) {
  return (
    <div className="tarjetas">
      <div className="tarjeta">
        <span className="cifra">{porcentaje(r.avance)}</span>Avance promedio de {r.acciones} acciones
      </div>
      {ORDEN.map((e) => (
        <div key={e} className="tarjeta">
          <span className="cifra">{r.conteo[e] ?? 0}</span>
          <Estado valor={e} />
        </div>
      ))}
      <div className="tarjeta">
        <span className="cifra">{r.reprogramadas}</span>Reprogramadas
      </div>
    </div>
  );
}

function SoporteForm({ programa, accion, alGuardar }: { programa: string; accion: Accion; alGuardar: () => void }) {
  const { token } = useSesion();
  const [enlace, setEnlace] = useState("");
  const [error, setError] = useState<string | null>(null);
  const id = `sop-${accion.codigo}`;
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await llamar("calidad", "/calidad/evidencia", {
            token: token("calidad"),
            json: { programa, codigo: accion.codigo, enlace },
          });
          setEnlace("");
          alGuardar();
        } catch (err) {
          setError((err as Error).message);
        }
      }}
    >
      <label htmlFor={id}>
        Enlace del soporte de la acción {accion.codigo}
        <span className="ayuda">Queda pendiente de revisión. No cambia el % de avance, que solo viene del plan.</span>
      </label>
      <input id={id} type="url" value={enlace} onChange={(e) => setEnlace(e.target.value)} required />
      <div className="botones">
        <button type="submit">Guardar soporte</button>
      </div>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
    </form>
  );
}

export default function EstadoPlan() {
  const { token } = useSesion();
  const [programas, setProgramas] = useState<ResumenPlan[] | null>(null);
  const [plan, setPlan] = useState<PlanCompleto | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const t = token("calidad");

  useEffect(() => {
    if (!t) return;
    llamar<{ programas: ResumenPlan[] }>("calidad", "/calidad/programas", { token: t })
      .then((d) => setProgramas(d.programas))
      .catch((e: Error) => setError(e.message));
  }, [t]);

  const abrir = useCallback(
    async (programa: string) => {
      setError(null);
      try {
        setPlan(await llamar<PlanCompleto>("calidad", `/calidad/plan?programa=${encodeURIComponent(programa)}`, { token: t }));
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [t],
  );

  const reporte = async () => {
    if (!plan) return;
    try {
      const datos = await llamar<Blob>("calidad", `/calidad/reporte?programa=${encodeURIComponent(plan.programa)}`, { token: t });
      guardarArchivo(datos, `reporte-plan-${plan.programa}.xlsx`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const reprogramadas = plan?.objetivos.flatMap((o) => o.acciones).filter((a) => a.reprogramada) ?? [];

  return (
    <Pantalla
      titulo="Estado del plan de mejoramiento"
      servicio="calidad"
      roles={["calidad", "admin"]}
      hace={[
        "Muestra cada programa por objetivos y acciones, con su % de avance y su estado.",
        "Señala las vencidas, las reprogramadas y las marcadas «NO FUNCIONÓ».",
        "Permite registrar el enlace de un soporte y descargar el reporte en Excel.",
      ]}
      noHace={[
        "No cambia el % de avance: ese dato solo viene del plan cargado.",
        "No envía avisos a nadie ni reemplaza el seguimiento oficial.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {programas === null ? <p>Cargando programas…</p> : null}
      {programas?.length === 0 ? <Mensaje tipo="info">Aún no hay plan cargado. Use «Cargar el plan».</Mensaje> : null}
      {programas && programas.length > 0 && !plan ? (
        <>
          <h2>Elija un programa</h2>
          <div className="tarjetas">
            {programas.map((p) => (
              <button key={p.programa} type="button" className="tarjeta secundario" onClick={() => abrir(p.programa)}>
                <span style={{ textAlign: "left" }}>
                  <strong>{p.programa}</strong>
                  {p.acciones} acciones · avance {porcentaje(p.avance)}
                  <br />
                  {p.conteo["vencida"] ?? 0} vencidas · {p.reprogramadas} reprogramadas · {p.conteo["no funcionó"] ?? 0} «NO
                  FUNCIONÓ»
                </span>
              </button>
            ))}
          </div>
        </>
      ) : null}
      {plan ? (
        <>
          <div className="botones">
            <button type="button" className="secundario" onClick={() => setPlan(null)}>
              ← Otro programa
            </button>
            <button type="button" onClick={reporte}>
              Descargar reporte en Excel
            </button>
          </div>
          <h2>{plan.programa}</h2>
          <p>
            <small>
              Archivo: {plan.archivo}
              {plan.proximo_corte
                ? ` · Próximo corte: ${plan.proximo_corte.fecha}${plan.proximo_corte.estimado ? " (estimado)" : ""}`
                : ""}
            </small>
          </p>
          <Cifras r={plan} />
          {plan.objetivos.map((o) => (
            <div key={o.codigo}>
              <h3>Objetivo {o.texto.startsWith(o.codigo) ? o.texto : `${o.codigo} ${o.texto}`}</h3>
              <div className="tabla">
                <table>
                  <thead>
                    <tr>
                      <th>Acción</th>
                      <th>Responsables</th>
                      <th>Fin</th>
                      <th>Avance</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {o.acciones.map((a) => (
                      <tr key={a.codigo}>
                        <td>
                          <strong>{a.codigo}</strong> {a.descripcion}
                          {a.soportes.map((s) => (
                            <div key={s.fecha + s.valor}>
                              <small>
                                Soporte ({s.por ?? "sin nombre"}):{" "}
                                {s.tipo === "enlace" ? <a href={s.valor}>{s.valor}</a> : s.valor}
                              </small>
                            </div>
                          ))}
                          {abierta === a.codigo ? (
                            <SoporteForm
                              programa={plan.programa}
                              accion={a}
                              alGuardar={() => {
                                setAbierta(null);
                                abrir(plan.programa);
                              }}
                            />
                          ) : (
                            <div>
                              <button type="button" className="secundario" onClick={() => setAbierta(a.codigo)}>
                                Registrar soporte
                              </button>
                            </div>
                          )}
                        </td>
                        <td>{a.responsables}</td>
                        <td>
                          {a.fecha_fin ?? "sin fecha"}
                          {a.fechas_fin_anteriores.length > 0 ? (
                            <div>
                              <small>antes: {a.fechas_fin_anteriores.join(", ")}</small>
                            </div>
                          ) : null}
                        </td>
                        <td>
                          <Avance valor={a.avance} />
                        </td>
                        <td>
                          <Estado valor={a.estado} />
                          {a.reprogramada ? (
                            <div>
                              <span className="estado reprogramada">reprogramada</span>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
          {reprogramadas.length > 0 ? (
            <>
              <h3>Reprogramadas ({reprogramadas.length})</h3>
              <ul>
                {reprogramadas.map((a) => (
                  <li key={a.codigo}>
                    <strong>{a.codigo}</strong>
                    {a.fechas_fin_anteriores.length > 0 ? ` fin anterior ${a.fechas_fin_anteriores.join(", ")}` : ""}
                    {a.marcas.length > 0 ? ` · «${a.marcas.join("», «")}»` : ""}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {plan.alertas.length > 0 ? (
            <Mensaje tipo="info">
              Al leer el archivo:
              <ul>
                {plan.alertas.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </Mensaje>
          ) : null}
        </>
      ) : null}
    </Pantalla>
  );
}
