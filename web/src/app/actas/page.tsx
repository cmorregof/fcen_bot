"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Resumen = {
  id: number;
  estado: string;
  sentido_texto: string;
  programa: string | null;
  estudiante: string | null;
  objeto: string | null;
  consejo: { sentido_texto: string; instancia_texto: string } | null;
};

const ESTADO: Record<string, string> = {
  abierto: "Sin leer",
  procesando: "Leyendo",
  listo: "Ficha lista",
  error: "Con error",
  cerrado: "Cerrado",
  decidido_consejo: "Decidido por el Consejo",
};

function NuevoCaso() {
  const { token } = useSesion();
  const router = useRouter();
  const [texto, setTexto] = useState("");
  const [imagenes, setImagenes] = useState<FileList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paso, setPaso] = useState<"" | "guardando" | "leyendo">("");

  const crear = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const form = new FormData();
    form.append("texto", texto);
    for (const f of Array.from(imagenes ?? [])) form.append("imagenes", f);
    try {
      setPaso("guardando");
      const { id } = await llamar<{ id: number }>("actas", "/actas/casos", { token: token("actas"), form });
      setPaso("leyendo");
      try {
        await llamar("actas", `/actas/casos/${id}/procesar`, { token: token("actas"), metodo: "POST" });
      } catch {
        /* la ficha mostrará el error y permitirá reintentar */
      }
      router.push(`/actas/caso?id=${id}`);
    } catch (err) {
      setError((err as Error).message);
      setPaso("");
    }
  };

  return (
    <form onSubmit={crear}>
      <h2>Preparar un caso nuevo</h2>
      <label htmlFor="correo">
        1. Pegue aquí el correo del estudiante
        <span className="ayuda">Tal como llegó: con la fecha, el nombre y el cuerpo del mensaje.</span>
      </label>
      <textarea id="correo" value={texto} onChange={(e) => setTexto(e.target.value)} />
      <label htmlFor="pantallazos">
        2. Adjunte los pantallazos del SIA y de la solicitud
        <span className="ayuda">Imágenes JPG o PNG. Puede elegir varias a la vez.</span>
      </label>
      <input id="pantallazos" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(e) => setImagenes(e.target.files)} />
      <div className="botones">
        <button type="submit" disabled={paso !== "" || (!texto.trim() && !imagenes?.length)}>
          {paso === "guardando" ? "Guardando…" : paso === "leyendo" ? "Leyendo el caso… (puede tardar un minuto)" : "3. Crear y leer el caso"}
        </button>
      </div>
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
    </form>
  );
}

export default function Casos() {
  const { token, tieneRol } = useSesion();
  const [datos, setDatos] = useState<{ area: string; casos: Resumen[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const t = token("actas");
  const administrativa = tieneRol("actas", "administrativa");

  useEffect(() => {
    if (!t) return;
    llamar<{ area: string; casos: Resumen[] }>("actas", "/actas/casos", { token: t })
      .then(setDatos)
      .catch((e: Error) => setError(e.message));
  }, [t]);

  return (
    <Pantalla
      titulo={administrativa ? "Casos del comité asesor" : "Consultar casos del comité"}
      servicio="actas"
      roles={["administrativa", "comite"]}
      hace={
        administrativa
          ? [
              "Crea un caso con el correo y los pantallazos, y lo lee para armar la ficha con alertas.",
              "Lista los casos de su área para abrir su ficha.",
            ]
          : ["Lista los casos de su área para leer la ficha y dejar su concepto."]
      }
      noHace={[
        "No decide: el comité solo recomienda aprobar o no aprobar, y decide el Consejo.",
        "No muestra casos de otras áreas.",
      ]}
    >
      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {administrativa ? <NuevoCaso /> : null}
      <h2>Casos recientes {datos ? `· ${datos.area}` : ""}</h2>
      {datos?.casos.length === 0 ? <p>Aún no hay casos.</p> : null}
      {datos && datos.casos.length > 0 ? (
        <div className="tabla">
          <table>
            <thead>
              <tr>
                <th>Caso</th>
                <th>Estudiante y solicitud</th>
                <th>Estado</th>
                <th>Recomendación</th>
              </tr>
            </thead>
            <tbody>
              {datos.casos.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link href={`/actas/caso?id=${c.id}`}>Abrir caso #{c.id}</Link>
                  </td>
                  <td>
                    {c.estudiante ?? "Sin leer"}
                    {c.objeto ? <div><small>{c.objeto}</small></div> : null}
                    {c.programa ? <div><small>{c.programa}</small></div> : null}
                  </td>
                  <td>{ESTADO[c.estado] ?? c.estado}</td>
                  <td>
                    {c.sentido_texto}
                    {c.consejo ? (
                      <div>
                        <small>
                          {c.consejo.instancia_texto}: {c.consejo.sentido_texto}
                        </small>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Pantalla>
  );
}
