"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Valores = Record<string, number | null>;
type Fuente = { nombre: string; definicion: string; fuente: string };
type Plazo = { dias: number; fuente: string } | null;
type Reporte = {
  periodo: { etiqueta: string; texto: string; desde: string; hasta: string };
  alcance: string;
  corte: string;
  plazos: { comite: Plazo; consejo: Plazo };
  total: Valores;
  dimensiones: { nombre: string; definicion: string; fuente: string; grupos: { nombre: string; indicadores: Valores }[] }[];
  fuentes: Record<string, Fuente>;
  nota: string;
};

// Columnas de las tablas por grupo. El Excel trae todas (config/indicadores.yaml).
const COLUMNAS: { clave: string; titulo: string }[] = [
  { clave: "recibidos", titulo: "Recibidos" },
  { clave: "recomendados", titulo: "Recomendados" },
  { clave: "decididos_consejo", titulo: "Decididos por el Consejo" },
  { clave: "consejo_aplazo", titulo: "Aplazados" },
  { clave: "pendientes_acta", titulo: "Pendientes de acta" },
  { clave: "dias_comite_mediana", titulo: "Días a la recomendación (mediana)" },
  { clave: "dias_comite_p90", titulo: "Días a la recomendación (p90)" },
  { clave: "dias_consejo_mediana", titulo: "Días al Consejo (mediana)" },
  { clave: "dias_consejo_p90", titulo: "Días al Consejo (p90)" },
  { clave: "sin_fecha_recomendacion", titulo: "Recomendados sin fecha" },
  { clave: "fechas_inconsistentes", titulo: "Fechas inconsistentes" },
  { clave: "fuera_plazo_comite", titulo: "Fuera de plazo (comité)" },
  { clave: "fuera_plazo_consejo", titulo: "Fuera de plazo (Consejo)" },
];

const cifra = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(1).replace(".", ",");

function Tarjeta({ titulo, valor, detalle, fuente }: { titulo: string; valor: string; detalle?: string; fuente: Fuente }) {
  return (
    <div className="tarjeta">
      <span className="cifra">{valor}</span>
      <strong>{titulo}</strong>
      {detalle ? <span>{detalle}</span> : null}
      <span className="ayuda">Fuente: {fuente.fuente}</span>
    </div>
  );
}

