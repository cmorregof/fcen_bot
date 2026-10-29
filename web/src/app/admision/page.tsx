"use client";

import { useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

const ETIQUETAS: Record<string, string> = {
  consentimientos: "Personas que aceptaron el aviso de datos",
  rechazos: "Personas que no aceptaron el aviso",
  menores: "Menores de edad",
  preguntas: "Preguntas recibidas",
  preguntas_sin_respuesta: "Preguntas que no estaban en el listado",
  documentos_revisados: "Documentos revisados",
  documentos_con_errores: "Documentos con algo por corregir",
  credenciales_bloqueadas: "Veces que alguien escribió un correo o contraseña",
};

type Documento = {
  clave: string;
  nombre: string;
  seccion: string;
  tipo: "obligatorio" | "condicional" | "opcional";
  condicion: string | null;
  nota: string | null;
  chequeo: string[];
};
type Insumo = { nombre: string; bytes: number; paginas: number; caracteres: number; estado: string };
type Insumos = { carpeta: string; archivos: Insumo[]; faltan: string[] };

const ESTADOS: Record<string, string> = {
  ok: "Se lee bien",
  ocr_en_cache: "Escaneado; se usa el texto de su .ocr.txt",
  se_hara_ocr: "Escaneado; se le hará OCR al leerlo (puede tardar unos minutos)",
  falta_ocr: "Escaneado y sin .ocr.txt: el asistente no lo puede leer",
  ilegible: "No se pudo abrir",
};

function porSeccion(docs: Documento[]): [string, Documento[]][] {
  const grupos = new Map<string, Documento[]>();
  for (const d of docs) grupos.set(d.seccion, [...(grupos.get(d.seccion) ?? []), d]);
  return [...grupos.entries()];
}

function Fuentes({ t }: { t: string }) {
  const [insumos, setInsumos] = useState<Insumos | null>(null);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    llamar<Insumos>("admision", "/admision/insumos", { token: t })
      .then(setInsumos)
      .catch((e: Error) => setError(e.message));
  }, [t]);

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (!archivo) return;
        setOcupado(true);
        setError(null);
        const form = new FormData();
        form.append("archivo", archivo);
        try {
          setInsumos(await llamar<Insumos>("admision", "/admision/insumos", { token: t, form }));
        } catch (err) {
          setError((err as Error).message);
        }
        setOcupado(false);
      }}
    >
      <h2>Fuentes del asistente</h2>
      <p>
        <small>
          Documentos oficiales que el asistente usa para responder. Solo documentos públicos de la Universidad, nunca
          de un admitido.
        </small>
      </p>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {insumos && insumos.faltan.length > 0 ? (
        <Mensaje tipo="info">
          Faltan:
          <ul>
            {insumos.faltan.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Mensaje>
      ) : null}
      {insumos ? (
        <div className="tabla">
          <table>
            <thead>
              <tr>
                <th scope="col">Archivo</th>
                <th scope="col">Páginas</th>
                <th scope="col">Estado</th>
              </tr>
            </thead>
            <tbody>
              {insumos.archivos.map((a) => (
                <tr key={a.nombre}>
                  <th scope="row">{a.nombre}</th>
                  <td>{a.paginas}</td>
                  <td>{ESTADOS[a.estado] ?? a.estado}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <label htmlFor="insumo">
        Subir o reemplazar un archivo
        <span className="ayuda">PDF con su nombre oficial, o su .ocr.txt. Si ya existe, se reemplaza.</span>
      </label>
      <input id="insumo" type="file" accept=".pdf,.txt,.md" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} required />
      <div className="botones">
        <button type="submit" disabled={ocupado}>
          {ocupado ? "Subiendo…" : "Subir"}
        </button>
      </div>
    </form>
  );
}

export default function Admision() {
  const { token } = useSesion();
  const [metricas, setMetricas] = useState<Record<string, number> | null>(null);
  const [docs, setDocs] = useState<Documento[]>([]);
  const [error, setError] = useState<string | null>(null);
  const t = token("admision");

  useEffect(() => {
    if (!t) return;
    llamar<{ metricas: Record<string, number> }>("admision", "/admision/metricas", { token: t })
      .then((d) => setMetricas(d.metricas))
      .catch((e: Error) => setError(e.message));
    llamar<{ documentos: Documento[] }>("admision", "/admision/chequeo", { token: t })
      .then((d) => setDocs(d.documentos))
      .catch((e: Error) => setError(e.message));
  }, [t]);

  return (
    <Pantalla
      titulo="Admisión: cifras y lista de chequeo"
      servicio="admision"
      roles={["admision", "admin"]}
      hace={[
        "Muestra cuántas personas usaron el asistente y qué errores aparecen más.",
        "Muestra la lista de chequeo que usa el asistente para cada documento.",
        "Deja subir los documentos oficiales (listado, formato, manual) que el asistente consulta.",
      ]}
      noHace={[
        "No muestra documentos ni preguntas de los admitidos: no se guardan.",
        "No decide si un documento es válido: eso lo hace la revisión oficial.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      <h2>Cifras acumuladas</h2>
      {metricas && Object.keys(metricas).length === 0 ? <p>Aún no hay cifras.</p> : null}
      {metricas ? (
        <div className="tabla">
          <table>
            <tbody>
              {Object.entries(metricas).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">{ETIQUETAS[k] ?? k.replace("error_", "Errores de tipo: ").replaceAll("_", " ")}</th>
                  <td>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <h2>Lista de chequeo</h2>
      <p>
        <small>Se edita en el archivo config/admision/chequeo.yaml del servicio.</small>
      </p>
      {porSeccion(docs).map(([seccion, lista]) => (
        <section key={seccion}>
          <h3>{seccion}</h3>
          {lista.map((d) => (
            <div key={d.clave}>
              <h4>
                {d.nombre}
                {d.tipo === "opcional" ? " (opcional)" : null}
              </h4>
              {d.tipo === "condicional" && d.condicion ? (
                <p>
                  <strong>{d.condicion}.</strong>
                </p>
              ) : null}
              {d.nota ? (
                <p>
                  <small>{d.nota}</small>
                </p>
              ) : null}
              <ul>
                {d.chequeo.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      ))}
      {t ? <Fuentes t={t} /> : null}
    </Pantalla>
  );
}
