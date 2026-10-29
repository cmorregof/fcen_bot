"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Detalle = {
  id: number;
  estado: string;
  sentido: string;
  sentido_texto: string;
  programa: string | null;
  programa_clave: string | null;
  estudiante: string | null;
  objeto: string | null;
  extraccion: {
    documento?: string | null;
    fecha_solicitud?: string | null;
    justificacion_breve?: string;
    dudas?: string[];
    asignaturas?: { codigo: string | null; nombre: string; grupo: string | null; accion: string }[];
    equivalencias?: Cuadro[];
  } | null;
  alertas: { nivel: string; mensaje: string }[];
  cifras: Record<string, number | null> | null;
  nota_comite: string | null;
  conceptos: { miembro: string; texto: string }[];
  miembros: string[];
  programas: { clave: string; nombre: string }[];
  imagenes: number;
  anexos: string[];
};

type LadoCuadro = {
  codigo: string | null;
  nombre: string | null;
  tipologia: string | null;
  creditos: number | null;
  nota: string | null;
};
type Cuadro = {
  figura: string;
  origen: string | null;
  destino: string | null;
  filas: { origen: LadoCuadro; destino: LadoCuadro }[];
};

const FIGURA: Record<string, string> = {
  equivalencia: "Cuadro de equivalencias",
  homologacion: "Cuadro de homologaciones",
  convalidacion: "Cuadro de convalidaciones",
};

function celdas(l: LadoCuadro) {
  return [l.codigo, l.nombre, l.tipologia, l.creditos, l.nota].map((v, i) => <td key={i}>{v ?? ""}</td>);
}

const NIVEL: Record<string, "error" | "info" | "exito"> = { error: "error", aviso: "info", info: "exito" };
const CIFRAS: Record<string, string> = {
  creditos_inscritos: "Créditos inscritos",
  creditos_tras_solicitud: "Créditos tras la solicitud",
  papa: "P.A.P.A.",
  porcentaje_avance: "Avance (%)",
  semana: "Semana del periodo",
};

