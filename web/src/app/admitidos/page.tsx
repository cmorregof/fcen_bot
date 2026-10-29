"use client";

import { useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";

type Aviso = {
  aviso: string;
  proposito: string;
  contacto: string;
  documentos: { clave: string; nombre: string }[];
  max_mb: number;
};
type Respuesta = { estado: string; credenciales: boolean; respuesta: string; citas: string[]; contacto: string };
type Revision = {
  estado: string;
  documento: string;
  problemas: string[];
  bien: { punto: string; detalle: string }[];
  corregir: { punto: string; detalle: string }[];
  aviso: string;
};

const AVISO_CREDENCIALES =
  "Escribió un correo o una contraseña. No los comparta: no los pedimos, no los usamos y no los guardamos.";

function Pregunta({ token, contacto }: { token: string; contacto: string }) {
  const [texto, setTexto] = useState("");
  const [resp, setResp] = useState<Respuesta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setOcupado(true);
        setError(null);
        try {
          setResp(await llamar<Respuesta>("admision", "/admision/preguntar", { token, json: { texto } }));
        } catch (err) {
          setError((err as Error).message);
        }
        setOcupado(false);
      }}
    >
      <h2>Hacer una pregunta sobre el listado de documentos</h2>
      <label htmlFor="pregunta">Su pregunta</label>
      <textarea id="pregunta" value={texto} onChange={(e) => setTexto(e.target.value)} required />
      <div className="botones">
        <button type="submit" disabled={ocupado}>
          {ocupado ? "Buscando…" : "Preguntar"}
        </button>
      </div>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {resp?.credenciales ? <Mensaje tipo="error">{AVISO_CREDENCIALES}</Mensaje> : null}
      {resp?.estado === "ok" ? (
        <Mensaje tipo="exito">
          {resp.respuesta}
          <br />
          <small>Fuente: {resp.citas.join("; ")}</small>
        </Mensaje>
      ) : null}
      {resp?.estado === "sin_respuesta" ? (
        <Mensaje tipo="info">
          Eso no aparece en el listado ni en la guía, así que no se lo podemos confirmar. Consúltelo con {contacto}.
        </Mensaje>
      ) : null}
      {resp && ["error", "sin_fuentes"].includes(resp.estado) ? (
        <Mensaje tipo="error">No pudimos responder ahora. Intente de nuevo en un rato.</Mensaje>
      ) : null}
    </form>
  );
}

function RevisarDocumento({ token, aviso }: { token: string; aviso: Aviso }) {
  const [clave, setClave] = useState("");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [res, setRes] = useState<Revision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (!archivo) return;
        setOcupado(true);
        setError(null);
        setRes(null);
        const form = new FormData();
        form.append("clave", clave);
        form.append("archivo", archivo);
        try {
          setRes(await llamar<Revision>("admision", "/admision/revisar", { token, form }));
        } catch (err) {
          setError((err as Error).message);
        }
        setOcupado(false);
      }}
    >
      <h2>Revisar un documento</h2>
      <label htmlFor="tipo">1. ¿Qué documento es?</label>
      <select id="tipo" value={clave} onChange={(e) => setClave(e.target.value)} required>
        <option value="">Elija el documento</option>
        {aviso.documentos.map((d) => (
          <option key={d.clave} value={d.clave}>
            {d.nombre}
          </option>
        ))}
      </select>
      <label htmlFor="archivo">
        2. Elija el archivo
        <span className="ayuda">PDF o foto (JPG o PNG), máximo {aviso.max_mb} MB.</span>
      </label>
      <input id="archivo" type="file" accept=".pdf,image/jpeg,image/png" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} required />
      <div className="botones">
        <button type="submit" disabled={ocupado}>
          {ocupado ? "Revisando… (puede tardar un minuto)" : "3. Revisar"}
        </button>
      </div>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {res?.estado === "problemas" ? (
        <Mensaje tipo="error">
          No pudimos revisar el archivo:
          <ul>
            {res.problemas.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
          Corríjalo y vuelva a intentarlo.
        </Mensaje>
      ) : null}
      {res && ["error", "sin_fuentes"].includes(res.estado) ? (
        <Mensaje tipo="error">No pudimos revisar el documento ahora. Intente de nuevo en un rato.</Mensaje>
      ) : null}
      {res?.estado === "ok" ? (
        <div>
          <h3>{res.documento}</h3>
          {res.bien.length > 0 ? (
            <Mensaje tipo="exito">
              Está bien:
              <ul>
                {res.bien.map((i) => (
                  <li key={i.punto}>{i.punto}</li>
                ))}
              </ul>
            </Mensaje>
          ) : null}
          {res.corregir.length > 0 ? (
            <Mensaje tipo="info">
              Por corregir:
              <ul>
                {res.corregir.map((i) => (
                  <li key={i.punto}>
                    {i.punto}: {i.detalle}
                  </li>
                ))}
              </ul>
            </Mensaje>
          ) : (
            <p>No vemos nada por corregir en estos puntos.</p>
          )}
          <p>
            <small>{res.aviso}</small>
          </p>
        </div>
      ) : null}
    </form>
  );
}

