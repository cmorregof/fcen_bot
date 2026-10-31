"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { Catalogos, MODALIDADES, Oferta, nombresProgramas } from "@/lib/oportunidades";
import { useSesion } from "@/lib/sesion";

type Fuente = {
  clave: string;
  nombre: string;
  url: string;
  activa: boolean;
  tipos: string[];
  justificacion: string;
  terminos_url: string;
};

type Corrida = {
  id: number;
  origen: string;
  estado: string;
  iniciada: string;
  nuevas: number;
  verificadas: number;
  en_revision: number;
  costo_usd: number;
  error: string | null;
  fuentes: { clave: string; estado: string; detalle?: string; nuevas?: number }[];
};

type DatosFuentes = {
  vigia_activa: boolean;
  fuentes: Fuente[];
  excluidas: { nombre: string; motivo: string }[];
  corridas: Corrida[];
};

const VACIA = {
  titulo: "",
  entidad: "",
  tipo: "practica",
  url: "",
  programas: [] as string[],
  fecha_cierre: "",
  modalidad: "sin_dato",
  lugar: "",
  resumen: "",
  requisitos: "",
};

export default function Ofertas() {
  const { token, tieneRol } = useSesion();
  const t = token("oportunidades");
  const responsable = tieneRol("oportunidades", "oportunidades", "admin");
  const [ofertas, setOfertas] = useState<Oferta[]>([]);
  const [catalogos, setCatalogos] = useState<Catalogos | null>(null);
  const [fuentes, setFuentes] = useState<DatosFuentes | null>(null);
  const [estado, setEstado] = useState("");
  const [programa, setPrograma] = useState("");
  const [nueva, setNueva] = useState(VACIA);
  const [error, setError] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const cargar = useCallback(() => {
    if (!t) return;
    const params = new URLSearchParams();
    if (estado) params.set("estado", estado);
    if (programa) params.set("programa", programa);
    Promise.all([
      llamar<{ ofertas: Oferta[] }>("oportunidades", `/oportunidades/ofertas?${params}`, { token: t }),
      llamar<Catalogos>("oportunidades", "/oportunidades/catalogos", { token: t }),
      llamar<DatosFuentes>("oportunidades", "/oportunidades/fuentes", { token: t }),
    ])
      .then(([o, c, f]) => {
        setOfertas(o.ofertas);
        setCatalogos(c);
        setFuentes(f);
      })
      .catch((e: Error) => setError(e.message));
  }, [t, estado, programa]);

  useEffect(cargar, [cargar]);

  const vigia = async () => {
    setError(null);
    try {
      const r = await llamar<{ corrida: number }>("oportunidades", "/oportunidades/vigia", { token: t, metodo: "POST" });
      setMensaje(`Vigía #${r.corrida} en marcha. Actualice en unos minutos para ver el resultado.`);
      cargar();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const registrar = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const r = await llamar<{ id: number; motivos: string[] }>("oportunidades", "/oportunidades/ofertas", {
        token: t,
        json: { ...nueva, fecha_cierre: nueva.fecha_cierre || null },
      });
      setMensaje(`Oferta #${r.id} registrada. Quedó en la cola de revisión.`);
      setNueva(VACIA);
      cargar();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Pantalla
      titulo="Ofertas y fuentes"
      servicio="oportunidades"
      roles={["oportunidades", "decanatura", "admin"]}
      hace={[
        "Lista todas las ofertas por estado y programa, con quién las verificó o aprobó.",
        "Muestra las fuentes de la vigía, por qué se pueden consultar y las que se excluyeron.",
        "Muestra las últimas corridas de la vigía con su costo, y permite correrla ahora.",
        "Permite registrar a mano una oferta que llegó por otro medio.",
      ]}
      noHace={[
        "No consulta fuentes apagadas ni sitios cuyo robots.txt lo prohíba; no inicia sesión en ningún portal.",
        "No aprueba ni publica: eso pasa por la cola de revisión y el boletín.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {mensaje ? <Mensaje tipo="exito">{mensaje}</Mensaje> : null}

      <h2>Ofertas</h2>
      <div className="botones">
        <label>
          Estado
          <select value={estado} onChange={(e) => setEstado(e.target.value)}>
            <option value="">Todos</option>
            {Object.entries(catalogos?.estados ?? {}).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Programa
          <select value={programa} onChange={(e) => setPrograma(e.target.value)}>
            <option value="">Todos</option>
            {Object.entries(catalogos?.programas ?? {}).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="tabla">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Oferta</th>
              <th>Tipo</th>
              <th>Programas</th>
              <th>Cierre</th>
              <th>Estado</th>
              <th>Quién y cuándo</th>
            </tr>
          </thead>
          <tbody>
            {ofertas.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td>
                  <a href={o.url} target="_blank" rel="noopener noreferrer">
                    {o.titulo}
                  </a>
                  <br />
                  {o.entidad} · {MODALIDADES[o.modalidad]}
                </td>
                <td>{catalogos?.tipos[o.tipo] ?? o.tipo}</td>
                <td>{nombresProgramas(o, catalogos)}</td>
                <td>{o.fecha_cierre ?? "sin fecha"}</td>
                <td>
                  {catalogos?.estados[o.estado] ?? o.estado}
                  {o.motivo_descarte ? ` (${o.motivo_descarte})` : ""}
                </td>
                <td>
                  {o.verificado_por ? `Verificó: ${o.verificado_por} (${o.verificado})` : ""}
                  {o.aprobado_por ? <><br />Aprobó: {o.aprobado_por} ({o.aprobado})</> : null}
                  {o.descartado_por ? <><br />Descartó: {o.descartado_por}</> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ofertas.length === 0 ? <p>No hay ofertas con ese filtro.</p> : null}

      <h2>Fuentes de la vigía</h2>
      {fuentes ? (
        <Mensaje tipo="info">
          La vigía semanal automática está {fuentes.vigia_activa ? "ACTIVA" : "APAGADA"}. Solo se consultan las fuentes
          activas.
        </Mensaje>
      ) : null}
      <ul>
        {fuentes?.fuentes.map((f) => (
          <li key={f.clave}>
            <strong>{f.nombre}</strong> — {f.activa ? "activa" : "apagada"} ·{" "}
            <a href={f.url} target="_blank" rel="noopener noreferrer">
              {f.url}
            </a>
            <br />
            {f.justificacion}
          </li>
        ))}
      </ul>
      {fuentes && fuentes.excluidas.length > 0 ? (
        <>
          <h3>Fuentes que no se consultan</h3>
          <ul>
            {fuentes.excluidas.map((f) => (
              <li key={f.nombre}>
                <strong>{f.nombre}</strong>: {f.motivo}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <h2>Últimas corridas</h2>
      {responsable ? (
        <button onClick={vigia}>Correr la vigía ahora</button>
      ) : null}
      <ul>
        {fuentes?.corridas.map((c) => (
          <li key={c.id}>
            #{c.id} · {c.iniciada} · {c.origen} · {c.estado}: {c.nuevas} nuevas, {c.verificadas} verificadas,{" "}
            {c.en_revision} a la cola · USD {c.costo_usd.toFixed(3)}
            {c.error ? ` · error: ${c.error}` : ""}
            <ul>
              {c.fuentes.map((f) => (
                <li key={f.clave}>
                  {f.clave}: {f.estado}
                  {f.detalle ? ` (${f.detalle})` : ""}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>

      {responsable ? (
        <form onSubmit={registrar}>
          <h2>Registrar una oferta a mano</h2>
          <label>
            Título
            <input type="text" required value={nueva.titulo} onChange={(e) => setNueva({ ...nueva, titulo: e.target.value })} />
          </label>
          <label>
            Empresa o entidad
            <input type="text" required value={nueva.entidad} onChange={(e) => setNueva({ ...nueva, entidad: e.target.value })} />
          </label>
          <label>
            Enlace de la oferta
            <input type="url" required value={nueva.url} onChange={(e) => setNueva({ ...nueva, url: e.target.value })} />
          </label>
          <label>
            Tipo
            <select value={nueva.tipo} onChange={(e) => setNueva({ ...nueva, tipo: e.target.value })}>
              {Object.entries(catalogos?.tipos ?? {}).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label>
            Modalidad
            <select value={nueva.modalidad} onChange={(e) => setNueva({ ...nueva, modalidad: e.target.value })}>
              {Object.entries(MODALIDADES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>Programas FCEN</legend>
            {Object.entries(catalogos?.programas ?? {}).map(([k, v]) => (
              <label key={k} className="opcion">
                <input
                  type="checkbox"
                  checked={nueva.programas.includes(k)}
                  onChange={(e) =>
                    setNueva({
                      ...nueva,
                      programas: e.target.checked ? [...nueva.programas, k] : nueva.programas.filter((p) => p !== k),
                    })
                  }
                />
                {v}
              </label>
            ))}
          </fieldset>
          <label>
            Fecha de cierre
            <input type="date" value={nueva.fecha_cierre} onChange={(e) => setNueva({ ...nueva, fecha_cierre: e.target.value })} />
          </label>
          <label>
            Lugar
            <input type="text" value={nueva.lugar} onChange={(e) => setNueva({ ...nueva, lugar: e.target.value })} />
          </label>
          <label>
            Resumen (sin nombres ni datos de contacto de personas)
            <textarea value={nueva.resumen} onChange={(e) => setNueva({ ...nueva, resumen: e.target.value })} />
          </label>
          <label>
            Requisitos
            <textarea value={nueva.requisitos} onChange={(e) => setNueva({ ...nueva, requisitos: e.target.value })} />
          </label>
          <button type="submit">Registrar</button>
        </form>
      ) : null}
    </Pantalla>
  );
}
