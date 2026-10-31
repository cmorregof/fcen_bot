"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Entidad = {
  id: number;
  nombre: string;
  tipo: string;
  sector: string;
  sitio_web: string;
  aliada: boolean;
  convenio: string;
  notas: string;
  ofertas: number;
};

const TIPOS: Record<string, string> = {
  empresa: "Empresa",
  entidad_publica: "Entidad pública",
  ong: "ONG o fundación",
  universidad: "Universidad o centro de investigación",
  otra: "Otra",
};

const VACIA = { nombre: "", tipo: "empresa", sector: "", sitio_web: "", aliada: false, convenio: "", notas: "" };

export default function Empresas() {
  const { token, tieneRol } = useSesion();
  const t = token("oportunidades");
  const responsable = tieneRol("oportunidades", "oportunidades", "admin");
  const [entidades, setEntidades] = useState<Entidad[]>([]);
  const [form, setForm] = useState(VACIA);
  const [editando, setEditando] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const cargar = useCallback(() => {
    if (!t) return;
    llamar<{ entidades: Entidad[] }>("oportunidades", "/oportunidades/entidades", { token: t })
      .then((d) => setEntidades(d.entidades))
      .catch((e: Error) => setError(e.message));
  }, [t]);

  useEffect(cargar, [cargar]);

  const guardar = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await llamar("oportunidades", editando ? `/oportunidades/entidades/${editando}` : "/oportunidades/entidades", {
        token: t,
        json: form,
        metodo: editando ? "PUT" : "POST",
      });
      setMensaje(editando ? "Entidad actualizada." : "Entidad registrada.");
      setForm(VACIA);
      setEditando(null);
      cargar();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Pantalla
      titulo="Empresas y entidades"
      servicio="oportunidades"
      roles={["oportunidades", "decanatura", "admin"]}
      hace={[
        "Lista las empresas y entidades, primero las aliadas, con cuántas ofertas suyas hay.",
        "Permite registrar o corregir una entidad (tipo, sector, sitio web, convenio). Las ofertas con ese nombre quedan ligadas.",
      ]}
      noHace={[
        "No guarda nombres, correos ni teléfonos de personas de contacto: solo datos de la entidad.",
        "No guarda datos de estudiantes ni de quién se postuló.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {mensaje ? <Mensaje tipo="exito">{mensaje}</Mensaje> : null}
      <div className="tabla">
        <table>
          <thead>
            <tr>
              <th>Entidad</th>
              <th>Tipo</th>
              <th>Sector</th>
              <th>Aliada</th>
              <th>Convenio</th>
              <th>Ofertas</th>
              {responsable ? <th></th> : null}
            </tr>
          </thead>
          <tbody>
            {entidades.map((e) => (
              <tr key={e.id}>
                <td>
                  {e.sitio_web ? (
                    <a href={e.sitio_web} target="_blank" rel="noopener noreferrer">
                      {e.nombre}
                    </a>
                  ) : (
                    e.nombre
                  )}
                </td>
                <td>{TIPOS[e.tipo] ?? e.tipo}</td>
                <td>{e.sector}</td>
                <td>{e.aliada ? "Sí" : "No"}</td>
                <td>{e.convenio}</td>
                <td>{e.ofertas}</td>
                {responsable ? (
                  <td>
                    <button
                      className="secundario"
                      onClick={() => {
                        setEditando(e.id);
                        setForm({
                          nombre: e.nombre,
                          tipo: e.tipo,
                          sector: e.sector,
                          sitio_web: e.sitio_web,
                          aliada: e.aliada,
                          convenio: e.convenio,
                          notas: e.notas,
                        });
                      }}
                    >
                      Editar
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {entidades.length === 0 ? <p>Todavía no hay entidades registradas.</p> : null}

      {responsable ? (
        <form onSubmit={guardar}>
          <h2>{editando ? `Editar entidad #${editando}` : "Registrar una entidad"}</h2>
          <label>
            Nombre
            <input type="text" required value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} />
          </label>
          <label>
            Tipo
            <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
              {Object.entries(TIPOS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label>
            Sector
            <input type="text" value={form.sector} onChange={(e) => setForm({ ...form, sector: e.target.value })} />
          </label>
          <label>
            Sitio web
            <input type="url" value={form.sitio_web} onChange={(e) => setForm({ ...form, sitio_web: e.target.value })} />
          </label>
          <label className="opcion">
            <input type="checkbox" checked={form.aliada} onChange={(e) => setForm({ ...form, aliada: e.target.checked })} />
            Entidad aliada de la Facultad
          </label>
          <label>
            Convenio (número y vigencia, si hay)
            <input type="text" value={form.convenio} onChange={(e) => setForm({ ...form, convenio: e.target.value })} />
          </label>
          <label>
            Notas (sin datos de personas)
            <textarea value={form.notas} onChange={(e) => setForm({ ...form, notas: e.target.value })} />
          </label>
          <div className="botones">
            <button type="submit">{editando ? "Guardar cambios" : "Registrar"}</button>
            {editando ? (
              <button
                type="button"
                className="secundario"
                onClick={() => {
                  setEditando(null);
                  setForm(VACIA);
                }}
              >
                Cancelar
              </button>
            ) : null}
          </div>
        </form>
      ) : null}
    </Pantalla>
  );
}
