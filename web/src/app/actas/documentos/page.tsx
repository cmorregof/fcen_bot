"use client";

import { useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Datos = { programas: { clave: string; nombre: string; casos: number }[]; sin_programa: number[] };

export default function Documentos() {
  const { token } = useSesion();
  const [datos, setDatos] = useState<Datos | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const t = token("actas");

  useEffect(() => {
    if (!t) return;
    llamar<Datos>("actas", "/actas/documentos", { token: t }).then(setDatos).catch((e: Error) => setError(e.message));
  }, [t]);

  const bajar = async (clave: string, nombre: string, tipo: "oficio" | "acta") => {
    setOcupado(clave + tipo);
    setError(null);
    try {
      const blob = await llamar<Blob>("actas", `/actas/documentos/${clave}/${tipo}`, { token: t });
      guardarArchivo(blob, `${tipo === "oficio" ? "Oficio" : "Acta"}_${nombre.replaceAll(" ", "_")}.docx`);
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(null);
  };

  return (
    <Pantalla
      titulo="Oficio y acta"
      servicio="actas"
      roles={["administrativa"]}
      hace={[
        "Arma, por programa, el borrador del oficio al Consejo y el acta del comité con los casos con ficha lista.",
        "Los descarga en Word para revisarlos y firmarlos.",
      ]}
      noHace={["No envía nada al Consejo.", "No cierra los casos: siguen en el borrador hasta que usted los cierre."]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {datos?.programas.length === 0 ? <p>No hay casos con ficha lista.</p> : null}
      {datos && datos.sin_programa.length > 0 ? (
        <Mensaje tipo="info">
          Estos casos no tienen programa y no entran al borrador: {datos.sin_programa.map((i) => `#${i}`).join(", ")}.
        </Mensaje>
      ) : null}
      {datos?.programas.map((p) => (
        <div key={p.clave} className="tarjeta" style={{ marginBottom: "1rem" }}>
          <strong>{p.nombre}</strong>
          {p.casos} caso(s)
          <div className="botones">
            <button type="button" disabled={ocupado !== null} onClick={() => bajar(p.clave, p.nombre, "oficio")}>
              {ocupado === p.clave + "oficio" ? "Preparando…" : "Descargar oficio"}
            </button>
            <button type="button" disabled={ocupado !== null} onClick={() => bajar(p.clave, p.nombre, "acta")}>
              {ocupado === p.clave + "acta" ? "Preparando…" : "Descargar acta"}
            </button>
          </div>
        </div>
      ))}
    </Pantalla>
  );
}
