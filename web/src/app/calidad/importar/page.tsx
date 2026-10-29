"use client";

import { useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Resultado = {
  guardado: boolean;
  errores: string[];
  programa?: string;
  plan_nuevo?: boolean;
  objetivos?: number;
  acciones?: number;
  tareas?: number;
  avance?: number | null;
  cronogramas?: number[];
  alertas?: string[];
  cortes_nuevos?: number;
  cortes_cambiados?: number;
  nuevas?: string[];
  actualizadas?: { accion: string; cambios: string[] }[];
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
        "Paso 1: lee la plantilla institucional y le muestra el resumen: objetivos, acciones, avance y qué cambia.",
        "Paso 2: solo si usted confirma, guarda los cambios. El historial conserva lo anterior.",
      ]}
      noHace={["No borra acciones.", "No guarda nada hasta que usted confirme, ni si el archivo no se puede leer."]}
    >
      <label htmlFor="plan">
        Archivo del plan (.xlsx)
        <span className="ayuda">
          La plantilla institucional del plan de mejoramiento (hojas de formulación, plan, cronogramas y evaluación).
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
          No se guardó nada. No se pudo leer el plan:
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
          <p>
            <strong>{vista.programa}</strong>
            {vista.plan_nuevo ? " (plan nuevo)" : ""}: {vista.objetivos} objetivos, {vista.acciones} acciones, {vista.tareas}{" "}
            tareas en el cronograma
            {vista.cronogramas && vista.cronogramas.length > 0 ? ` (${vista.cronogramas.join(", ")})` : ""}. Avance
            promedio: {vista.avance === null || vista.avance === undefined ? "sin dato" : `${Math.round(vista.avance)} %`}.
          </p>
          <ul>
            <li>{vista.nuevas?.length ?? 0} acciones nuevas</li>
            <li>{vista.actualizadas?.length ?? 0} acciones con cambios</li>
            <li>{vista.sin_cambios ?? 0} acciones sin cambios</li>
            <li>
              {vista.cortes_nuevos ?? 0} cortes nuevos, {vista.cortes_cambiados ?? 0} cortes cambiados
            </li>
            {vista.ausentes && vista.ausentes.length > 0 ? (
              <li>
                {vista.ausentes.length} acciones guardadas no vienen en el archivo (no se borran): {vista.ausentes.join(", ")}
              </li>
            ) : null}
          </ul>
          {vista.alertas && vista.alertas.length > 0 ? (
            <Mensaje tipo="info">
              Revise antes de guardar:
              <ul>
                {vista.alertas.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Mensaje>
          ) : null}
          {vista.actualizadas && vista.actualizadas.length > 0 ? (
            <>
              <h3>Acciones con cambios</h3>
              <ul>
                {vista.actualizadas.map((a) => (
                  <li key={a.accion}>
                    {a.accion}: cambia {a.cambios.join(", ")}
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
