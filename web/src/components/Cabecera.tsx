"use client";

import Link from "next/link";
import { NOMBRE_ROL, useSesion } from "@/lib/sesion";

export function Cabecera() {
  const { sesiones, salir } = useSesion();
  const primera = Object.values(sesiones)[0];
  const roles = [...new Set(Object.values(sesiones).map((s) => NOMBRE_ROL[s.rol]))];
  return (
    <header className="cabecera">
      <Link href="/" className="marca">
        MemorIA <span>· FCEN</span>
      </Link>
      {primera ? (
        <div className="usuario">
          <span>
            {primera.nombre ?? primera.correo}
            <small>{roles.join(" · ")}</small>
          </span>
          <button type="button" className="boton secundario" onClick={salir}>
            Salir
          </button>
        </div>
      ) : null}
    </header>
  );
}
