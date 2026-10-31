"use client";

import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { Catalogos, MODALIDADES, Oferta, nombresProgramas } from "@/lib/oportunidades";
import { useSesion } from "@/lib/sesion";

function Tarjeta({
  oferta,
  catalogos,
  alCambiar,
}: {
  oferta: Oferta;
  catalogos: Catalogos | null;
  alCambiar: (mensaje: string) => void;
}) {
  const { token } = useSesion();
  const t = token("oportunidades");
  const [nota, setNota] = useState("");
  const [motivo, setMotivo] = useState("");
  const [programas, setProgramas] = useState<string[]>(oferta.programas);
  const [cierre, setCierre] = useState(oferta.fecha_cierre ?? "");
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const accion = async (ruta: string, json: unknown, metodo = "POST", exito = "Listo.") => {
    setOcupado(true);
    setError(null);
    try {
      await llamar("oportunidades", ruta, { token: t, json, metodo });
      alCambiar(exito);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOcupado(false);
    }
  };

  const base = `/oportunidades/ofertas/${oferta.id}`;
  const cambioDatos =
    programas.join() !== oferta.programas.join() || cierre !== (oferta.fecha_cierre ?? "");

  return (
    <div className="tarjeta">
      <strong>
        #{oferta.id} {oferta.titulo}
      </strong>
      <div>
        {oferta.entidad} · {catalogos?.tipos[oferta.tipo] ?? oferta.tipo} · {MODALIDADES[oferta.modalidad]}
        {oferta.lugar ? ` · ${oferta.lugar}` : ""}
      </div>
      <div>Programas: {nombresProgramas(oferta, catalogos)}</div>
      <div>Cierre: {oferta.fecha_cierre ?? "sin fecha"}</div>
      {oferta.resumen ? <div>{oferta.resumen}</div> : null}
      {oferta.requisitos ? <div>Requisitos: {oferta.requisitos}</div> : null}
      <div>
        <a href={oferta.url} target="_blank" rel="noopener noreferrer">
          Abrir la oferta en la fuente ({oferta.fuente})
        </a>
      </div>
      {oferta.motivos.length > 0 ? (
        <>
          <div>
            <strong>Por qué está en la cola:</strong>
          </div>
          <ul>
            {oferta.motivos.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </>
      ) : null}
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}

      {oferta.estado === "encontrada" ? (
        <details>
          <summary>Corregir programas o fecha de cierre</summary>
          <fieldset>
            <legend>Programas FCEN</legend>
            {Object.entries(catalogos?.programas ?? {}).map(([clave, nombre]) => (
              <label key={clave} className="opcion">
                <input
                  type="checkbox"
                  checked={programas.includes(clave)}
                  onChange={(e) =>
                    setProgramas(e.target.checked ? [...programas, clave] : programas.filter((p) => p !== clave))
                  }
                />
                {nombre}
              </label>
            ))}
          </fieldset>
          <label>
            Fecha de cierre
            <input type="date" value={cierre} onChange={(e) => setCierre(e.target.value)} />
          </label>
          <button
            disabled={ocupado || !cambioDatos}
            onClick={() =>
              accion(base, { programas, fecha_cierre: cierre || null }, "PUT", "Corregida y revisada de nuevo.")
            }
          >
            Guardar corrección
          </button>
        </details>
      ) : null}

      <div className="botones">
        {oferta.estado === "encontrada" ? (
          <>
            <label>
              Qué revisó (obligatorio si hay motivos)
              <input type="text" value={nota} onChange={(e) => setNota(e.target.value)} />
            </label>
            <button disabled={ocupado} onClick={() => accion(`${base}/verificar`, { nota }, "POST", "Marcada como verificada.")}>
              Marcar verificada
            </button>
          </>
        ) : null}
        {oferta.estado === "verificada" ? (
          <button disabled={ocupado} onClick={() => accion(`${base}/aprobar`, undefined, "POST", "Aprobada para el boletín.")}>
            Aprobar para el boletín
          </button>
        ) : null}
      </div>
      <div className="botones">
        <label>
          Motivo del descarte
          <input type="text" value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </label>
        <button
          className="peligro"
          disabled={ocupado || motivo.trim().length < 3}
          onClick={() => accion(`${base}/descartar`, { motivo }, "POST", "Descartada.")}
        >
          Descartar
        </button>
      </div>
    </div>
  );
}

export default function ColaRevision() {
  const { token } = useSesion();
  const t = token("oportunidades");
  const [cola, setCola] = useState<Oferta[]>([]);
  const [verificadas, setVerificadas] = useState<Oferta[]>([]);
  const [catalogos, setCatalogos] = useState<Catalogos | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(() => {
    if (!t) return;
    Promise.all([
      llamar<{ ofertas: Oferta[] }>("oportunidades", "/oportunidades/cola", { token: t }),
      llamar<{ ofertas: Oferta[] }>("oportunidades", "/oportunidades/ofertas?estado=verificada", { token: t }),
      llamar<Catalogos>("oportunidades", "/oportunidades/catalogos", { token: t }),
    ])
      .then(([c, v, cat]) => {
        setCola(c.ofertas);
        setVerificadas(v.ofertas);
        setCatalogos(cat);
      })
      .catch((e: Error) => setError(e.message));
  }, [t]);

  useEffect(cargar, [cargar]);

  const alCambiar = (m: string) => {
    setMensaje(m);
    cargar();
  };

  return (
    <Pantalla
      titulo="Oportunidades: cola de revisión"
      servicio="oportunidades"
      roles={["oportunidades", "admin"]}
      hace={[
        "Muestra las ofertas que el verificador no pudo dar por buenas, con cada motivo (enlace, fecha, programa, duplicado o dudas del modelo).",
        "Permite corregir programas y fecha, marcar una oferta como verificada (dejando qué revisó) o descartarla con motivo.",
        "Permite aprobar para el boletín las ofertas verificadas.",
      ]}
      noHace={[
        "No aprueba nada sola: el verificador y el modelo nunca aprueban.",
        "No publica ni envía el boletín: eso se hace en «Boletín semanal».",
        "No guarda datos de estudiantes.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {mensaje ? <Mensaje tipo="exito">{mensaje}</Mensaje> : null}
      <h2>Por revisar ({cola.length})</h2>
      {cola.length === 0 ? <p>No hay ofertas en la cola.</p> : null}
      <div className="tarjetas">
        {cola.map((o) => (
          <Tarjeta key={o.id} oferta={o} catalogos={catalogos} alCambiar={alCambiar} />
        ))}
      </div>
      <h2>Verificadas, por aprobar para el boletín ({verificadas.length})</h2>
      {verificadas.length === 0 ? <p>No hay ofertas verificadas pendientes.</p> : null}
      <div className="tarjetas">
        {verificadas.map((o) => (
          <Tarjeta key={o.id} oferta={o} catalogos={catalogos} alCambiar={alCambiar} />
        ))}
      </div>
    </Pantalla>
  );
}