export default function PaginaIndicadores() {
  const { token, sesiones } = useSesion();
  const t = token("actas");
  const [periodo, setPeriodo] = useState("");
  // El Excel se pide con el periodo de la última consulta, no con lo escrito.
  const [consultado, setConsultado] = useState("");
  const [reporte, setReporte] = useState<Reporte | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);

  const consultar = useCallback(
    async (p: string) => {
      if (!t) return;
      setError(null);
      setCargando(true);
      try {
        setReporte(await llamar<Reporte>("actas", `/actas/indicadores?periodo=${encodeURIComponent(p)}`, { token: t }));
        setConsultado(p);
      } catch (e) {
        setReporte(null);
        setError((e as Error).message);
      } finally {
        setCargando(false);
      }
    },
    [t],
  );

  useEffect(() => {
    consultar("");
  }, [consultar]);

  const descargar = async () => {
    if (!reporte) return;
    try {
      const datos = await llamar<Blob>("actas", `/actas/indicadores/xlsx?periodo=${encodeURIComponent(consultado)}`, {
        token: t,
      });
      guardarArchivo(datos, `indicadores-actas-${reporte.periodo.desde}.xlsx`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const descargarSuit = async () => {
    setError(null);
    try {
      const ano = new Date().getFullYear();
      const datos = await llamar<Blob>("actas", `/actas/suit/xlsx?ano=${ano}`, { token: t });
      guardarArchivo(datos, `datos_suit_fcen_${ano}.xlsx`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const area = sesiones.actas?.rol === "administrativa";
  const f = reporte?.fuentes;
  const v = reporte?.total;
  const plazo = (clave: string, p: Plazo) =>
    p ? `${cifra(v?.[clave])} (plazo ${p.dias} días)` : "Sin plazo configurado";

  return (
    <Pantalla
      titulo="Indicadores"
      servicio="actas"
      roles={["administrativa", "decanatura", "admin"]}
      hace={[
        area
          ? "Muestra los indicadores de su área curricular: casos, recomendaciones, decisiones del Consejo y tiempos."
          : "Muestra los indicadores de toda la Facultad: casos, recomendaciones, decisiones del Consejo y tiempos.",
        "Cada cifra trae su fuente. Permite descargar el Excel con la pestaña «fuentes».",
      ]}
      noHace={[
        "No muestra nombres de estudiantes ni documentos.",
        "No cuenta como aprobado un caso sin acta del Consejo: figura como pendiente de acta.",
        "No modifica nada.",
      ]}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          consultar(periodo);
        }}
      >
        <label htmlFor="periodo">
          Periodo
          <span className="ayuda">Un mes (2026-10), un año (2026) o vacío para el periodo académico en curso.</span>
        </label>
        <input id="periodo" value={periodo} onChange={(e) => setPeriodo(e.target.value)} placeholder="2026-10" />
        <div className="botones">
          <button type="submit" disabled={cargando}>
            {cargando ? "Consultando…" : "Consultar"}
          </button>
          <button type="button" className="secundario" onClick={descargar} disabled={!reporte}>
            Descargar Excel
          </button>
          {!area ? (
            <button type="button" className="secundario" onClick={descargarSuit}>
              Datos SUIT del año (Excel)
            </button>
          ) : null}
        </div>
      </form>

      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}

      {reporte && f && v ? (
        <>
          <h2>
            {reporte.alcance} · {reporte.periodo.texto}
          </h2>
          <p className="ayuda">Corte: {reporte.corte}. Casos recibidos en el periodo, con su estado a la fecha de corte.</p>
          <div className="tarjetas">
            <Tarjeta titulo="Casos recibidos" valor={cifra(v.recibidos)} fuente={f.recibidos} />
            <Tarjeta
              titulo="Recomendados por el comité"
              valor={cifra(v.recomendados)}
              detalle={`${cifra(v.recomendar_aprobar)} recomendar aprobar · ${cifra(v.recomendar_no_aprobar)} recomendar no aprobar`}
              fuente={f.recomendados}
            />
            <Tarjeta
              titulo="Decididos por el Consejo"
              valor={cifra(v.decididos_consejo)}
              detalle={`Aprobó ${cifra(v.consejo_aprobo)} · no aprobó ${cifra(v.consejo_no_aprobo)} · aplazó ${cifra(v.consejo_aplazo)}${v.consejo_otro ? ` · otra ${cifra(v.consejo_otro)}` : ""}`}
              fuente={f.decididos_consejo}
            />
            <Tarjeta titulo="Pendientes de acta del Consejo" valor={cifra(v.pendientes_acta)} fuente={f.pendientes_acta} />
            <Tarjeta
              titulo="Días de la solicitud a la recomendación"
              valor={cifra(v.dias_comite_mediana)}
              detalle={`Mediana · percentil 90: ${cifra(v.dias_comite_p90)} · ${cifra(v.dias_comite_casos)} casos`}
              fuente={f.dias_comite_mediana}
            />
            <Tarjeta
              titulo="Días de la recomendación a la decisión del Consejo"
              valor={cifra(v.dias_consejo_mediana)}
              detalle={`Mediana · percentil 90: ${cifra(v.dias_consejo_p90)} · ${cifra(v.dias_consejo_casos)} casos`}
              fuente={f.dias_consejo_mediana}
            />
            <Tarjeta
              titulo="Fuera de plazo"
              valor={`${cifra(v.fuera_plazo_comite)} / ${cifra(v.fuera_plazo_consejo)}`}
              detalle={`Comité: ${plazo("fuera_plazo_comite", reporte.plazos.comite)} · Consejo: ${plazo("fuera_plazo_consejo", reporte.plazos.consejo)}`}
              fuente={f.fuera_plazo_comite}
            />
          </div>

          {reporte.dimensiones.map((d) => (
            <div key={d.nombre}>
              <h2>Por {d.nombre.toLowerCase()}</h2>
              <p className="ayuda">
                {d.definicion} Fuente: {d.fuente}
              </p>
              <div className="tabla">
                <table>
                  <thead>
                    <tr>
                      <th>{d.nombre}</th>
                      {COLUMNAS.map((c) => (
                        <th key={c.clave} title={f[c.clave]?.definicion}>
                          {c.titulo}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {d.grupos.map((g) => (
                      <tr key={g.nombre}>
                        <td>{g.nombre}</td>
                        {COLUMNAS.map((c) => (
                          <td key={c.clave}>{cifra(g.indicadores[c.clave])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <h2>Fuentes y definiciones</h2>
          <dl>
            {Object.entries(f).map(([clave, fuente]) => (
              <div key={clave}>
                <dt>
                  <strong>{fuente.nombre}</strong>
                </dt>
                <dd>
                  {fuente.definicion} <span className="ayuda">Fuente: {fuente.fuente}</span>
                </dd>
              </div>
            ))}
          </dl>
          <Mensaje tipo="info">{reporte.nota}</Mensaje>
        </>
      ) : null}
    </Pantalla>
  );
}
