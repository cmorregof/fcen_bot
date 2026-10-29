"use client";

import Link from "next/link";
import { Ingreso } from "@/components/Ingreso";
import { HERRAMIENTAS } from "@/lib/herramientas";
import { useSesion } from "@/lib/sesion";

export default function Inicio() {
  const { sesiones, cargando, tieneRol } = useSesion();
  if (cargando) return <p>Cargando…</p>;

  const ingresado = Object.keys(sesiones).length > 0;
  if (!ingresado) {
    return (
      <section>
        <h1>MemorIA</h1>
        <p>
          Herramientas de apoyo para la Facultad de Ciencias Exactas y Naturales. Ayudan a preparar y
          revisar; las decisiones siempre las toman las personas y las instancias competentes.
        </p>
        <div className="tarjetas">
          <div className="tarjeta">
            <Ingreso />
          </div>
          <div className="tarjeta">
            <h2>¿Es admitido o admitida?</h2>
            <p>Revise sus documentos antes de subirlos. No necesita cuenta.</p>
            <Link href="/admitidos" className="boton">
              Revisar mis documentos
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const mias = HERRAMIENTAS.filter((h) => tieneRol(h.servicio, ...h.roles));
  const decanatura = Object.values(sesiones).some((s) => s.rol === "decanatura" || s.rol === "admin");
  const admin = Object.values(sesiones).some((s) => s.rol === "admin");

  return (
    <section>
      <h1>¿Qué desea hacer?</h1>
      <div className="tarjetas">
        {mias.map((h) => (
          <Link key={h.ruta + h.titulo} href={h.ruta} className="tarjeta">
            <strong>{h.titulo}</strong>
            {h.descripcion}
          </Link>
        ))}
        {decanatura ? (
          <Link href="/tablero" className="tarjeta">
            <strong>Tablero de la Facultad</strong>
            Cifras de los tres servicios, solo lectura.
          </Link>
        ) : null}
        {admin ? (
          <Link href="/usuarios" className="tarjeta">
            <strong>Usuarios</strong>
            Autorizar correos y asignar roles.
          </Link>
        ) : null}
      </div>
      {mias.length === 0 && !decanatura && !admin ? (
        <p>Su usuario todavía no tiene herramientas asignadas.</p>
      ) : null}
    </section>
  );
}
