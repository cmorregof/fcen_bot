"use client";

// Adjuntos del caso (app/services/adjuntos.py): pantallazos, formatos de
// solicitud y anexos. Se pueden agregar, descargar y quitar los equivocados.

import { useState } from "react";
import { Mensaje } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";

export type Adjunto = {
  id: number;
  tipo: string;
  tipo_texto: string;
  nombre: string;
  formato: string;
  bytes: number | null;
  creado: string | null;
  leido: boolean;
  descargable: boolean;
};

export const ACEPTA = ".pdf,.docx,image/jpeg,image/png,image/webp,application/pdf";

type Respuesta = { aviso?: string | null };

function tamano(bytes: number | null) {
  if (bytes === null) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function Adjuntos<T extends Respuesta>({
  casoId,
  adjuntos,
  leido,
  editable,
  token,
  onFicha,
}: {
  casoId: number;
  adjuntos: Adjunto[];
  // El caso ya se leyó con el modelo.
  leido: boolean;
  // Administrativa del área: agrega, clasifica y quita.
  editable: boolean;
  token: string | null;
  onFicha: (d: T) => void;
}) {
  const [archivos, setArchivos] = useState<FileList | null>(null);
  const [confirmar, setConfirmar] = useState<number | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [releer, setReleer] = useState(false);
  const [entrada, setEntrada] = useState(0); // para vaciar el campo de archivos
  const base = `/actas/casos/${casoId}`;

  const ejecutar = async (fn: () => Promise<T>, exito: string, ofrecerReleer = false) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    try {
      const d = await fn();
      onFicha(d);
      setAviso(d.aviso ? `${exito} ${d.aviso}` : exito);
      setReleer(ofrecerReleer && Boolean(d.aviso));
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(false);
  };

  const agregar = () => {
    const form = new FormData();
    for (const f of Array.from(archivos ?? [])) form.append("archivos", f);
    return ejecutar(async () => {
      const d = await llamar<T>("actas", `${base}/archivos`, { token, form });
      setArchivos(null);
      setEntrada((n) => n + 1);
      return d;
    }, "Agregados.", true);
  };

  const borrar = (a: Adjunto) =>
    ejecutar(async () => {
      const d = await llamar<T & { borrado_leido?: boolean }>("actas", `${base}/archivos/${a.id}`, { token, metodo: "DELETE" });
      setConfirmar(null);
      return d;
    }, `Se borró «${a.nombre}».`, true);

  const clasificar = (a: Adjunto, es_formato: boolean) =>
    ejecutar(() => llamar<T>("actas", `${base}/archivos/${a.id}/clasificar`, { token, json: { es_formato } }), "Listo.", es_formato);

  const descargar = async (a: Adjunto) => {
    setError(null);
    try {
      const blob = await llamar<Blob>("actas", `${base}/archivos/${a.id}`, { token });
      guardarArchivo(blob, a.nombre);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <h2>Adjuntos</h2>
      <p>
        <small>Se leen los pantallazos y el formato. Los anexos solo se guardan.</small>
      </p>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso ? <Mensaje tipo="info">{aviso}</Mensaje> : null}
      {releer && leido && editable ? (
        <div className="botones">
          <button
            type="button"
            disabled={ocupado}
            onClick={() => ejecutar(() => llamar<T>("actas", `${base}/releer`, { token, metodo: "POST" }), "Caso leído de nuevo.")}
          >
            {ocupado ? "Leyendo…" : "Volver a leer"}
          </button>
          <small>No cambia la recomendación.</small>
        </div>
      ) : null}
      {adjuntos.length === 0 ? <p>Sin adjuntos.</p> : null}
      {adjuntos.length > 0 ? (
        <div className="tabla">
          <table>
            <thead>
              <tr>
                <th>Archivo</th>
                <th>Tipo</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {adjuntos.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.nombre}
                    <div>
                      <small>
                        {[a.formato, tamano(a.bytes)].filter(Boolean).join(" · ")}
                        {a.leido ? " · leído" : ""}
                      </small>
                    </div>
                  </td>
                  <td>{a.tipo_texto}</td>
                  <td>
                    {confirmar === a.id ? (
                      <div>
                        <p>
                          ¿Borrar «{a.nombre}»? No se puede recuperar.
                          {a.leido && leido ? " Ya se usó en la lectura." : ""}
                        </p>
                        <div className="botones">
                          <button type="button" className="peligro" disabled={ocupado} onClick={() => borrar(a)}>
                            Sí, borrar
                          </button>
                          <button type="button" className="secundario" disabled={ocupado} onClick={() => setConfirmar(null)}>
                            Cancelar
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="botones">
                        {a.descargable ? (
                          <button type="button" className="secundario" onClick={() => descargar(a)}>
                            Descargar
                          </button>
                        ) : null}
                        {editable && a.tipo === "pendiente" ? (
                          <>
                            <button type="button" disabled={ocupado} onClick={() => clasificar(a, true)}>
                              Es el formato
                            </button>
                            <button type="button" className="secundario" disabled={ocupado} onClick={() => clasificar(a, false)}>
                              Es un anexo
                            </button>
                          </>
                        ) : null}
                        {editable ? (
                          <button type="button" className="peligro" disabled={ocupado} onClick={() => setConfirmar(a.id)}>
                            Quitar
                          </button>
                        ) : null}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {editable ? (
        <>
          <label htmlFor="mas-adjuntos">
            Agregar archivos
            <span className="ayuda">PDF, Word o imágenes. Hasta 20 MB.</span>
          </label>
          <input key={entrada} id="mas-adjuntos" type="file" accept={ACEPTA} multiple onChange={(e) => setArchivos(e.target.files)} />
          <div className="botones">
            <button type="button" className="secundario" disabled={ocupado || !archivos?.length} onClick={agregar}>
              Agregar
            </button>
          </div>
        </>
      ) : null}
    </>
  );
}
