"use client";

import { useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Resultado = {
  guardado: boolean;
  errores: string[];
  nuevas?: string[];
  actualizadas?: { tarea: string; cambios: string[] }[];
  sin_cambios?: number;
  ausentes?: string[];
};

export default function Importar() {
  const { token } = useSesion();
  const [archivo, setArchivo] = useState<File | null>(null);
  const [vista, setVista] = useState<Resultado | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const enviar = async (confirmar: boolean) => {
    if (!archivo) return;
    setOcupado(true);
    setError(null);
    const form = new FormData();
    form.append("archivo", archivo);
    if (confirmar) form.append("confirmar", "true");
    try {
      setVista(await llamar<Resultado>("calidad", "/calidad/importar", { token: token("calidad"), form }));
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(false);
  };

  return (
    <Pantalla
      titulo="Cargar el plan de mejoramiento"
      servicio="calidad"
      roles={["calidad", "admin"]}
      hace={[
        "Paso 1: lee el Excel y le muestra qué tareas son nuevas y cuáles cambian.",
        "Paso 2: solo si usted confirma, guarda los cambios. El historial conserva lo anterior.",
      ]}
      noHace={["No borra tareas.", "No guarda nada si el archivo tiene errores."]}
    >
      <label htmlFor="plan">
        Archivo del plan (.xlsx)
        <span className="ayuda">
          Columnas: programa, código, tarea, responsable_cargo, responsable_dependencia, fecha_limite y evidencia_esperada.
        </span>
      </label>
      <input
        id="plan"
        type="file"
        accept=".xlsx"
        onChange={(e) => {
          setArchivo(e.target.files?.[0] ?? null);
          setVista(null);
        }}
      />
      <div className="botones">
        <button type="button" disabled={!archivo || ocupado} onClick={() => enviar(false)}>
          {ocupado ? "Leyendo…" : "Revisar el archivo"}
        </button>
      </div>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {vista && vista.errores.length > 0 ? (
        <Mensaje tipo="error">
          No se guardó nada. Corrija el archivo:
          <ul>
            {vista.errores.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </Mensaje>
      ) : null}
      {vista && vista.errores.length === 0 ? (
        <>
          {vista.guardado ? <Mensaje tipo="exito">Plan guardado.</Mensaje> : <h2>Esto es lo que cambiaría</h2>}
          <ul>
            <li>{vista.nuevas?.length ?? 0} tareas nuevas</li>
            <li>{vista.actualizadas?.length ?? 0} tareas con cambios</li>
            <li>{vista.sin_cambios ?? 0} tareas sin cambios</li>
            {vista.ausentes && vista.ausentes.length > 0 ? (
              <li>
                {vista.ausentes.length} tareas guardadas no vienen en el archivo (no se borran): {vista.ausentes.join(", ")}
              </li>
            ) : null}
          </ul>
          {vista.actualizadas && vista.actualizadas.length > 0 ? (
            <>
              <h3>Tareas con cambios</h3>
              <ul>
                {vista.actualizadas.map((a) => (
                  <li key={a.tarea}>
                    {a.tarea}: cambia {a.cambios.join(", ")}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {!vista.guardado ? (
            <div className="botones">
              <button type="button" disabled={ocupado} onClick={() => enviar(true)}>
                Guardar el plan
              </button>
              <button type="button" className="secundario" onClick={() => setVista(null)}>
                Cancelar
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </Pantalla>
  );
}
