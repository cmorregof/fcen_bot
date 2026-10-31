"use client";

import { useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { SERVICIOS, Servicio, llamar } from "@/lib/api";
import { porcentaje } from "@/lib/calidad";
import { useSesion } from "@/lib/sesion";

type Tablero = {
  servicio: string;
  titulo: string;
  total: Record<string, number>;
  reprogramadas?: number;
  por_programa: { nombre: string; conteo: Record<string, number>; avance?: number | null; reprogramadas?: number }[];
};

const ETIQUETAS: Record<string, string> = {
  recibidos: "Casos recibidos",
  en_curso: "En curso",
  recomendar_aprobar: "Recomendar aprobar",
  recomendar_no_aprobar: "Recomendar no aprobar",
  "no funcionó": "Acciones «NO FUNCIONÓ»",
  vencida: "Acciones vencidas",
  "en curso": "En curso",
  "por iniciar": "Por iniciar",
  cumplida: "Cumplidas",
  consentimientos: "Personas atendidas",
  preguntas: "Preguntas",
  preguntas_sin_respuesta: "Preguntas sin respuesta en el listado",
  documentos_revisados: "Documentos revisados",
  documentos_con_errores: "Documentos con algo por corregir",
};

export default function PaginaTablero() {
  const { sesiones, token } = useSesion();
  const [tableros, setTableros] = useState<Tablero[]>([]);
  const [errores, setErrores] = useState<string[]>([]);

  useEffect(() => {
    // Cada servicio responde por sí mismo; ninguno consulta la base de otro.
    const servicios = (Object.keys(sesiones) as Servicio[]).filter((s) =>
      ["decanatura", "admin"].includes(sesiones[s]?.rol ?? ""),
    );
    Promise.all(
      servicios.map((s) =>
        llamar<Tablero>(s, `/${s}/tablero`, { token: token(s) }).catch((e: Error) => {
          setErrores((prev) => [...prev, `${SERVICIOS[s].nombre}: ${e.message}`]);
          return null;
        }),
      ),
    ).then((r) => setTableros(r.filter((t): t is Tablero => t !== null)));
  }, [sesiones, token]);

  const permitido = Object.values(sesiones).some((s) => s.rol === "decanatura" || s.rol === "admin");
  if (!permitido) {
    return (
      <Pantalla titulo="Tablero de la Facultad" hace={[]} noHace={[]}>
        <Mensaje tipo="error">Esta pantalla no está habilitada para su usuario.</Mensaje>
      </Pantalla>
    );
  }

  return (
    <Pantalla
      titulo="Tablero de la Facultad"
      hace={["Muestra cifras de los comités asesores, el plan de mejoramiento, la admisión y las oportunidades."]}
      noHace={["No muestra nombres de estudiantes ni documentos.", "No permite modificar nada."]}
    >
      {errores.map((e) => (
        <Mensaje key={e} tipo="error">
          {e}
        </Mensaje>
      ))}
      {tableros.map((t) => (
        <div key={t.servicio}>
          <h2>{t.titulo}</h2>
          <div className="tarjetas">
            {Object.entries(t.total).map(([k, v]) => (
              <div key={k} className="tarjeta">
                <span className="cifra">{v}</span>
                {ETIQUETAS[k] ?? k}
              </div>
            ))}
            {t.reprogramadas !== undefined ? (
              <div className="tarjeta">
                <span className="cifra">{t.reprogramadas}</span>Reprogramadas
              </div>
            ) : null}
          </div>
          {t.por_programa.length > 0 ? (
            <div className="tabla">
              <table>
                <thead>
                  <tr>
                    <th>{t.servicio === "actas" ? "Área curricular" : "Programa"}</th>
                    {Object.keys(t.por_programa[0].conteo).map((k) => (
                      <th key={k}>{ETIQUETAS[k] ?? k}</th>
                    ))}
                    {t.servicio === "calidad" ? (
                      <>
                        <th>Avance</th>
                        <th>Reprogramadas</th>
                      </>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {t.por_programa.map((p) => (
                    <tr key={p.nombre}>
                      <td>{p.nombre}</td>
                      {Object.values(p.conteo).map((v, i) => (
                        <td key={i}>{v}</td>
                      ))}
                      {t.servicio === "calidad" ? (
                        <>
                          <td>{porcentaje(p.avance)}</td>
                          <td>{p.reprogramadas ?? 0}</td>
                        </>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ))}
    </Pantalla>
  );
}
