"use client";

import { useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

const ETIQUETAS: Record<string, string> = {
  consentimientos: "Personas que aceptaron el aviso de datos",
  rechazos: "Personas que no aceptaron el aviso",
  menores: "Menores de edad",
  preguntas: "Preguntas recibidas",
  preguntas_sin_respuesta: "Preguntas que no estaban en el listado",
  documentos_revisados: "Documentos revisados",
  documentos_con_errores: "Documentos con algo por corregir",
  credenciales_bloqueadas: "Veces que alguien escribió un correo o contraseña",
};

type Documento = { clave: string; nombre: string; seccion: string; chequeo: string[] };

export default function Admision() {
  const { token } = useSesion();
  const [metricas, setMetricas] = useState<Record<string, number> | null>(null);
  const [docs, setDocs] = useState<Documento[]>([]);
  const [error, setError] = useState<string | null>(null);
  const t = token("admision");

  useEffect(() => {
    if (!t) return;
    llamar<{ metricas: Record<string, number> }>("admision", "/admision/metricas", { token: t })
      .then((d) => setMetricas(d.metricas))
      .catch((e: Error) => setError(e.message));
    llamar<{ documentos: Documento[] }>("admision", "/admision/chequeo", { token: t })
      .then((d) => setDocs(d.documentos))
      .catch((e: Error) => setError(e.message));
  }, [t]);

  return (
    <Pantalla
      titulo="Admisión: cifras y lista de chequeo"
      servicio="admision"
      roles={["admision", "admin"]}
      hace={[
        "Muestra cuántas personas usaron el asistente y qué errores aparecen más.",
        "Muestra la lista de chequeo que usa el asistente para cada documento.",
      ]}
      noHace={[
        "No muestra documentos ni preguntas de los admitidos: no se guardan.",
        "No decide si un documento es válido: eso lo hace la revisión oficial.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      <h2>Cifras acumuladas</h2>
      {metricas && Object.keys(metricas).length === 0 ? <p>Aún no hay cifras.</p> : null}
      {metricas ? (
        <div className="tabla">
          <table>
            <tbody>
              {Object.entries(metricas).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">{ETIQUETAS[k] ?? k.replace("error_", "Errores de tipo: ").replaceAll("_", " ")}</th>
                  <td>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <h2>Lista de chequeo</h2>
      <p>
        <small>Se edita en el archivo config/admision/chequeo.yaml del servicio.</small>
      </p>
      {docs.map((d) => (
        <div key={d.clave}>
          <h3>{d.nombre}</h3>
          <small>{d.seccion}</small>
          <ul>
            {d.chequeo.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      ))}
    </Pantalla>
  );
}