function Ficha() {
  const id = useSearchParams().get("id");
  const { token, tieneRol } = useSesion();
  const t = token("actas");
  const administrativa = tieneRol("actas", "administrativa");
  const [caso, setCaso] = useState<Detalle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [correccion, setCorreccion] = useState("");
  const [nota, setNota] = useState("");
  const [miembro, setMiembro] = useState("");
  const [concepto, setConcepto] = useState("");

  const cargar = useCallback(async () => {
    try {
      const d = await llamar<Detalle>("actas", `/actas/casos/${id}`, { token: t });
      setCaso(d);
      setNota(d.nota_comite ?? "");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id, t]);

  useEffect(() => {
    if (t && id) cargar();
  }, [t, id, cargar]);

  const accion = async (ruta: string, json: object | undefined, exito: string) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    try {
      const d = await llamar<Detalle>("actas", `/actas/casos/${id}${ruta}`, { token: t, json, metodo: "POST" });
      setCaso(d);
      setAviso(exito);
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(false);
  };

  return (
    <Pantalla
      titulo={caso ? `Caso #${caso.id}${caso.estudiante ? `: ${caso.estudiante}` : ""}` : "Ficha del caso"}
      servicio="actas"
      roles={["administrativa", "comite"]}
      hace={
        administrativa
          ? [
              "Muestra los datos leídos del correo y del SIA, con alertas según la norma.",
              "Registra la recomendación del comité, la nota y los conceptos de sus miembros.",
            ]
          : ["Muestra la ficha del caso y le permite dejar su concepto."]
      }
      noHace={[
        "No decide el caso: el comité recomienda y decide el Consejo de Facultad.",
        "Las alertas no reemplazan la lectura de la norma.",
      ]}
    >
      <div className="botones">
        <Link href="/actas" className="boton secundario">
          ← Volver a los casos
        </Link>
      </div>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso ? <Mensaje tipo="exito">{aviso}</Mensaje> : null}
      {caso && !caso.extraccion ? (
        <>
          <Mensaje tipo="info">Este caso todavía no se ha leído.</Mensaje>
          {administrativa ? (
            <button type="button" disabled={ocupado} onClick={() => accion("/procesar", undefined, "Caso leído.")}>
              {ocupado ? "Leyendo… (puede tardar un minuto)" : "Leer el caso"}
            </button>
          ) : null}
        </>
      ) : null}
      {caso?.extraccion ? (
        <>
          <h2>Solicitud</h2>
          <p>{caso.objeto}</p>
          <ul>
            <li>Programa: {caso.programa ?? "sin identificar"}</li>
            <li>Documento: {caso.extraccion.documento ?? "no aparece"}</li>
            <li>Fecha de la solicitud: {caso.extraccion.fecha_solicitud ?? "no aparece"}</li>
            <li>Justificación: {caso.extraccion.justificacion_breve}</li>
            <li>Pantallazos: {caso.imagenes}. Anexos: {caso.anexos.length ? caso.anexos.join(", ") : "ninguno"}</li>
          </ul>
          {caso.extraccion.asignaturas && caso.extraccion.asignaturas.length > 0 ? (
            <>
              <h3>Asignaturas</h3>
              <ul>
                {caso.extraccion.asignaturas.map((a, i) => (
                  <li key={i}>
                    {a.accion}: {a.codigo ?? ""} {a.nombre} {a.grupo ? `(grupo ${a.grupo})` : ""}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {(caso.extraccion.equivalencias ?? [])
            .filter((c) => c.filas.length > 0)
            .map((c, n) => (
              <div key={n} className="tabla">
                <h3>{FIGURA[c.figura] ?? "Cuadro"}</h3>
                <table>
                  <thead>
                    <tr>
                      <th colSpan={5}>Cursada{c.origen ? ` en ${c.origen}` : ""}</th>
                      <th colSpan={5}>Se reconoce{c.destino ? ` en ${c.destino}` : ""}</th>
                    </tr>
                    <tr>
                      {["Código", "Asignatura", "Tipología", "Créditos", "Nota", "Código", "Asignatura", "Tipología", "Créditos", "Nota"].map(
                        (t, i) => (
                          <th key={i}>{t}</th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {c.filas.map((f, i) => (
                      <tr key={i}>
                        {celdas(f.origen)}
                        {celdas(f.destino)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          {caso.cifras ? (
            <div className="tarjetas">
              {Object.entries(caso.cifras)
                .filter(([, v]) => v !== null)
                .map(([k, v]) => (
                  <div key={k} className="tarjeta">
                    <span className="cifra">{v}</span>
                    {CIFRAS[k] ?? k}
                  </div>
                ))}
            </div>
          ) : null}
          <h2>Alertas</h2>
          {caso.alertas.length === 0 ? <p>Sin alertas.</p> : null}
          {caso.alertas.map((a) => (
            <Mensaje key={a.mensaje} tipo={NIVEL[a.nivel] ?? "info"}>
              {a.mensaje}
            </Mensaje>
          ))}
          {caso.extraccion.dudas && caso.extraccion.dudas.length > 0 ? (
            <>
              <h3>Datos que conviene verificar</h3>
              <ul>
                {caso.extraccion.dudas.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </>
          ) : null}

          {administrativa && !caso.programa_clave ? (
            <>
              <h2>¿A qué programa pertenece?</h2>
              <div className="botones">
                {caso.programas.map((p) => (
                  <button key={p.clave} type="button" className="secundario" onClick={() => accion("/programa", { programa: p.clave }, "Programa guardado.")}>
                    {p.nombre}
                  </button>
                ))}
              </div>
            </>
          ) : null}

          {administrativa ? (
            <>
              <h2>Recomendación del comité</h2>
              <p>
                Actual: <strong>{caso.sentido_texto}</strong>. Regístrela después de la sesión del comité.
              </p>
              <div className="botones">
                <button type="button" disabled={ocupado} onClick={() => accion("/recomendacion", { sentido: "aprobar" }, "Se registró: Recomendar aprobar.")}>
                  Recomendar aprobar
                </button>
                <button type="button" disabled={ocupado} className="peligro" onClick={() => accion("/recomendacion", { sentido: "no_aprobar" }, "Se registró: Recomendar no aprobar.")}>
                  Recomendar no aprobar
                </button>
                <button type="button" disabled={ocupado} className="secundario" onClick={() => accion("/recomendacion", { sentido: "pendiente" }, "El caso quedó pendiente.")}>
                  Pendiente
                </button>
              </div>

              <h2>Corregir un dato</h2>
              <label htmlFor="correccion">
                Escriba qué está mal y cuál es el dato correcto
                <span className="ayuda">Ejemplo: el documento es 1000000001, no 1000000000.</span>
              </label>
              <textarea id="correccion" value={correccion} onChange={(e) => setCorreccion(e.target.value)} />
              <div className="botones">
                <button type="button" disabled={ocupado || !correccion.trim()} onClick={() => accion("/correccion", { texto: correccion }, "Corrección aplicada.").then(() => setCorreccion(""))}>
                  Aplicar corrección
                </button>
              </div>

              <h2>Nota del comité</h2>
              <label htmlFor="nota">Nota que va en el oficio (opcional)</label>
              <textarea id="nota" value={nota} onChange={(e) => setNota(e.target.value)} />
              <div className="botones">
                <button type="button" disabled={ocupado} onClick={() => accion("/nota", { texto: nota }, "Nota guardada.")}>
                  Guardar nota
                </button>
              </div>
            </>
          ) : (
            <p>
              Recomendación registrada: <strong>{caso.sentido_texto}</strong>
            </p>
          )}

          <h2>Conceptos de los miembros del comité</h2>
          <p>
            <small>Van al acta, no al oficio.</small>
          </p>
          {caso.conceptos.length === 0 ? <p>Aún no hay conceptos.</p> : null}
          <ul>
            {caso.conceptos.map((c) => (
              <li key={c.miembro}>
                <strong>{c.miembro}:</strong> {c.texto}
              </li>
            ))}
          </ul>
          <label htmlFor="miembro">Miembro del comité</label>
          <select id="miembro" value={miembro} onChange={(e) => setMiembro(e.target.value)}>
            <option value="">Elija el miembro</option>
            {caso.miembros.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <label htmlFor="concepto">Concepto</label>
          <textarea id="concepto" value={concepto} onChange={(e) => setConcepto(e.target.value)} />
          <div className="botones">
            <button
              type="button"
              disabled={ocupado || !miembro || !concepto.trim()}
              onClick={() => accion("/concepto", { miembro, texto: concepto }, "Concepto guardado.").then(() => setConcepto(""))}
            >
              Guardar concepto
            </button>
          </div>
        </>
      ) : null}
    </Pantalla>
  );
}

export default function PaginaFicha() {
  return (
    <Suspense fallback={<p>Cargando…</p>}>
      <Ficha />
    </Suspense>
  );
}
