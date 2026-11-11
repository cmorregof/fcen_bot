"use client";

// Adjuntos del caso (app/services/adjuntos.py), en dos zonas:
// - «Pantallazos del SIA»: imágenes de la historia académica; las lee la
//   extracción del caso.
// - «Otros anexos del estudiante»: PDF, Word o imágenes. MemorIA resume cada
//   uno (app/services/anexos.py) y el resumen va al análisis del acta.
// Se pueden agregar, descargar y quitar los equivocados.

import { useState } from "react";
import { Mensaje } from "@/components/Pantalla";
import { guardarArchivo, llamar } from "@/lib/api";

export type ResumenAnexo = {
  tipo_documento: string;
  fecha: string | null;
  emisor: string | null;
  acredita: string | null;
  datos_relevantes: string[];
  citas: { texto: string; verificada: boolean }[];
  legible: boolean;
  parcial: boolean;
  frase_acta: string;
};

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
  zona: Zona;
  se_lee: boolean;
  resumen: ResumenAnexo | null;
};

export type Zona = "sia" | "anexos";

export const ACEPTA = ".pdf,.docx,image/jpeg,image/png,image/webp,application/pdf";
export const ACEPTA_SIA = "image/jpeg,image/png,image/webp";
export const VERIFICAR = "[verificar en el anexo]";

export const ZONAS: Record<Zona, { titulo: string; ayuda: string; acepta: string }> = {
  sia: {
    titulo: "Pantallazos del SIA",
    ayuda: "Solo imágenes de la historia académica (JPG, PNG o WEBP). MemorIA lee los créditos, el P.A.P.A. y las asignaturas.",
    acepta: ACEPTA_SIA,
  },
  anexos: {
    titulo: "Otros anexos del estudiante",
    ayuda: "Certificados, cartas, formatos, soportes médicos o constancias, en PDF, Word o imagen. MemorIA resume cada uno para el acta.",
    acepta: ACEPTA,
  },
};

type Respuesta = { aviso?: string | null };

