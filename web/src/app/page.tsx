"use client";

import Link from "next/link";
import { Icono, NombreIcono } from "@/components/Icono";
import { Ingreso } from "@/components/Ingreso";
import { Servicio } from "@/lib/api";
import { HERRAMIENTAS } from "@/lib/herramientas";
import { useSesion } from "@/lib/sesion";

const GRUPO: Record<Servicio, string> = {
  actas: "Comités asesores",
  calidad: "Calidad",
  admision: "Admisión",
  oportunidades: "Oportunidades",
};

const ICONO: Record<string, NombreIcono> = {
  "/actas": "carpeta",
  "/actas/documentos": "documento",
  "/actas/consejo": "balanza",
  "/secretaria": "campana",
  "/indicadores": "grafica",
  "/calidad": "lista",
  "/calidad/importar": "subir",
  "/calidad/soportes": "lupa",
  "/calidad/avance": "lapiz",
  "/calidad/alertas": "alerta",
  "/calidad/a-quien": "pregunta",
  "/admision": "birrete",
  "/oportunidades": "maletin",
  "/oportunidades/ofertas": "lista",
  "/oportunidades/empresas": "edificio",
  "/oportunidades/boletin": "periodico",
};

type Enlace = { ruta: string; titulo: string; descripcion: string; icono: NombreIcono };

function Herramienta({ e }: { e: Enlace }) {
  return (
    <li>
      <Link href={e.ruta} className="herramienta">
        <span className="icono">
          <Icono nombre={e.icono} />
        </span>
        <span className="texto">
          <strong>{e.titulo}</strong>
          <span>{e.descripcion}</span>
        </span>
        <span className="flecha">
          <Icono nombre="flecha" tamano={20} />
        </span>
      </Link>
    </li>
  );
}

export default function Inicio() {
  const { sesiones, cargando, tieneRol } = useSesion();
  if (cargando) return <p>Cargando…</p>;

  const ingresado = Object.keys(sesiones).length > 0;
  if (!ingresado) {
    return (
      <section>
        <div className="portada">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/memoria.webp" alt="" />
          <div className="portada-texto">
            <p className="institucion">Universidad Nacional de Colombia · Sede Manizales · FCEN</p>
            <h1>
              Memor<span className="ia">IA</span>
            </h1>
            <p className="lema">
              Menos tiempo en trámites,
              <br />
              más tiempo para los estudiantes.
            </p>
          </div>
        </div>
        <div className="entrada">
          <div>
            <Ingreso />
          </div>
          <div className="tarjeta">
            <h2>¿Es admitido o admitida?</h2>
            <p>Revise sus documentos antes de subirlos. No necesita cuenta.</p>
            <Link href="/admitidos" className="boton secundario">
              Revisar mis documentos
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const mias = HERRAMIENTAS.filter((h) => tieneRol(h.servicio, ...h.roles));
  const decanatura = Object.values(sesiones).some((s) => s.rol === "decanatura" || s.rol === "admin");
  const admin = Object.values(sesiones).some((s) => s.rol === "admin" || s.admin);
  const nombre = Object.values(sesiones)[0]?.nombre?.split(" ")[0];

  const grupos: { titulo: string; enlaces: Enlace[] }[] = (Object.keys(GRUPO) as Servicio[])
    .map((s) => ({
      titulo: GRUPO[s],
      enlaces: mias
        .filter((h) => h.servicio === s)
        .map((h) => ({ ruta: h.ruta, titulo: h.titulo, descripcion: h.descripcion, icono: ICONO[h.ruta] ?? "documento" })),
    }))
    .filter((g) => g.enlaces.length > 0);

  const facultad: Enlace[] = [];
  if (decanatura) {
    facultad.push({ ruta: "/tablero", titulo: "Tablero de la Facultad", descripcion: "Cifras de todos los servicios.", icono: "tablero" });
  }
  if (admin) {
    facultad.push({ ruta: "/usuarios", titulo: "Usuarios", descripcion: "Autorizar correos y asignar roles.", icono: "personas" });
  }
  if (facultad.length > 0) grupos.push({ titulo: "Facultad", enlaces: facultad });

  return (
    <section>
      <h1>{nombre ? `Hola, ${nombre}` : "Inicio"}</h1>
      <p className="saludo">¿Qué desea hacer hoy?</p>
      {grupos.map((g) => (
        <section key={g.titulo} className="grupo-herramientas" aria-label={g.titulo}>
          {grupos.length > 1 ? <h2>{g.titulo}</h2> : null}
          <ul className="herramientas">
            {g.enlaces.map((e) => (
              <Herramienta key={e.ruta + e.titulo} e={e} />
            ))}
          </ul>
        </section>
      ))}
      {grupos.length === 0 ? <p>Su usuario todavía no tiene herramientas asignadas.</p> : null}
    </section>
  );
}
