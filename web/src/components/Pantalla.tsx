"use client";

import Link from "next/link";
import { Servicio } from "@/lib/api";
import { Rol, useSesion } from "@/lib/sesion";

type Props = {
  titulo: string;
  hace: string[];
  noHace: string[];
  children: React.ReactNode;
  // Si se indica, la pantalla solo se muestra a estos roles de ese servicio.
  servicio?: Servicio;
  roles?: Rol[];
};

export function Pantalla({ titulo, hace, noHace, children, servicio, roles }: Props) {
  const { cargando, tieneRol } = useSesion();
  if (cargando) return <p>Cargando…</p>;
  if (servicio && roles && !tieneRol(servicio, ...roles)) {
    return (
      <section>
        <h1>{titulo}</h1>
        <p className="mensaje error" role="alert">
          Esta pantalla no está habilitada para su usuario.
        </p>
        <Link href="/" className="boton secundario">
          Volver al inicio
        </Link>
      </section>
    );
  }
  return (
    <section>
      <h1>{titulo}</h1>
      <div className="alcance">
        <div>
          <h2>Qué hace esta pantalla</h2>
          <ul>
            {hace.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
        <div>
          <h2>Qué no hace</h2>
          <ul>
            {noHace.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      </div>
      {children}
    </section>
  );
}

export function Mensaje({ tipo, children }: { tipo: "error" | "exito" | "info"; children: React.ReactNode }) {
  return (
    <p className={`mensaje ${tipo}`} role={tipo === "error" ? "alert" : "status"}>
      {children}
    </p>
  );
}