export default function Admitidos() {
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acepto, setAcepto] = useState<"" | "si" | "no">("");
  const [menor, setMenor] = useState<"" | "si" | "no">("");
  const [acudiente, setAcudiente] = useState(false);
  const [sesion, setSesion] = useState<{ token: string; puede_revisar: boolean } | null>(null);
  const [rechazo, setRechazo] = useState(false);

  useEffect(() => {
    llamar<Aviso>("admision", "/admision/aviso").then(setAviso).catch((e: Error) => setError(e.message));
  }, []);

  const continuar = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const r = await llamar<{ token: string | null; puede_revisar?: boolean }>("admision", "/admision/consentimiento", {
        json: { acepto: acepto === "si", menor: menor === "si", acudiente },
      });
      if (r.token) setSesion({ token: r.token, puede_revisar: Boolean(r.puede_revisar) });
      else setRechazo(true);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Pantalla
      titulo="Revise sus documentos de admisión"
      hace={[
        aviso?.proposito ?? "Le ayuda a revisar sus documentos antes de subirlos.",
        "Responde preguntas con el listado oficial de documentos.",
      ]}
      noHace={[
        "No sube nada por usted ni reemplaza la revisión oficial.",
        "No guarda sus documentos ni sus preguntas. Nunca le pedirá su correo ni su contraseña.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso && !sesion && !rechazo ? (
        <form onSubmit={continuar}>
          <h2>Aviso de tratamiento de datos</h2>
          <div className="aviso-datos">{aviso.aviso.replaceAll("**", "")}</div>
          <fieldset>
            <legend>¿Acepta el aviso de datos?</legend>
            <label className="opcion">
              <input type="radio" name="acepto" checked={acepto === "si"} onChange={() => setAcepto("si")} required /> Sí, acepto
            </label>
            <label className="opcion">
              <input type="radio" name="acepto" checked={acepto === "no"} onChange={() => setAcepto("no")} /> No acepto
            </label>
          </fieldset>
          {acepto === "si" ? (
            <fieldset>
              <legend>¿Tiene menos de 18 años?</legend>
              <label className="opcion">
                <input type="radio" name="menor" checked={menor === "si"} onChange={() => setMenor("si")} required /> Sí, soy menor de edad
              </label>
              <label className="opcion">
                <input type="radio" name="menor" checked={menor === "no"} onChange={() => setMenor("no")} /> No
              </label>
            </fieldset>
          ) : null}
          {acepto === "si" && menor === "si" ? (
            <label className="opcion">
              <input type="checkbox" checked={acudiente} onChange={(e) => setAcudiente(e.target.checked)} />
              Mi acudiente (quien tiene mi patria potestad) leyó el aviso y acepta.
            </label>
          ) : null}
          <div className="botones">
            <button type="submit" disabled={!acepto || (acepto === "si" && !menor)}>
              Continuar
            </button>
          </div>
        </form>
      ) : null}
      {rechazo ? (
        <Mensaje tipo="info">Entendido: no revisamos documentos ni guardamos nada. Puede volver cuando quiera.</Mensaje>
      ) : null}
      {sesion && aviso ? (
        <>
          <Pregunta token={sesion.token} contacto={aviso.contacto} />
          {sesion.puede_revisar ? (
            <RevisarDocumento token={sesion.token} aviso={aviso} />
          ) : (
            <Mensaje tipo="info">
              Para revisar documentos se necesita la aceptación de su acudiente. Puede hacer preguntas sobre el listado.
            </Mensaje>
          )}
        </>
      ) : null}
    </Pantalla>
  );
}
