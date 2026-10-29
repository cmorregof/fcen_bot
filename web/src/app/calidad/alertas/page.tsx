"use client";

import { useEffect, useState } from "react";
import { Estado } from "@/components/Estado";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { Accion, porcentaje } from "@/lib/calidad";
import { useSesion } from "@/lib/sesion";

type Datos = {
  envio_activo: boolean;
  programas: { programa: string; acciones: Accion[] }[];
};

export default function Alertas() {
  const { token } = useSesion();
  const [datos, setDatos] = useState<Datos | null>(null);
  const [error, setError] = useState<string | null>(null);
  const t = token("calidad");
  useEffect(() => {
    if (!t) return;
    llamar<Datos>("calidad", "/calidad/alertas", { token: t }).then(setDatos).catch((e: Error) => setError(e.message));
  }, [t]);

  return (
    <Pantalla
      titulo="Alertas del plan"
      servicio="calidad"
      roles={["calidad", "admin"]}
      hace={["Muestra, por programa, las acciones vencidas, las marcadas «NO FUNCIONÓ» y las que vencen pronto."]}
      noHace={["No envía esta alerta a nadie: es solo una vista previa."]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {datos ? (
        <Mensaje tipo="info">
          El envío automático por Telegram está {datos.envio_activo ? "ACTIVO" : "APAGADO"}.
        </Mensaje>
      ) : null}
      {datos?.programas.map((p) => (
        <div key={p.programa}>
          <h2>{p.programa}</h2>
          {p.acciones.length === 0 ? (
            <p>Sin acciones vencidas ni próximas a vencer.</p>
          ) : (
            <ul>
              {p.acciones.map((a) => (
                <li key={a.codigo}>
                  <Estado valor={a.estado} /> {a.proxima ? "(vence pronto) " : ""}
                  {a.codigo}: {a.descripcion}. Avance {porcentaje(a.avance)}. Responsables: {a.responsables || "sin dato"}.
                  Fin: {a.fecha_fin ?? "sin fecha"}.
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </Pantalla>
  );
}
