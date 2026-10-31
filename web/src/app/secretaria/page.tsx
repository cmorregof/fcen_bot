"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Registro = {
  acto: "oficio" | "resolucion";
  numero: string;
  fecha_ingreso: string | null;
  fecha_expedicion: string | null;
  fecha_notificacion: string | null;
};
type Est = { casos: number; mediana: number | null; p90: number | null };
type Caso = {
  caso_id: number;
  programa: string;
  tramite: string;
  estudiante: string;
  decision: string;
  acta_numero: string;
  acta_fecha: string;
  sugerida_ingreso: string | null;
  registro: Registro | null;
  registrado_por: string;
};
type Datos = {
  semestre: string;
  resumen: {
    decididos: number;
    completos: number;
    ingreso_expedicion: Est;
    expedicion_notificacion: Est;
    total: Est;
  };
  casos: Caso[];
};

const vacio = (c: Caso): Registro =>
  c.registro ?? {
    acto: "oficio",
    numero: "",
    fecha_ingreso: c.sugerida_ingreso,
    fecha_expedicion: null,
    fecha_notificacion: null,
  };

const dias = (e: Est) =>
  e.casos === 0 ? "—" : `${String(e.mediana).replace(".", ",")} días (p90: ${e.p90}) · ${e.casos} casos`;

