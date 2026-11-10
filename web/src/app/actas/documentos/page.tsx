"use client";

import { useEffect, useState } from "react";
import { ArchivosFirmados, type Firma, FirmarPrograma } from "@/components/FirmarPrograma";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Datos = {
  programas: { clave: string; nombre: string; casos: number; con_recomendacion: number; acta_propuesta: string; anio: number }[];
  sin_programa: number[];
};
type ArchivoActa = { documento: "oficio" | "acta"; formato: "docx" | "pdf"; nombre: string; ruta: string };
type ActaComite = {
  id: number;
  programa: string;
  programa_nombre: string;
  anio: number | null;
  numero: string | null;
  fecha_sesion: string | null;
  estado: "firmada" | "cerrada";
  radicado?: string;
  caso_ids: number[];
  archivos: ArchivoActa[];
  acta_siguiente?: string;
};
type ActaAbierta = {
  programa_nombre: string;
  anio: number;
  numero_propuesto: string;
  casos: { id: number; estudiante: string | null; sentido_texto: string }[];
  caso_ids: number[];
  pendientes: number[];
};

// Cierra el acta en curso de un programa cuando se firmó por fuera de
// MemorIA: número (propuesto, corregible), fecha y confirmación explícita.
function CerrarSinFirma({ token, clave, alCerrar, alTerminar }: { token: string | null; clave: string; alCerrar: () => void; alTerminar: (a: ActaComite) => void }) {
  const [acta, setActa] = useState<ActaAbierta | null>(null);
  const [numero, setNumero] = useState("");
  const [fecha, setFecha] = useState("");
  const [confirmo, setConfirmo] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    llamar<ActaAbierta>("actas", `/actas/actas-comite/${clave}/abierta`, { token })
      .then((a) => {
        setActa(a);
        setNumero(a.numero_propuesto);
      })
      .catch((e: Error) => setError(e.message));
  }, [token, clave]);

  const cerrar = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!acta) return;
    setOcupado(true);
    setError(null);
    try {
      const a = await llamar<ActaComite>("actas", `/actas/actas-comite/${clave}/cerrar`, {
        token,
        json: { numero, fecha_sesion: fecha, caso_ids: acta.caso_ids, confirmo },
      });
      alTerminar(a);
    } catch (err) {
      setError((err as Error).message);
      setConfirmo(false);
    }
    setOcupado(false);
  };

  if (!acta) return error ? <Mensaje tipo="error">{error}</Mensaje> : <p>Preparando el acta…</p>;

  return (
    <section className="tarjeta" style={{ marginBottom: "1rem" }}>
      <h2>Cerrar el acta sin firmar · {acta.programa_nombre}</h2>
      <p className="ayuda">Úselo si el acta se firmó por fuera de MemorIA. Queda guardada con su número y su fecha, los casos pasan al Consejo y los nuevos entran a la siguiente acta.</p>
      {acta.casos.length === 0 ? <Mensaje tipo="error">No hay casos con recomendación del comité.</Mensaje> : null}
      <ul>
        {acta.casos.map((c) => (
          <li key={c.id}>
            #{c.id} · {c.estudiante ?? "sin nombre"} · {c.sentido_texto}
          </li>
        ))}
      </ul>
      {acta.pendientes.length > 0 ? (
        <Mensaje tipo="info">Pasan a la siguiente acta, sin recomendación del comité: {acta.pendientes.map((i) => `#${i}`).join(", ")}.</Mensaje>
      ) : null}
      <form onSubmit={cerrar}>
        <label htmlFor="numero-cierre">
          Número del acta
          <span className="ayuda">Propuesta: la siguiente del programa en {acta.anio}. Corríjala si la dirección numeró otras actas por fuera.</span>
        </label>
        <input id="numero-cierre" value={numero} onChange={(e) => setNumero(e.target.value)} required />
        <label htmlFor="fecha-cierre">Fecha de la sesión</label>
        <input id="fecha-cierre" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} required />
        <label className="opcion">
          <input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} />
          Confirmo que el comité trató estos casos en el acta {numero}.
        </label>
        {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
        <div className="botones">
          <button type="submit" disabled={!confirmo || ocupado || acta.casos.length === 0}>
            {ocupado ? "Cerrando…" : "Cerrar acta y empezar la siguiente"}
          </button>
          <button type="button" className="secundario" disabled={ocupado} onClick={alCerrar}>
            Cancelar
          </button>
        </div>
      </form>
    </section>
  );
}

