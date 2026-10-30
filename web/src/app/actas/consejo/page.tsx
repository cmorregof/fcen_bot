"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type CasoCorto = {
  id: number;
  estudiante: string | null;
  documento: string | null;
  programa: string | null;
  recomendacion: string;
};

type Decision = {
  id: number;
  orden: number;
  leida: {
    nombre_estudiante: string | null;
    documento: string | null;
    numero_caso: string | null;
    radicado: string | null;
    programa: string | null;
    texto_decision: string;
    fragmento: string;
  };
  sentido_texto: string;
  cruce: "exacto" | "dudoso" | "sin_caso" | "no_verificado";
  motivo: string | null;
  estado: "pendiente" | "aplicada" | "descartada";
  revisado_por: string | null;
  caso: CasoCorto | null;
  candidatos: CasoCorto[];
};

type Acta = {
  id: number;
  instancia_texto: string;
  numero: string | null;
  fecha: string | null;
  archivo: string | null;
  subido_por: string;
  pendientes: number;
  cruzaron: Decision[];
  en_duda: Decision[];
  sin_caso: Decision[];
  no_aparecieron: CasoCorto[];
};

type Lista = {
  actas: { id: number; instancia_texto: string; numero: string | null; fecha: string | null; archivo: string | null; decisiones: number; pendientes: number }[];
  instancias: { clave: string; nombre: string }[];
};

const ESTADO: Record<Decision["estado"], string> = {
  pendiente: "Sin confirmar",
  aplicada: "Registrada",
  descartada: "Descartada",
};

function nombreCaso(c: CasoCorto) {
  return `#${c.id} · ${c.estudiante ?? "sin nombre"}${c.documento ? ` · ${c.documento}` : ""}${c.programa ? ` · ${c.programa}` : ""}`;
}

function Leido({ d }: { d: Decision }) {
  const l = d.leida;
  const ids = [
    l.documento ? `documento ${l.documento}` : null,
    l.numero_caso ? `caso ${l.numero_caso}` : null,
    l.radicado ? `radicado ${l.radicado}` : null,
    l.programa,
  ].filter(Boolean);
  return (
    <>
      <strong>{l.nombre_estudiante ?? "Sin nombre en el acta"}</strong>
      {ids.length ? <div><small>{ids.join(" · ")}</small></div> : null}
      <div>
        {d.sentido_texto}: «{l.texto_decision}»
      </div>
      <blockquote style={{ margin: "0.5rem 0", whiteSpace: "pre-wrap" }}>
        <small>{l.fragmento}</small>
      </blockquote>
    </>
  );
}

