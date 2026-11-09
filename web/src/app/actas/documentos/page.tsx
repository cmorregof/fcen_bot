"use client";

import { useEffect, useState } from "react";
import { ArchivosFirmados, type Firma, FirmarPrograma } from "@/components/FirmarPrograma";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Datos = { programas: { clave: string; nombre: string; casos: number; con_recomendacion: number }[]; sin_programa: number[] };
type EstadoArchivo = { activo: boolean; programas: { clave: string; nombre: string }[] };

// El acta ya firmada (PDF) va al archivo oficial en Drive. El Word es un
// borrador y no se archiva.
function ArchivarActa({ token, estado }: { token: string | null; estado: EstadoArchivo }) {
  const [programa, setPrograma] = useState(estado.programas[0]?.clave ?? "");
  const [numero, setNumero] = useState("");
  const [fecha, setFecha] = useState("");
  const [pdf, setPdf] = useState<File | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [resultado, setResultado] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);

  const archivar = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pdf) return;
    setOcupado(true);
    setResultado(null);
    const form = new FormData();
    form.append("programa", programa);
    form.append("numero", numero);
    form.append("fecha", fecha);
    form.append("pdf", pdf);
    try {
      const r = await llamar<{ ruta: string }>("actas", "/actas/archivo/acta", { token, form });
      setResultado({ tipo: "ok", texto: `Archivada en Drive: ${r.ruta}` });
    } catch (err) {
      setResultado({ tipo: "error", texto: (err as Error).message });
    }
    setOcupado(false);
  };

  return (
    <form onSubmit={archivar}>
      <h2>Archivar el acta firmada</h2>
      <p className="ayuda">Suba el PDF del acta ya firmada. Queda en el archivo oficial de Drive, por año, área y programa, y en el índice del año.</p>
      <label htmlFor="programa-acta">Programa</label>
      <select id="programa-acta" value={programa} onChange={(e) => setPrograma(e.target.value)}>
        {estado.programas.map((p) => (
          <option key={p.clave} value={p.clave}>
            {p.nombre}
          </option>
        ))}
      </select>
      <label htmlFor="numero-acta">Número del acta</label>
      <input id="numero-acta" value={numero} onChange={(e) => setNumero(e.target.value)} placeholder="019" required />
      <label htmlFor="fecha-acta">Fecha de la sesión</label>
      <input id="fecha-acta" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} required />
      <label htmlFor="pdf-acta">PDF firmado</label>
      <input id="pdf-acta" type="file" accept="application/pdf,.pdf" onChange={(e) => setPdf(e.target.files?.[0] ?? null)} required />
      <div className="botones">
        <button type="submit" disabled={ocupado || !pdf}>
          {ocupado ? "Archivando…" : "Archivar en Drive"}
        </button>
      </div>
      {resultado ? <Mensaje tipo={resultado.tipo === "ok" ? "exito" : "error"}>{resultado.texto}</Mensaje> : null}
    </form>
  );
}

export default function Documentos() {
  const { token } = useSesion();
  const [datos, setDatos] = useState<Datos | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [archivo, setArchivo] = useState<EstadoArchivo | null>(null);
  const [firmando, setFirmando] = useState<string | null>(null);
  const [firmas, setFirmas] = useState<Firma[]>([]);
  const [recien, setRecien] = useState<Firma | null>(null);
  const t = token("actas");

  const cargar = () => {
    if (!t) return;
    llamar<Datos>("actas", "/actas/documentos", { token: t }).then(setDatos).catch((e: Error) => setError(e.message));
    llamar<{ firmas: Firma[] }>("actas", "/actas/firmas", { token: t })
      .then((r) => setFirmas(r.firmas))
      .catch(() => setFirmas([]));
  };

  useEffect(() => {
    if (!t) return;
    cargar();
    llamar<EstadoArchivo>("actas", "/actas/archivo", { token: t })
      .then(setArchivo)
      .catch(() => setArchivo(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      roles={["administrativa", "admin"]}
      hace={[
        "Arma, por programa, el borrador del oficio al Consejo y el acta del comité con los casos con ficha lista.",
        "Los descarga en Word para revisarlos.",
        "Firma el oficio y el acta de un programa cuando usted lo confirma: radicado, datos de la sesión, imagen de la firma, Word y PDF finales, y registro de quién firmó.",
        "Si el archivo en Drive está activo, guarda el acta ya firmada (PDF) en el archivo oficial.",
      ]}
      noHace={[
        "No envía nada al Consejo: el oficio firmado lo envía usted.",
        "No firma sin su confirmación, ni casos sin recomendación del comité.",
      ]}
    >
      {recien ? (
        <div className="tarjeta" style={{ marginBottom: "1rem" }}>
          <Mensaje tipo="exito">
            Firmado {recien.programa_nombre}: radicado {recien.radicado}, acta {recien.numero_acta}. Los casos {recien.caso_ids.map((i) => `#${i}`).join(", ")} pasan al Consejo.
          </Mensaje>
          <ArchivosFirmados token={t} firma={recien} />
        </div>
      ) : null}
      {firmando ? (
        <FirmarPrograma
          token={t}
          clave={firmando}
          alCerrar={() => setFirmando(null)}
          alTerminar={(f) => {
            setFirmando(null);
            setRecien(f);
            cargar();
          }}
        />
      ) : null}
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
            <button
              type="button"
              disabled={ocupado !== null || firmando !== null || p.con_recomendacion === 0}
              onClick={() => {
                setRecien(null);
                setFirmando(p.clave);
              }}
            >
              Firmar…
            </button>
          </div>
          {p.con_recomendacion === 0 ? <span className="ayuda">Para firmar, registre primero la recomendación del comité.</span> : null}
        </div>
      ))}
      {firmas.length > 0 ? (
        <>
          <h2>Documentos firmados</h2>
          {firmas.map((f) => (
            <details key={f.id} className="tarjeta" style={{ marginBottom: "0.75rem" }}>
              <summary>
                {f.radicado} · {f.programa_nombre} · acta {f.numero_acta} · firmó {f.firmado_por} ({f.firmado} UTC)
              </summary>
              <p>
                Firma: {f.firmante}
                {f.con_imagen ? "" : " (sin imagen de firma)"}. Sesión del {f.fecha_sesion}, {f.hora}, {f.lugar}. Casos: {f.caso_ids.map((i) => `#${i}`).join(", ")}.
              </p>
              <ArchivosFirmados token={t} firma={f} />
            </details>
          ))}
        </>
      ) : null}
      {archivo?.activo && archivo.programas.length > 0 ? <ArchivarActa token={t} estado={archivo} /> : null}
    </Pantalla>
  );
}
