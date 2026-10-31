"use client";

import { useEffect, useState } from "react";
import { PRACTICA, SERVICIOS, Servicio, servicioConfigurado } from "./api";

// ¿Es el entorno de práctica? Sí si este despliegue se construyó con
// NEXT_PUBLIC_PRACTICA=true o si algún backend al que apunta lo declara
// (MEMORIA_PRACTICA=true): así el banner sale aunque alguien apunte la web de
// producción a un backend de práctica.
let consulta: Promise<boolean> | null = null;

// Una sola consulta por carga de página, sin importar cuántos componentes lo usen.
function consultar(): Promise<boolean> {
  consulta ??= Promise.all(
    (Object.keys(SERVICIOS) as Servicio[]).filter(servicioConfigurado).map((s) =>
      fetch(`${SERVICIOS[s].url}/api/web/entorno`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => d?.practica === true)
        .catch(() => false), // sin conexión: se muestra como producción
    ),
  ).then((r) => r.some(Boolean));
  return consulta;
}

export function usePractica(): boolean {
  const [practica, setPractica] = useState(PRACTICA);
  useEffect(() => {
    if (PRACTICA) return;
    let vigente = true;
    consultar().then((p) => {
      if (vigente && p) setPractica(true);
    });
    return () => {
      vigente = false;
    };
  }, []);
  return practica;
}
