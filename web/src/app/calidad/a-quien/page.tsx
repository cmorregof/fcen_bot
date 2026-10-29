"use client";

import { useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Tramite = { tema: string; dependencia: string; cargo: string; correo: string; vigencia: string };

export default function AQuien() {
  const { token } = useSesion();
  const [q, setQ] = useState("");
  const [datos, setDatos] = useState<{ resultados: Tramite[]; temas: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <Pantalla
      titulo="¿A quién acudo?"
      servicio="calidad"
      roles={["calidad", "admin"]}
      hace={["Busca en el directorio de trámites qué dependencia y qué cargo lo atiende."]}
      noHace={["No inventa responsables: si el tema no está en el directorio, se lo dice."]}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            setDatos(await llamar("calidad", `/calidad/a-quien?q=${encodeURIComponent(q)}`, { token: token("calidad") }));
          } catch (err) {
            setError((err as Error).message);
          }
        }}
      >
        <label htmlFor="tema">
          ¿Sobre qué trámite tiene dudas?
          <span className="ayuda">Ejemplo: certificado de notas, homologación, viáticos.</span>
        </label>
        <input id="tema" type="text" value={q} onChange={(e) => setQ(e.target.value)} required />
        <div className="botones">
          <button type="submit">Buscar</button>
        </div>
      </form>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {datos && datos.resultados.length === 0 ? (
        <Mensaje tipo="info">
          Ese tema no está en el directorio. Temas disponibles: {datos.temas.join(", ")}.
        </Mensaje>
      ) : null}
      {datos?.resultados.map((t) => (
        <div key={t.tema} className="tarjeta" style={{ marginBottom: "1rem" }}>
          <strong>{t.tema}</strong>
          <div>Dependencia: {t.dependencia}</div>
          <div>Cargo: {t.cargo}</div>
          <div>Correo: {t.correo}</div>
          <small>Vigencia del dato: {t.vigencia}</small>
        </div>
      ))}
    </Pantalla>
  );
}