function FilaCaso({ caso, token, alGuardar }: { caso: Caso; token: string | null; alGuardar: () => void }) {
  const [r, setR] = useState<Registro>(vacio(caso));
  const [estado, setEstado] = useState<"" | "guardando" | "guardado">("");
  const [error, setError] = useState<string | null>(null);
  const cambiar = (campo: keyof Registro, valor: string) => {
    setEstado("");
    setR({ ...r, [campo]: valor === "" && campo !== "numero" ? null : valor });
  };
  const borrador = async () => {
    setError(null);
    try {
      const archivo = await llamar<Blob>("actas", `/actas/secretaria/casos/${caso.caso_id}/oficio-consejo`, { token });
      guardarArchivo(archivo, `Borrador_Consejo_caso_${caso.caso_id}.docx`);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const guardar = async () => {
    setEstado("guardando");
    setError(null);
    try {
      await llamar("actas", `/actas/secretaria/notificaciones/${caso.caso_id}`, { token, metodo: "PUT", json: r });
      setEstado("guardado");
      alGuardar();
    } catch (e) {
      setEstado("");
      setError((e as Error).message);
    }
  };
  return (
    <tr>
      <td>
        <strong>#{caso.caso_id}</strong>
        <br />
        {caso.estudiante || "—"}
        <br />
        <span className="ayuda">
          {caso.programa} · {caso.tramite} · {caso.decision} · Acta {caso.acta_numero} ({caso.acta_fecha})
        </span>
      </td>
      <td>
        <select value={r.acto} onChange={(e) => cambiar("acto", e.target.value)} aria-label="Acto">
          <option value="oficio">Oficio</option>
          <option value="resolucion">Resolución</option>
        </select>
        <input value={r.numero} onChange={(e) => cambiar("numero", e.target.value)} placeholder="Mz.FCEN.1.004-…" aria-label="Número" />
      </td>
      <td>
        <input type="date" value={r.fecha_ingreso ?? ""} onChange={(e) => cambiar("fecha_ingreso", e.target.value)} aria-label="Ingreso a la Secretaría" />
        {!caso.registro && caso.sugerida_ingreso ? <span className="ayuda">Sugerida: fecha de la recomendación del comité.</span> : null}
      </td>
      <td>
        <input type="date" value={r.fecha_expedicion ?? ""} onChange={(e) => cambiar("fecha_expedicion", e.target.value)} aria-label="Expedición" />
      </td>
      <td>
        <input type="date" value={r.fecha_notificacion ?? ""} onChange={(e) => cambiar("fecha_notificacion", e.target.value)} aria-label="Notificación" />
      </td>
      <td>
        <button type="button" className="secundario" onClick={guardar} disabled={estado === "guardando"}>
          {estado === "guardando" ? "Guardando…" : estado === "guardado" ? "Guardado" : "Guardar"}
        </button>
        {caso.decision === "Aprobó" || caso.decision === "No aprobó" ? (
          <button type="button" className="secundario" onClick={borrador}>
            Borrador (Word)
          </button>
        ) : null}
        {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      </td>
    </tr>
  );
}

export default function PaginaSecretaria() {
  const { token } = useSesion();
  const t = token("actas");
  const [semestre, setSemestre] = useState("");
  const [datos, setDatos] = useState<Datos | null>(null);
  const [error, setError] = useState<string | null>(null);

  const consultar = useCallback(
    async (s: string) => {
      if (!t) return;
      setError(null);
      try {
        setDatos(await llamar<Datos>("actas", `/actas/secretaria/notificaciones?semestre=${encodeURIComponent(s)}`, { token: t }));
      } catch (e) {
        setDatos(null);
        setError((e as Error).message);
      }
    },
    [t],
  );

  useEffect(() => {
    consultar("");
  }, [consultar]);

  const descargar = async () => {
    if (!datos) return;
    try {
      const archivo = await llamar<Blob>(
        "actas",
        `/actas/secretaria/notificaciones/xlsx?semestre=${encodeURIComponent(datos.semestre)}`,
        { token: t },
      );
      guardarArchivo(archivo, `tiempos_notificaciones_${datos.semestre}.xlsx`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const descargarEstadisticas = async () => {
    if (!datos) return;
    try {
      const archivo = await llamar<Blob>(
        "actas",
        `/actas/secretaria/estadisticas/xlsx?semestre=${encodeURIComponent(datos.semestre)}`,
        { token: t },
      );
      guardarArchivo(archivo, `estadisticas_consejo_fcen_${datos.semestre}.xlsx`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Pantalla
      titulo="Notificaciones"
      servicio="actas"
      roles={["secretaria", "admin"]}
      hace={[
        "Lista los casos que el Consejo de Facultad decidió en el semestre, según las actas confirmadas en MemorIA.",
        "Le permite descargar el borrador del oficio o la resolución, y registrar su número y las fechas de ingreso, expedición y notificación.",
        "Calcula los tiempos de respuesta para el indicador de divulgación de la información oficial, con Excel.",
      ]}
      noHace={[
        "No notifica ni envía nada: solo guarda las fechas que usted registra.",
        "El Excel no lleva nombres ni documentos.",
      ]}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          consultar(semestre);
        }}
      >
        <label htmlFor="semestre">
          Semestre
          <span className="ayuda">2026-1S (enero a junio) o 2026-2S (julio a diciembre), por la fecha de la sesión del Consejo. Vacío: el actual.</span>
        </label>
        <input id="semestre" value={semestre} onChange={(e) => setSemestre(e.target.value)} placeholder="2026-2S" />
        <div className="botones">
          <button type="submit">Consultar</button>
          <button type="button" className="secundario" onClick={descargar} disabled={!datos}>
            Descargar Excel de tiempos
          </button>
          <button type="button" className="secundario" onClick={descargarEstadisticas} disabled={!datos}>
            Estadísticas para Calidad (Excel)
          </button>
        </div>
      </form>

      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}

      {datos ? (
        <>
          <h2>{datos.semestre}</h2>
          <ul>
            <li>
              Casos decididos: <strong>{datos.resumen.decididos}</strong>; con las tres fechas: <strong>{datos.resumen.completos}</strong>.
            </li>
            <li>Ingreso → expedición: {dias(datos.resumen.ingreso_expedicion)}.</li>
            <li>Expedición → notificación: {dias(datos.resumen.expedicion_notificacion)}.</li>
            <li>Ingreso → notificación: {dias(datos.resumen.total)}.</li>
          </ul>
          {datos.casos.length === 0 ? (
            <Mensaje tipo="info">No hay casos decididos por el Consejo de Facultad en este semestre.</Mensaje>
          ) : (
            <div className="tabla">
              <table>
                <thead>
                  <tr>
                    <th>Caso</th>
                    <th>Acto y número</th>
                    <th>Ingreso a la Secretaría</th>
                    <th>Expedición</th>
                    <th>Notificación</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {datos.casos.map((c) => (
                    <FilaCaso key={c.caso_id} caso={c} token={t} alGuardar={() => consultar(datos.semestre)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </Pantalla>
  );
}