function ActasAnteriores({ token, actas }: { token: string | null; actas: ActaComite[] }) {
  const [error, setError] = useState<string | null>(null);
  const bajar = async (a: ArchivoActa) => {
    setError(null);
    try {
      guardarArchivo(await llamar<Blob>("actas", a.ruta, { token }), a.nombre);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      <h2>Actas anteriores</h2>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      <div className="tabla">
        <table>
          <thead>
            <tr>
              <th>Programa</th>
              <th>Acta</th>
              <th>Sesión</th>
              <th>Casos</th>
              <th>Documentos</th>
            </tr>
          </thead>
          <tbody>
            {actas.map((a) => (
              <tr key={a.id}>
                <td>{a.programa_nombre}</td>
                <td>
                  {a.numero ? `${a.numero} de ${a.anio}` : "Histórica, sin número"}
                  {a.estado === "firmada" ? ` · firmada${a.radicado ? ` (${a.radicado})` : ""}` : " · cerrada sin firma"}
                </td>
                <td>{a.fecha_sesion ?? "—"}</td>
                <td>{a.caso_ids.length}</td>
                <td>
                  {a.archivos.length === 0 ? "—" : null}
                  {a.archivos.map((x) => (
                    <button key={x.ruta} type="button" className="secundario" onClick={() => bajar(x)}>
                      {x.documento === "oficio" ? "Oficio" : "Acta"} ({x.formato.toUpperCase()})
                    </button>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
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
  const [actas, setActas] = useState<ActaComite[]>([]);
  const [recien, setRecien] = useState<Firma | null>(null);
  const [cerrando, setCerrando] = useState<string | null>(null);
  const [cerrada, setCerrada] = useState<ActaComite | null>(null);
  const t = token("actas");

  const cargar = () => {
    if (!t) return;
    llamar<Datos>("actas", "/actas/documentos", { token: t }).then(setDatos).catch((e: Error) => setError(e.message));
    llamar<{ actas: ActaComite[] }>("actas", "/actas/actas-comite", { token: t })
      .then((r) => setActas(r.actas))
      .catch(() => setActas([]));
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
        "Arma por programa el borrador del oficio y del acta, en Word.",
        "Firma el oficio y el acta cuando usted lo confirma.",
        "Numera las actas por programa y año; al firmar o cerrar una, los casos nuevos van a la siguiente.",
        "Guarda las actas anteriores y, si Drive está activo, el PDF firmado.",
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
            {recien.acta_siguiente ? ` La siguiente acta del programa es la ${recien.acta_siguiente}.` : ""}
          </Mensaje>
          <ArchivosFirmados token={t} firma={recien} />
        </div>
      ) : null}
      {cerrada ? (
        <Mensaje tipo="exito">
          Acta {cerrada.numero} de {cerrada.programa_nombre} cerrada. Los casos {cerrada.caso_ids.map((i) => `#${i}`).join(", ")} pasan al Consejo.
          {cerrada.acta_siguiente ? ` La siguiente acta del programa es la ${cerrada.acta_siguiente}.` : ""}
        </Mensaje>
      ) : null}
      {cerrando ? (
        <CerrarSinFirma
          token={t}
          clave={cerrando}
          alCerrar={() => setCerrando(null)}
          alTerminar={(a) => {
            setCerrando(null);
            setCerrada(a);
            cargar();
          }}
        />
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
          Acta en curso: {p.acta_propuesta} de {p.anio} (número propuesto) · {p.casos} caso(s), {p.con_recomendacion} con recomendación
          <div className="botones">
            <button type="button" disabled={ocupado !== null} onClick={() => bajar(p.clave, p.nombre, "oficio")}>
              {ocupado === p.clave + "oficio" ? "Preparando…" : "Descargar oficio"}
            </button>
            <button type="button" disabled={ocupado !== null} onClick={() => bajar(p.clave, p.nombre, "acta")}>
              {ocupado === p.clave + "acta" ? "Preparando…" : "Descargar acta"}
            </button>
            <button
              type="button"
              disabled={ocupado !== null || firmando !== null || cerrando !== null || p.con_recomendacion === 0}
              onClick={() => {
                setRecien(null);
                setCerrada(null);
                setFirmando(p.clave);
              }}
            >
              Firmar y cerrar el acta…
            </button>
            <button
              type="button"
              className="secundario"
              disabled={ocupado !== null || firmando !== null || cerrando !== null || p.con_recomendacion === 0}
              onClick={() => {
                setRecien(null);
                setCerrada(null);
                setCerrando(p.clave);
              }}
            >
              Cerrar sin firmar…
            </button>
          </div>
          {p.con_recomendacion === 0 ? <span className="ayuda">Para firmar, registre primero la recomendación del comité.</span> : null}
        </div>
      ))}
      {actas.length > 0 ? <ActasAnteriores token={t} actas={actas} /> : null}
      {archivo?.activo && archivo.programas.length > 0 ? <ArchivarActa token={t} estado={archivo} /> : null}
    </Pantalla>
  );
}
