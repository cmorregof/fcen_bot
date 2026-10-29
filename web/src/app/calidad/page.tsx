"use client";

import { useCallback, useEffect, useState } from "react";
import { Estado } from "@/components/Estado";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Conteo = Record<string, number>;
type Tarea = {
  id: number;
  codigo: string;
  tarea: string;
  responsable: string;
  fecha_limite: string;
  evidencia_esperada: string;
  estado: string;
  evidencias: { tipo: string; valor: string; por: string | null; fecha: string }[];
};
type Plan = { programa: string; conteo: Conteo; tareas: Tarea[] };

function EvidenciaForm({ tarea, alGuardar }: { tarea: Tarea; alGuardar: () => void }) {
  const { token } = useSesion();
  const [enlace, setEnlace] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await llamar("calidad", "/calidad/evidencia", {
            token: token("calidad"),
            json: { tarea_id: tarea.id, enlace },
          });
          setEnlace("");
          alGuardar();
        } catch (err) {
          setError((err as Error).message);
        }
      }}
    >
      <label htmlFor={`ev-${tarea.id}`}>
        Enlace de la evidencia de {tarea.codigo}
        <span className="ayuda">Se espera: {tarea.evidencia_esperada}. Al guardar, la tarea queda cumplida.</span>
      </label>
      <input id={`ev-${tarea.id}`} type="url" value={enlace} onChange={(e) => setEnlace(e.target.value)} required />
      <div className="botones">
        <button type="submit">Guardar evidencia</button>
      </div>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
    </form>
  );
}

export default function EstadoPlan() {
  const { token } = useSesion();
  const [programas, setProgramas] = useState<{ programa: string; conteo: Conteo }[] | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [abierta, setAbierta] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const t = token("calidad");

  useEffect(() => {
    if (!t) return;
    llamar<{ programas: { programa: string; conteo: Conteo }[] }>("calidad", "/calidad/programas", { token: t })
      .then((d) => setProgramas(d.programas))
      .catch((e: Error) => setError(e.message));
  }, [t]);

  const abrir = useCallback(
    async (programa: string) => {
      setError(null);
      try {
        setPlan(await llamar<Plan>("calidad", `/calidad/plan?programa=${encodeURIComponent(programa)}`, { token: t }));
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

  return (
    <Pantalla
      titulo="Estado del plan de mejoramiento"
      servicio="calidad"
      roles={["calidad", "admin"]}
      hace={[
        "Muestra las tareas de cada programa: vencidas, próximas a vencer, pendientes y cumplidas.",
        "Permite registrar el enlace de una evidencia y descargar el reporte en Excel.",
      ]}
      noHace={[
        "No envía avisos a nadie.",
        "No reemplaza el seguimiento oficial ni las decisiones de los comités.",
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
                  {p.conteo["vencida"]} vencidas · {p.conteo["próxima a vencer"]} próximas · {p.conteo["cumplida"]} cumplidas
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
          <div className="tabla">
            <table>
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Tarea</th>
                  <th>Responsable</th>
                  <th>Fecha límite</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {plan.tareas.map((tarea) => (
                  <tr key={tarea.id}>
                    <td>{tarea.codigo}</td>
                    <td>
                      {tarea.tarea}
                      {tarea.evidencias.map((e) => (
                        <div key={e.fecha + e.valor}>
                          <small>
                            Evidencia: {e.tipo === "enlace" ? <a href={e.valor}>{e.valor}</a> : e.valor}
                          </small>
                        </div>
                      ))}
                      {tarea.estado !== "cumplida" ? (
                        abierta === tarea.id ? (
                          <EvidenciaForm
                            tarea={tarea}
                            alGuardar={() => {
                              setAbierta(null);
                              abrir(plan.programa);
                            }}
                          />
                        ) : (
                          <div>
                            <button type="button" className="secundario" onClick={() => setAbierta(tarea.id)}>
                              Registrar evidencia
                            </button>
                          </div>
                        )
                      ) : null}
                    </td>
                    <td>{tarea.responsable}</td>
                    <td>{tarea.fecha_limite}</td>
                    <td>
                      <Estado valor={tarea.estado} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </Pantalla>
  );
}
