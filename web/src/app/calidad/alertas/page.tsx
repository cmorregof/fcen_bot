"use client";

import { useEffect, useState } from "react";
import { Estado } from "@/components/Estado";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Datos = {
  envio_activo: boolean;
  programas: { programa: string; tareas: { id: number; codigo: string; tarea: string; responsable: string; fecha_limite: string; estado: string }[] }[];
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
      hace={["Muestra, por programa, las tareas vencidas y las que vencen en las próximas 4 semanas."]}
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
          {p.tareas.length === 0 ? (
            <p>Sin tareas vencidas ni próximas a vencer.</p>
          ) : (
            <ul>
              {p.tareas.map((t) => (
                <li key={t.id}>
                  <Estado valor={t.estado} /> {t.codigo}: {t.tarea}. Responsable: {t.responsable}. Fecha límite: {t.fecha_limite}.
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </Pantalla>
  );
}
