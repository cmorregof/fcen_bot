"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ErrorApi, SERVICIOS, Servicio, llamar, servicioConfigurado } from "./api";

export type Rol = "administrativa" | "comite" | "secretaria" | "calidad" | "admision" | "decanatura" | "admin";

export type SesionServicio = {
  token: string;
  correo: string;
  nombre: string | null;
  rol: Rol;
  direccion: string | null;
};

type Sesiones = Partial<Record<Servicio, SesionServicio>>;

type Contexto = {
  sesiones: Sesiones;
  cargando: boolean;
  ingresar: (ruta: "/sesion" | "/sesion/dev", cuerpo: object) => Promise<string | null>;
  salir: () => void;
  token: (s: Servicio) => string | null;
  tieneRol: (s: Servicio, ...roles: Rol[]) => boolean;
};

const CLAVE = "memoria.sesiones";
const Ctx = createContext<Contexto | null>(null);

export function ProveedorSesion({ children }: { children: React.ReactNode }) {
  const [sesiones, setSesiones] = useState<Sesiones>({});
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    try {
      const guardado = sessionStorage.getItem(CLAVE);
      if (guardado) setSesiones(JSON.parse(guardado));
    } catch {
      /* sin almacenamiento: se ingresa de nuevo */
    }
    setCargando(false);
  }, []);

  const guardar = (nuevas: Sesiones) => {
    setSesiones(nuevas);
    try {
      sessionStorage.setItem(CLAVE, JSON.stringify(nuevas));
    } catch {
      /* ignorar */
    }
  };

  // Se pide sesión a cada servicio por separado: cada uno decide si el
  // correo está autorizado y con qué rol.
  const ingresar = useCallback(async (ruta: "/sesion" | "/sesion/dev", cuerpo: object) => {
    const nuevas: Sesiones = {};
    let ultimoError: string | null = null;
    await Promise.all(
      (Object.keys(SERVICIOS) as Servicio[]).filter(servicioConfigurado).map(async (s) => {
        try {
          nuevas[s] = await llamar<SesionServicio>(s, ruta, { json: cuerpo });
        } catch (e) {
          if (e instanceof ErrorApi && e.estado !== 403) ultimoError = e.message;
        }
      }),
    );
    if (Object.keys(nuevas).length === 0) {
      return ultimoError ?? "Su correo no está autorizado. Pida acceso a la persona que administra MemorIA.";
    }
    guardar(nuevas);
    return null;
  }, []);

  const salir = () => guardar({});

  const valor: Contexto = {
    sesiones,
    cargando,
    ingresar,
    salir,
    token: (s) => sesiones[s]?.token ?? null,
    tieneRol: (s, ...roles) => {
      const r = sesiones[s]?.rol;
      return r !== undefined && roles.includes(r);
    },
  };
  return <Ctx.Provider value={valor}>{children}</Ctx.Provider>;
}

export function useSesion(): Contexto {
  const c = useContext(Ctx);
  if (!c) throw new Error("useSesion fuera de ProveedorSesion");
  return c;
}

export const NOMBRE_ROL: Record<Rol, string> = {
  administrativa: "Administrativa de área curricular",
  comite: "Comité asesor",
  secretaria: "Secretaría de Facultad",
  calidad: "Calidad",
  admision: "Responsable de admisión",
  decanatura: "Decanatura",
  admin: "Administración de usuarios",
};
