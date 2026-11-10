"use client";

import { useEffect, useState } from "react";
import { Mensaje } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";

// Firma del oficio al Consejo y del acta del comité de un programa. Tres
// pasos: resumen, datos (radicado y sesión) y confirmación explícita. Nada se
// firma hasta que la persona marca la casilla y toca «Firmar».

export type ArchivoFirmado = { documento: "oficio" | "acta"; formato: "docx" | "pdf"; nombre: string; sha256: string };
export type Firma = {
  id: number;
  programa: string;
  programa_nombre: string;
  radicado: string;
  numero_acta: string;
  fecha_sesion: string;
  hora: string;
  lugar: string;
  caso_ids: number[];
  firmante: string;
  firmado_por: string;
  firmado: string;
  con_imagen: boolean;
  archivos: ArchivoFirmado[];
};

type Preparacion = {
  programa: string;
  programa_nombre: string;
  firmante: { nombre: string; cargo: string } | null;
  firma_en_nombre: string;
  tiene_imagen: boolean;
  radicado_propuesto: string | null;
  casos: { id: number; estudiante: string | null; sentido_texto: string }[];
  caso_ids: number[];
  pendientes: number[];
  bloqueos: string[];
  avisos: string[];
};

export async function bajarFirmado(token: string | null, firma: Firma, archivo: ArchivoFirmado) {
  const blob = await llamar<Blob>("actas", `/actas/firmas/${firma.id}/${archivo.documento}/${archivo.formato}`, { token });
  guardarArchivo(blob, archivo.nombre);
}

export function ArchivosFirmados({ token, firma }: { token: string | null; firma: Firma }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <div className="botones">
        {firma.archivos.map((a) => (
          <button
            key={a.documento + a.formato}
            type="button"
            className="secundario"
            onClick={() => bajarFirmado(token, firma, a).catch((e: Error) => setError(e.message))}
          >
            {a.documento === "oficio" ? "Oficio" : "Acta"} ({a.formato.toUpperCase()})
          </button>
        ))}
      </div>
      <details>
        <summary>SHA-256 de cada documento</summary>
        <ul>
          {firma.archivos.map((a) => (
            <li key={a.nombre}>
              {a.nombre}: <code style={{ wordBreak: "break-all" }}>{a.sha256}</code>
            </li>
          ))}
        </ul>
      </details>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
    </>
  );
}

export function FirmarPrograma({
  token,
  clave,
  alTerminar,
  alCerrar,
}: {
  token: string | null;
  clave: string;
  alTerminar: (f: Firma) => void;
  alCerrar: () => void;
}) {
  const [prep, setPrep] = useState<Preparacion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paso, setPaso] = useState<"datos" | "confirmar">("datos");
  const [radicado, setRadicado] = useState("");
  const [acta, setActa] = useState("");
  const [fecha, setFecha] = useState("");
  const [hora, setHora] = useState("");
  const [lugar, setLugar] = useState("");
  const [confirmo, setConfirmo] = useState(false);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    llamar<Preparacion>("actas", `/actas/firmar/${clave}`, { token })
      .then((p) => {
        setPrep(p);
        setRadicado(p.radicado_propuesto ?? "");
      })
      .catch((e: Error) => setError(e.message));
  }, [token, clave]);

  const firmar = async () => {
    if (!prep) return;
    setOcupado(true);
    setError(null);
    try {
      const f = await llamar<Firma>("actas", `/actas/firmar/${clave}`, {
        token,
        json: { radicado, numero_acta: acta, fecha_sesion: fecha, hora, lugar, caso_ids: prep.caso_ids, confirmo },
      });
      alTerminar(f);
    } catch (e) {
      setError((e as Error).message);
      setPaso("datos");
      setConfirmo(false);
    }
    setOcupado(false);
  };

  if (!prep) return error ? <Mensaje tipo="error">{error}</Mensaje> : <p>Preparando el resumen…</p>;

  return (
    <section className="tarjeta" style={{ marginBottom: "1rem" }}>
      <h2>Firmar · {prep.programa_nombre}</h2>
      {prep.firmante ? (
        <p>
          Firma <strong style={{ display: "inline" }}>{prep.firmante.nombre}</strong>, {prep.firmante.cargo}. Usted firma en su nombre ({prep.firma_en_nombre}).
        </p>
      ) : null}
      <p>Entran {prep.casos.length} caso(s) al oficio y al acta:</p>
      <ul>
        {prep.casos.map((c) => (
          <li key={c.id}>
            #{c.id} · {c.estudiante ?? "sin nombre"} · {c.sentido_texto}
          </li>
        ))}
      </ul>
      {prep.bloqueos.map((b) => (
        <Mensaje key={b} tipo="error">
          {b}
        </Mensaje>
      ))}
      {prep.avisos.map((a) => (
        <Mensaje key={a} tipo="info">
          {a}
        </Mensaje>
      ))}
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}

      {prep.bloqueos.length > 0 ? (
        <div className="botones">
          <button type="button" className="secundario" onClick={alCerrar}>
            Cerrar
          </button>
        </div>
      ) : paso === "datos" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setPaso("confirmar");
          }}
        >
          <label htmlFor="radicado">
            Radicado del oficio
            <span className="ayuda">Es una propuesta: el siguiente de la dirección. Corríjalo si ya usó ese número por fuera de MemorIA.</span>
          </label>
          <input id="radicado" value={radicado} onChange={(e) => setRadicado(e.target.value)} placeholder="Mz.FCEN.1.0xx-NNN-26" required />
          <label htmlFor="acta">Número del acta del comité</label>
          <input id="acta" value={acta} onChange={(e) => setActa(e.target.value)} placeholder="019" required />
          <label htmlFor="fecha">Fecha de la sesión</label>
          <input id="fecha" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} required />
          <label htmlFor="hora">Hora</label>
          <input id="hora" value={hora} onChange={(e) => setHora(e.target.value)} placeholder="10:00 a. m." required />
          <label htmlFor="lugar">
            Lugar
            <span className="ayuda">O «sesión ad referéndum».</span>
          </label>
          <input id="lugar" value={lugar} onChange={(e) => setLugar(e.target.value)} required />
          <div className="botones">
            <button type="submit">Revisar antes de firmar</button>
            <button type="button" className="secundario" onClick={alCerrar}>
              Cancelar
            </button>
          </div>
        </form>
      ) : (
        <div>
          <p className="aviso-datos">
            Radicado: {radicado}
            {"\n"}Acta {acta} · sesión del {fecha} · {hora} · {lugar}
            {"\n"}Casos: {prep.caso_ids.map((i) => `#${i}`).join(", ")}
          </p>
          <p>
            Al firmar se generan el oficio y el acta finales{prep.tiene_imagen ? " con la imagen de la firma" : ""}, en Word y PDF; se registra quién firmó, cuándo y la huella SHA-256 de cada
            documento; y los casos pasan al Consejo de Facultad.
          </p>
          <label className="opcion">
            <input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} />
            Confirmo que el comité trató estos casos y que firmo en nombre de {prep.firmante?.nombre}.
          </label>
          <div className="botones">
            <button type="button" disabled={!confirmo || ocupado} onClick={firmar}>
              {ocupado ? "Firmando…" : "Firmar"}
            </button>
            <button type="button" className="secundario" disabled={ocupado} onClick={() => setPaso("datos")}>
              Corregir datos
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