function tamano(bytes: number | null) {
  if (bytes === null) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// El texto con «[verificar en el anexo]» resaltado.
function ConMarcas({ texto }: { texto: string }) {
  const partes = texto.split(VERIFICAR);
  return (
    <>
      {partes.map((p, i) => (
        <span key={i}>
          {p}
          {i < partes.length - 1 ? <mark className="verificar">{VERIFICAR}</mark> : null}
        </span>
      ))}
    </>
  );
}

function Dato({ rotulo, valor }: { rotulo: string; valor: string | null }) {
  return (
    <>
      <dt>{rotulo}</dt>
      <dd>{valor ? <ConMarcas texto={valor} /> : <mark className="verificar">{VERIFICAR}</mark>}</dd>
    </>
  );
}

function Resumen({ r }: { r: ResumenAnexo }) {
  return (
    <div className="resumen-anexo">
      <dl>
        <Dato rotulo="Documento" valor={r.tipo_documento} />
        <Dato rotulo="Emisor" valor={r.emisor} />
        <Dato rotulo="Fecha" valor={r.fecha} />
        <Dato rotulo="Acredita" valor={r.acredita} />
        {r.datos_relevantes.length ? (
          <>
            <dt>Datos</dt>
            <dd>
              <ul>
                {r.datos_relevantes.map((d) => (
                  <li key={d}>
                    <ConMarcas texto={d} />
                  </li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
      </dl>
      {r.citas.map((c) => (
        <blockquote key={c.texto}>
          “{c.texto}”
          <small> {c.verificada ? "· cita comprobada en el archivo" : <mark className="verificar">{VERIFICAR}</mark>}</small>
        </blockquote>
      ))}
      {!r.legible ? <p><small>Hay partes que no se leen: revise el archivo.</small></p> : null}
      {r.parcial ? <p><small>El archivo es largo: solo se leyó la primera parte.</small></p> : null}
      <p>
        <small>
          <strong>Así va en el acta:</strong> <ConMarcas texto={r.frase_acta} />
        </small>
      </p>
    </div>
  );
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
  // Administrativa del área: agrega, clasifica, lee y quita.
  editable: boolean;
  token: string | null;
  onFicha: (d: T) => void;
}) {
  const [archivos, setArchivos] = useState<Record<Zona, FileList | null>>({ sia: null, anexos: null });
  const [confirmar, setConfirmar] = useState<number | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [releer, setReleer] = useState(false);
  const [entrada, setEntrada] = useState(0); // para vaciar los campos de archivos
  const base = `/actas/casos/${casoId}`;

  const ejecutar = async (nombre: string, fn: () => Promise<T>, exito: string, ofrecerReleer = false) => {
    setOcupado(nombre);
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
    setOcupado(null);
  };

  const agregar = (zona: Zona) => {
    const form = new FormData();
    form.append("zona", zona);
    for (const f of Array.from(archivos[zona] ?? [])) form.append("archivos", f);
    return ejecutar(`agregar-${zona}`, async () => {
      const d = await llamar<T>("actas", `${base}/archivos`, { token, form });
      setArchivos((a) => ({ ...a, [zona]: null }));
      setEntrada((n) => n + 1);
      return d;
    }, "Agregados.", zona === "sia");
  };

  const borrar = (a: Adjunto) =>
    ejecutar(`borrar-${a.id}`, async () => {
      const d = await llamar<T & { borrado_leido?: boolean }>("actas", `${base}/archivos/${a.id}`, { token, metodo: "DELETE" });
      setConfirmar(null);
      return d;
    }, `Se borró «${a.nombre}».`, a.zona === "sia");

  const clasificar = (a: Adjunto, es_formato: boolean) =>
    ejecutar(`clasificar-${a.id}`, () => llamar<T>("actas", `${base}/archivos/${a.id}/clasificar`, { token, json: { es_formato } }), "Listo.", es_formato);

  const leerAnexo = (a: Adjunto) =>
    ejecutar(`leer-${a.id}`, () => llamar<T>("actas", `${base}/archivos/${a.id}/leer`, { token, metodo: "POST" }), `Se leyó «${a.nombre}».`);

  const descargar = async (a: Adjunto) => {
    setError(null);
    try {
      const blob = await llamar<Blob>("actas", `${base}/archivos/${a.id}`, { token });
      guardarArchivo(blob, a.nombre);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const fila = (a: Adjunto) => (
    <tr key={a.id}>
      <td>
        {a.nombre}
        <div>
          <small>
            {[a.formato, tamano(a.bytes), a.zona === "anexos" ? a.tipo_texto : ""].filter(Boolean).join(" · ")}
            {a.zona === "sia" && a.leido ? " · leído" : ""}
          </small>
        </div>
        {a.resumen ? <Resumen r={a.resumen} /> : null}
        {a.se_lee && !a.resumen ? (
          <p>
            <small>Sin resumen todavía: se lee al leer el caso, o con «Leer con MemorIA».</small>
          </p>
        ) : null}
      </td>
      <td>
        {confirmar === a.id ? (
          <div>
            <p>
              ¿Borrar «{a.nombre}»? No se puede recuperar.
              {a.zona === "sia" && a.leido && leido ? " Ya se usó en la lectura." : ""}
              {a.resumen ? " Su resumen también sale del acta." : ""}
            </p>
            <div className="botones">
              <button type="button" className="peligro" disabled={ocupado !== null} onClick={() => borrar(a)}>
                Sí, borrar
              </button>
              <button type="button" className="secundario" disabled={ocupado !== null} onClick={() => setConfirmar(null)}>
                Cancelar
              </button>
            </div>
          </div>
        ) : (
          <div className="botones">
            {editable && a.se_lee ? (
              <button type="button" className={a.resumen ? "secundario" : undefined} disabled={ocupado !== null} onClick={() => leerAnexo(a)}>
                {ocupado === `leer-${a.id}` ? "Leyendo…" : a.resumen ? "Leer de nuevo" : "Leer con MemorIA"}
              </button>
            ) : null}
            {a.descargable ? (
              <button type="button" className="secundario" onClick={() => descargar(a)}>
                Descargar
              </button>
            ) : null}
            {editable && a.tipo === "pendiente" ? (
              <>
                <button type="button" disabled={ocupado !== null} onClick={() => clasificar(a, true)}>
                  Es el formato
                </button>
                <button type="button" className="secundario" disabled={ocupado !== null} onClick={() => clasificar(a, false)}>
                  Es un anexo
                </button>
              </>
            ) : null}
            {editable ? (
              <button type="button" className="peligro" disabled={ocupado !== null} onClick={() => setConfirmar(a.id)}>
                Quitar
              </button>
            ) : null}
          </div>
        )}
      </td>
    </tr>
  );

  const zona = (z: Zona) => {
    const lista = adjuntos.filter((a) => a.zona === z);
    const { titulo, ayuda, acepta } = ZONAS[z];
    const campo = `adjuntos-${z}`;
    return (
      <section key={z} aria-labelledby={`titulo-${z}`}>
        <h2 id={`titulo-${z}`}>{titulo}</h2>
        <p>
          <small>{ayuda}</small>
        </p>
        {lista.length === 0 ? <p>Sin archivos.</p> : null}
        {lista.length > 0 ? (
          <div className="tabla">
            <table>
              <thead>
                <tr>
                  <th>{z === "sia" ? "Pantallazo" : "Anexo y resumen"}</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>{lista.map(fila)}</tbody>
            </table>
          </div>
        ) : null}
        {editable ? (
          <>
            <label htmlFor={campo}>
              {z === "sia" ? "Agregar pantallazos" : "Agregar anexos"}
              <span className="ayuda">{z === "sia" ? "Imágenes. Hasta 10 MB cada una." : "PDF, Word o imágenes. Hasta 20 MB."}</span>
            </label>
            <input
              key={`${z}-${entrada}`}
              id={campo}
              type="file"
              accept={acepta}
              multiple
              onChange={(e) => {
                const f = e.target.files;
                setArchivos((a) => ({ ...a, [z]: f }));
              }}
            />
            <div className="botones">
              <button type="button" className="secundario" disabled={ocupado !== null || !archivos[z]?.length} onClick={() => agregar(z)}>
                {ocupado === `agregar-${z}` ? (z === "anexos" ? "Agregando y leyendo…" : "Agregando…") : "Agregar"}
              </button>
            </div>
          </>
        ) : null}
      </section>
    );
  };

  return (
    <>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso ? <Mensaje tipo="info">{aviso}</Mensaje> : null}
      {releer && leido && editable ? (
        <div className="botones">
          <button
            type="button"
            disabled={ocupado !== null}
            onClick={() => ejecutar("releer", () => llamar<T>("actas", `${base}/releer`, { token, metodo: "POST" }), "Caso leído de nuevo.")}
          >
            {ocupado === "releer" ? "Leyendo…" : "Volver a leer el caso"}
          </button>
          <small>No cambia la recomendación.</small>
        </div>
      ) : null}
      {zona("sia")}
      {zona("anexos")}
      <p>
        <small>MemorIA solo resume los anexos: no decide si son suficientes. Lo que no lee queda como «{VERIFICAR}».</small>
      </p>
    </>
  );
}
