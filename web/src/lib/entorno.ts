"use client";

import { useEffect, useState } from "react";
import { PRACTICA, SERVICIOS, Servicio, servicioConfigurado } from "./api";

// ¿Es el entorno de práctica? Sí si este despliegue se construyó con
// NEXT_PUBLIC_PRACTICA=true o si algún backend al que apunta lo declara
// (MEMORIA_PRACTICA=true): así el banner sale aunque alguien apunte la web de
// producción a un backend de práctica.
export function usePractica(): boolean {
  const [practica, setPractica] = useState(PRACTICA);
  useEffect(() => {
    if (PRACTICA) return;
    let vigente = true;
    (Object.keys(SERVICIOS) as Servicio[]).filter(servicioConfigurado).forEach((s) => {
      fetch(`${SERVICIOS[s].url}/api/web/entorno`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (vigente && d?.practica === true) setPractica(true);
        })
        .catch(() => {
          /* sin conexión: se muestra como producción */
        });
    });
    return () => {
      vigente = false;
    };
  }, []);
  return practica;
}
