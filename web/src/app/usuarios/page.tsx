"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { SERVICIOS, Servicio, llamar } from "@/lib/api";
import { NOMBRE_ROL, Rol, useSesion } from "@/lib/sesion";

type Lista = {
  roles: Rol[];
  direcciones: Record<string, string>;
  usuarios: { correo: string; nombre: string | null; rol: Rol; direccion: string | null; activo: boolean }[];
};

function UsuariosServicio({ servicio }: { servicio: Servicio }) {
  const { token } = useSesion();
  const t = token(servicio);
  const [lista, setLista] = useState<Lista | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [correo, setCorreo] = useState("");
  const [nombre, setNombre] = useState("");
  const [rol, setRol] = useState<Rol | "">("");
  const [direccion, setDireccion] = useState("");

  const cargar = useCallback(() => {
    llamar<Lista>(servicio, "/usuarios", { token: t }).then(setLista).catch((e: Error) => setError(e.message));
  }, [servicio, t]);
  useEffect(cargar, [cargar]);

  const conArea = rol === "administrativa" || rol === "comite";

  return (
    <div>
      <h2>{SERVICIOS[servicio].nombre}</h2>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {lista ? (
        <div className="tabla">
          <table>
            <thead>
              <tr>
                <th>Correo</th>
                <th>Rol</th>
                <th>Estado</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {lista.usuarios.map((u) => (
                <tr key={u.correo}>
                  <td>
                    {u.correo}
                    {u.nombre ? <div><small>{u.nombre}</small></div> : null}
                  </td>
                  <td>
                    {NOMBRE_ROL[u.rol]}
                    {u.direccion ? <div><small>{lista.direcciones[u.direccion]}</small></div> : null}
                  </td>
                  <td>{u.activo ? "Autorizado" : "Retirado"}</td>
                  <td>
                    {u.activo ? (
                      <button
                        type="button"
                        className="secundario"
                        onClick={async () => {
                          if (!confirm(`¿Retirar el acceso de ${u.correo}?`)) return;
                          await llamar(servicio, `/usuarios/${encodeURIComponent(u.correo)}`, { token: t, metodo: "DELETE" }).catch(
                            (e: Error) => setError(e.message),
                          );
                          cargar();
                        }}
                      >
                        Retirar acceso
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {lista ? (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            try {
              await llamar(servicio, "/usuarios", {
                token: t,
                json: { correo, nombre: nombre || null, rol, direccion: conArea ? direccion : null },
              });
              setCorreo("");
              setNombre("");
              cargar();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <h3>Autorizar un correo</h3>
          <label htmlFor={`correo-${servicio}`}>Correo institucional</label>
          <input id={`correo-${servicio}`} type="email" value={correo} onChange={(e) => setCorreo(e.target.value)} required />
          <label htmlFor={`nombre-${servicio}`}>Nombre (opcional)</label>
          <input id={`nombre-${servicio}`} type="text" value={nombre} onChange={(e) => setNombre(e.target.value)} />
          <label htmlFor={`rol-${servicio}`}>Rol</label>
          <select id={`rol-${servicio}`} value={rol} onChange={(e) => setRol(e.target.value as Rol)} required>
            <option value="">Elija el rol</option>
            {lista.roles.map((r) => (
              <option key={r} value={r}>
                {NOMBRE_ROL[r]}
              </option>
            ))}
          </select>
          {conArea ? (
            <>
              <label htmlFor={`dir-${servicio}`}>Área curricular</label>
              <select id={`dir-${servicio}`} value={direccion} onChange={(e) => setDireccion(e.target.value)} required>
                <option value="">Elija el área</option>
                {Object.entries(lista.direcciones).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </>
          ) : null}
          <div className="botones">
            <button type="submit">Autorizar</button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

export default function Usuarios() {
  const { sesiones } = useSesion();
  const servicios = (Object.keys(sesiones) as Servicio[]).filter((s) => sesiones[s]?.rol === "admin");
  return (
    <Pantalla
      titulo="Usuarios"
      hace={[
        "Autoriza correos @unal.edu.co y les asigna un rol en cada servicio.",
        "Retira el acceso: la persona deja de entrar de inmediato.",
      ]}
      noHace={["No crea contraseñas: cada persona entra con su cuenta institucional de Google."]}
    >
      {servicios.length === 0 ? <Mensaje tipo="error">Esta pantalla no está habilitada para su usuario.</Mensaje> : null}
      {servicios.map((s) => (
        <UsuariosServicio key={s} servicio={s} />
      ))}
    </Pantalla>
  );
}
