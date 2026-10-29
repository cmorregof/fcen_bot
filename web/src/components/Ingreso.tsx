"use client";

import Script from "next/script";
import { useState } from "react";
import { Mensaje } from "./Pantalla";
import { useSesion } from "@/lib/sesion";

type Google = {
  accounts: {
    id: {
      initialize: (o: { client_id: string; callback: (r: { credential: string }) => void }) => void;
      renderButton: (e: HTMLElement, o: Record<string, string | number>) => void;
    };
  };
};

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
const DEV = process.env.NEXT_PUBLIC_INGRESO_DEV === "true";

export function Ingreso() {
  const { ingresar } = useSesion();
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [correo, setCorreo] = useState("");

  const entrar = async (ruta: "/sesion" | "/sesion/dev", cuerpo: object) => {
    setOcupado(true);
    setError(null);
    setError(await ingresar(ruta, cuerpo));
    setOcupado(false);
  };

  const iniciarGoogle = () => {
    const g = (window as unknown as { google?: Google }).google;
    const caja = document.getElementById("boton-google");
    if (!g || !caja || !CLIENT_ID) return;
    g.accounts.id.initialize({
      client_id: CLIENT_ID,
      callback: (r) => entrar("/sesion", { credencial: r.credential }),
    });
    g.accounts.id.renderButton(caja, { size: "large", text: "signin_with", locale: "es", width: 320 });
  };

  return (
    <div>
      <h2>Ingresar como funcionario</h2>
      <p>Use su cuenta institucional @unal.edu.co. No se crea ninguna contraseña nueva.</p>
      {CLIENT_ID ? (
        <>
          <Script src="https://accounts.google.com/gsi/client" onLoad={iniciarGoogle} />
          <div id="boton-google" />
        </>
      ) : (
        <Mensaje tipo="info">El ingreso con Google todavía no está configurado.</Mensaje>
      )}
      {DEV ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            entrar("/sesion/dev", { correo });
          }}
        >
          <label htmlFor="correo-dev">
            Correo ficticio (solo para pruebas en este computador)
            <span className="ayuda">Ejemplo: calidad@unal.edu.co, administrativa@unal.edu.co, decana@unal.edu.co</span>
          </label>
          <input id="correo-dev" type="email" value={correo} onChange={(e) => setCorreo(e.target.value)} required />
          <div className="botones">
            <button type="submit" disabled={ocupado}>
              {ocupado ? "Ingresando…" : "Ingresar de prueba"}
            </button>
          </div>
        </form>
      ) : null}
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
    </div>
  );
}