function Duda({ d, ocupado, accion }: { d: Decision; ocupado: boolean; accion: (ruta: string, json?: object) => void }) {
  const [elegido, setElegido] = useState<string>(d.candidatos[0] ? String(d.candidatos[0].id) : "");
  const [otro, setOtro] = useState("");
  const [reemplazar, setReemplazar] = useState(false);
  const yaDecidido = (d.motivo ?? "").includes("ya tiene una decisión");
  const pendiente = d.estado === "pendiente";
  const casoId = elegido === "otro" ? Number(otro) : Number(elegido);
  return (
    <div className="tarjeta" style={{ marginBottom: "1rem" }}>
      <Leido d={d} />
      {d.motivo ? <Mensaje tipo={d.cruce === "no_verificado" ? "error" : "info"}>{d.motivo}</Mensaje> : null}
      {!pendiente ? (
        <p>
          {ESTADO[d.estado]}
          {d.caso ? ` en el caso #${d.caso.id}` : ""}
          {d.revisado_por ? ` por ${d.revisado_por}` : ""}.
        </p>
      ) : (
        <>
          {d.cruce !== "no_verificado" ? (
            <>
              <label htmlFor={`caso-${d.id}`}>¿A qué caso corresponde?</label>
              <select id={`caso-${d.id}`} value={elegido} onChange={(e) => setElegido(e.target.value)}>
                <option value="">Elija el caso…</option>
                {d.candidatos.map((c) => (
                  <option key={c.id} value={c.id}>
                    {nombreCaso(c)}
                  </option>
                ))}
                <option value="otro">Otro caso (escribir el número)</option>
              </select>
              {elegido === "otro" ? (
                <input
                  aria-label="Número del caso"
                  inputMode="numeric"
                  value={otro}
                  onChange={(e) => setOtro(e.target.value.replace(/\D/g, ""))}
                  placeholder="Número del caso, p. ej. 12"
                />
              ) : null}
            </>
          ) : null}
          {yaDecidido && d.cruce !== "no_verificado" ? (
            <label>
              <input type="checkbox" checked={reemplazar} onChange={(e) => setReemplazar(e.target.checked)} /> Reemplazar la decisión del
              Consejo que ya está registrada en ese caso
            </label>
          ) : null}
          <div className="botones">
            {d.cruce !== "no_verificado" ? (
              <button
                type="button"
                disabled={ocupado || !casoId || (yaDecidido && !reemplazar)}
                onClick={() => accion(`/decisiones/${d.id}/confirmar`, { caso_id: casoId, reemplazar })}
              >
                Asignar a este caso
              </button>
            ) : null}
            <button type="button" className="secundario" disabled={ocupado} onClick={() => accion(`/decisiones/${d.id}/descartar`)}>
              Descartar
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function Revision({ acta, ocupado, accion }: { acta: Acta; ocupado: boolean; accion: (ruta: string, json?: object) => void }) {
  const exactosPendientes = acta.cruzaron.filter((d) => d.estado === "pendiente").length;
  return (
    <>
      <h2>
        {acta.instancia_texto} · Acta {acta.numero ?? "sin número"}
        {acta.fecha ? ` del ${acta.fecha}` : ""}
      </h2>
      <p>
        <small>
          {acta.archivo} · subida por {acta.subido_por} · {acta.pendientes} decisión(es) sin revisar
        </small>
      </p>

      <h2>Cruzaron ({acta.cruzaron.length})</h2>
      <p>Coinciden con un solo caso por documento o número de caso. Revíselas y confírmelas.</p>
      {acta.cruzaron.length === 0 ? <p>Ninguna.</p> : null}
      {acta.cruzaron.length > 0 ? (
        <div className="tabla">
          <table>
            <thead>
              <tr>
                <th>Lo que dice el acta</th>
                <th>Caso de MemorIA</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {acta.cruzaron.map((d) => (
                <tr key={d.id}>
                  <td>
                    <Leido d={d} />
                  </td>
                  <td>
                    {d.caso ? (
                      <>
                        <Link href={`/actas/caso?id=${d.caso.id}`}>{nombreCaso(d.caso)}</Link>
                        <div>
                          <small>Comité: {d.caso.recomendacion}</small>
                        </div>
                      </>
                    ) : (
                      "Caso de otra área"
                    )}
                  </td>
                  <td>
                    {ESTADO[d.estado]}
                    {d.estado === "pendiente" ? (
                      <div className="botones">
                        <button type="button" disabled={ocupado || !d.caso} onClick={() => accion(`/decisiones/${d.id}/confirmar`, {})}>
                          Confirmar
                        </button>
                        <button type="button" className="secundario" disabled={ocupado} onClick={() => accion(`/decisiones/${d.id}/descartar`)}>
                          Descartar
                        </button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {exactosPendientes > 1 ? (
        <div className="botones">
          <button type="button" disabled={ocupado} onClick={() => accion("/confirmar-exactos")}>
            Confirmar los {exactosPendientes} cruces
          </button>
        </div>
      ) : null}

      <h2>Quedaron en duda ({acta.en_duda.length})</h2>
      <p>No cruzaron con certeza. Asigne el caso a mano o descarte la decisión; MemorIA no adivina.</p>
      {acta.en_duda.length === 0 ? <p>Ninguna.</p> : null}
      {acta.en_duda.map((d) => (
        <Duda key={d.id} d={d} ocupado={ocupado} accion={accion} />
      ))}

      <h2>Decisiones sin caso en MemorIA ({acta.sin_caso.length})</h2>
      <p>El acta las trae, pero ningún caso de MemorIA coincide. Si sí corresponde a un caso, asígnelo a mano.</p>
      {acta.sin_caso.map((d) => (
        <Duda key={d.id} d={d} ocupado={ocupado} accion={accion} />
      ))}

      <h2>Casos recomendados que no aparecen en el acta ({acta.no_aparecieron.length})</h2>
      <p>Siguen «pendientes de acta del Consejo».</p>
      <ul>
        {acta.no_aparecieron.map((c) => (
          <li key={c.id}>
            <Link href={`/actas/caso?id=${c.id}`}>{nombreCaso(c)}</Link> · {c.recomendacion}
          </li>
        ))}
      </ul>
    </>
  );
}

export default function ActaConsejo() {
  const { token } = useSesion();
  const t = token("actas");
  const [lista, setLista] = useState<Lista | null>(null);
  const [acta, setActa] = useState<Acta | null>(null);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [instancia, setInstancia] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargarLista = useCallback(() => {
    if (!t) return;
    llamar<Lista>("actas", "/actas/consejo", { token: t })
      .then(setLista)
      .catch((e: Error) => setError(e.message));
  }, [t]);

  useEffect(() => {
    cargarLista();
  }, [cargarLista]);

  const abrir = async (id: number) => {
    setError(null);
    setAviso(null);
    try {
      setActa(await llamar<Acta>("actas", `/actas/consejo/${id}`, { token: t }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const subir = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!archivo) return;
    setOcupado(true);
    setError(null);
    setAviso(null);
    const form = new FormData();
    form.append("archivo", archivo);
    if (instancia) form.append("instancia", instancia);
    try {
      setActa(await llamar<Acta>("actas", "/actas/consejo", { token: t, form }));
      setAviso("Acta leída. Nada se ha registrado todavía: revise y confirme.");
      cargarLista();
    } catch (err) {
      setError((err as Error).message);
    }
    setOcupado(false);
  };

  const accion = async (ruta: string, json?: object) => {
    if (!acta) return;
    setOcupado(true);
    setError(null);
    setAviso(null);
    try {
      setActa(await llamar<Acta>("actas", `/actas/consejo/${acta.id}${ruta}`, { token: t, json, metodo: "POST" }));
      setAviso("Guardado.");
      cargarLista();
    } catch (err) {
      setError((err as Error).message);
    }
    setOcupado(false);
  };

  return (
    <Pantalla
      titulo="Acta del Consejo"
      servicio="actas"
      roles={["administrativa", "admin"]}
      hace={[
        "Lee el acta del Consejo (PDF con texto o Word) y copia cada decisión con su texto literal.",
        "Cruza cada decisión con los casos por número de caso, documento y nombre.",
        "Registra en el caso la decisión que usted confirme; el programa la ve en la ficha.",
      ]}
      noHace={[
        "No registra nada sin que usted lo confirme.",
        "No adivina: lo que no cruza con certeza queda en duda para que usted lo asigne o lo descarte.",
        "No acepta un fragmento que no esté literal en el acta.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso ? <Mensaje tipo="exito">{aviso}</Mensaje> : null}

      <form onSubmit={subir}>
        <h2>Subir un acta</h2>
        <label htmlFor="acta">
          Acta del Consejo
          <span className="ayuda">PDF con texto o Word (.docx). Si es un escaneo, pida la versión digital.</span>
        </label>
        <input
          id="acta"
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={(e) => setArchivo(e.target.files?.[0] ?? null)}
        />
        <label htmlFor="instancia">
          Instancia
          <span className="ayuda">Si la deja en automático, se toma del encabezado del acta.</span>
        </label>
        <select id="instancia" value={instancia} onChange={(e) => setInstancia(e.target.value)}>
          <option value="">Automático</option>
          {lista?.instancias.map((i) => (
            <option key={i.clave} value={i.clave}>
              {i.nombre}
            </option>
          ))}
        </select>
        <div className="botones">
          <button type="submit" disabled={ocupado || !archivo}>
            {ocupado ? "Leyendo el acta… (puede tardar un minuto)" : "Leer el acta"}
          </button>
        </div>
      </form>

      {lista && lista.actas.length > 0 ? (
        <>
          <h2>Actas subidas</h2>
          <ul>
            {lista.actas.map((a) => (
              <li key={a.id}>
                <button type="button" className="secundario" onClick={() => abrir(a.id)}>
                  {a.instancia_texto} · Acta {a.numero ?? "sin número"}
                  {a.fecha ? ` del ${a.fecha}` : ""}
                </button>{" "}
                <small>
                  {a.decisiones} decisión(es) · {a.pendientes} sin revisar
                </small>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {acta ? <Revision acta={acta} ocupado={ocupado} accion={accion} /> : null}
    </Pantalla>
  );
}
