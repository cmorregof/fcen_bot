"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Boletin = {
  id: number;
  semana: string;
  estado: string;
  oferta_ids: number[];
  texto: string;
  generado: string;
  generado_por: string;
  aprobado_por: string | null;
  aprobado: string | null;
};

type Anterior = { id: number; semana: string; estado: string; ofertas: number; aprobado_por: string | null };

type Datos = { semana: string; boletin: Boletin | null; anteriores: Anterior[] };

export default function PaginaBoletin() {
  const { token, tieneRol } = useSesion();
  const t = token("oportunidades");
  const responsable = tieneRol("oportunidades", "oportunidades", "admin");
  const [datos, setDatos] = useState<Datos | null>(null);
  const [semana, setSemana] = useState<string | null>(null);
  const [confirmo, setConfirmo] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const cargar = useCallback(() => {
    if (!t) return;
    const ruta = semana ? `/oportunidades/boletin?semana=${encodeURIComponent(semana)}` : "/oportunidades/boletin";
    llamar<Datos>("oportunidades", ruta, { token: t })
      .then(setDatos)
      .catch((e: Error) => setError(e.message));
  }, [t, semana]);

  useEffect(cargar, [cargar]);

  const ejecutar = async (fn: () => Promise<unknown>, exito: string) => {
    setOcupado(true);
    setError(null);
    try {
      await fn();
      setMensaje(exito);
      setConfirmo(false);
      cargar();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOcupado(false);
    }
  };

  const exportar = async (formato: "texto" | "html") => {
    const hoja = datos?.boletin;
    if (!hoja) return;
    try {
      const archivo = await llamar<Blob>("oportunidades", `/oportunidades/boletin/${hoja.id}/exportar?formato=${formato}`, {
        token: t,
      });
      guardarArchivo(archivo, `boletin-oportunidades-${hoja.semana}.${formato === "html" ? "html" : "txt"}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const hoja = datos?.boletin ?? null;

  return (
    <Pantalla
      titulo="Boletín semanal de oportunidades"
      servicio="oportunidades"
      roles={["oportunidades", "decanatura", "admin"]}
      hace={[
        "Muestra el borrador de la semana, por programa, con las ofertas aprobadas que siguen abiertas.",
        "Permite rehacer el borrador después de aprobar o descartar ofertas.",
        "Con «Aprobar y publicar», deja constancia de quién lo aprobó y cuándo, y marca sus ofertas como publicadas.",
        "Exporta el boletín en texto o HTML para pegarlo en el correo.",
      ]}
      noHace={[
        "No envía el boletín a nadie: MemorIA no manda correos en esta versión.",
        "No incluye ofertas que una persona no haya aprobado.",
        "No guarda la lista de destinatarios.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {mensaje ? <Mensaje tipo="exito">{mensaje}</Mensaje> : null}

      <h2>Semana {datos?.semana}</h2>
      {!hoja ? <p>Todavía no hay borrador para esta semana.</p> : null}
      {hoja ? (
        <>
          <Mensaje tipo="info">
            {hoja.estado === "publicado"
              ? `Publicado: lo aprobó ${hoja.aprobado_por} el ${hoja.aprobado}.`
              : `Borrador con ${hoja.oferta_ids.length} ofertas, generado el ${hoja.generado} (${hoja.generado_por}).`}
          </Mensaje>
          <pre className="aviso-datos">{hoja.texto}</pre>
          <div className="botones">
            <button className="secundario" onClick={() => exportar("texto")}>
              Descargar texto
            </button>
            <button className="secundario" onClick={() => exportar("html")}>
              Descargar HTML para correo
            </button>
          </div>
        </>
      ) : null}

      {responsable && !semana && hoja?.estado !== "publicado" ? (
        <>
          <div className="botones">
            <button
              className="secundario"
              disabled={ocupado}
              onClick={() =>
                ejecutar(
                  () => llamar("oportunidades", "/oportunidades/boletin/borrador", { token: t, metodo: "POST" }),
                  "Borrador rehecho con las ofertas aprobadas.",
                )
              }
            >
              Rehacer borrador
            </button>
          </div>
          {hoja && hoja.oferta_ids.length > 0 ? (
            <>
              <label className="confirmar">
                <input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} />
                Revisé el boletín completo y los enlaces de cada oferta.
              </label>
              <button
                disabled={ocupado || !confirmo}
                onClick={() =>
                  ejecutar(
                    () => llamar("oportunidades", `/oportunidades/boletin/${hoja.id}/aprobar`, { token: t, metodo: "POST" }),
                    "Boletín aprobado y publicado. Descárguelo para enviarlo por correo.",
                  )
                }
              >
                Aprobar y publicar
              </button>
            </>
          ) : null}
        </>
      ) : null}

      <h2>Boletines anteriores</h2>
      <ul>
        {datos?.anteriores.map((a) => (
          <li key={a.id}>
            <button className="secundario" onClick={() => setSemana(a.semana === datos.semana && !semana ? null : a.semana)}>
              {a.semana}
            </button>{" "}
            {a.estado} · {a.ofertas} ofertas{a.aprobado_por ? ` · aprobó ${a.aprobado_por}` : ""}
          </li>
        ))}
      </ul>
      {semana ? (
        <button className="secundario" onClick={() => setSemana(null)}>
          Volver a la semana actual
        </button>
      ) : null}
    </Pantalla>
  );
}
