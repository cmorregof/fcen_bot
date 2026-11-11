"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Mensaje, Pantalla } from "@/components/Pantalla";
import { claseEtapa, GRUPO, type Grupo, NOMBRE_GRUPO, type Resumen } from "@/lib/actas";
import { llamar } from "@/lib/api";
import { useSesion } from "@/lib/sesion";

type Vista = "bandeja" | "archivados";
type Filtro = "todos" | Grupo;

const FILTROS: Filtro[] = ["todos", "preparar", "comite", "consejo", "terminados"];

function plural(n: number, uno: string, varios: string) {
  return `${n} ${n === 1 ? uno : varios}`;
}

export default function Casos() {
  const { token, tieneRol } = useSesion();
  const t = token("actas");
  const administrativa = tieneRol("actas", "administrativa");
  const [vista, setVista] = useState<Vista>("bandeja");
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [buscar, setBuscar] = useState("");
  const [datos, setDatos] = useState<{ area: string; casos: Resumen[] } | null>(null);
  const [marcados, setMarcados] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    if (!t) return;
    setDatos(null);
    llamar<{ area: string; casos: Resumen[] }>("actas", `/actas/casos${vista === "archivados" ? "?archivados=true" : ""}`, { token: t })
      .then(setDatos)
      .catch((e: Error) => setError(e.message));
  }, [t, vista]);

  useEffect(() => {
    cargar();
    setMarcados(new Set());
  }, [cargar]);

  const casos = useMemo(() => datos?.casos ?? [], [datos]);
  const cuenta = (f: Filtro) => (f === "todos" ? casos.length : casos.filter((c) => c.etapa && GRUPO[c.etapa] === f).length);
  const texto = buscar.trim().toLowerCase();
  const visibles = useMemo(
    () =>
      casos.filter(
        (c) =>
          (vista === "archivados" || filtro === "todos" || (c.etapa && GRUPO[c.etapa] === filtro)) &&
          (!texto || `#${c.id} ${c.id} ${c.estudiante ?? ""} ${c.objeto ?? ""}`.toLowerCase().includes(texto)),
      ),
    [casos, filtro, texto, vista],
  );
  // En la bandeja se marcan los terminados para archivarlos; en archivados, cualquiera para devolverlo.
  const seleccionables = administrativa ? visibles.filter((c) => (vista === "archivados" ? true : c.archivable)) : [];
  const elegidos = seleccionables.filter((c) => marcados.has(c.id)).map((c) => c.id);
  const todos = seleccionables.length > 0 && elegidos.length === seleccionables.length;

  const marcar = (id: number, si: boolean) =>
    setMarcados((m) => {
      const n = new Set(m);
      if (si) n.add(id);
      else n.delete(id);
      return n;
    });

  const mover = async () => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    const archivar = vista === "bandeja";
    try {
      await llamar("actas", `/actas/casos/${archivar ? "archivar" : "desarchivar"}`, {
        token: t,
        json: { ids: elegidos },
        metodo: "POST",
      });
      setAviso(
        archivar
          ? `${plural(elegidos.length, "caso archivado", "casos archivados")}. Los encuentra en «Archivados».`
          : `${plural(elegidos.length, "caso volvió", "casos volvieron")} a la bandeja.`,
      );
      setMarcados(new Set());
      cargar();
    } catch (e) {
      setError((e as Error).message);
    }
    setOcupado(false);
  };

  return (
    <Pantalla
      titulo={administrativa ? "Casos del comité" : "Consultar casos del comité"}
      servicio="actas"
      roles={["administrativa", "comite"]}
      hace={
        administrativa
          ? [
              "Lista los casos de su área: por defecto, los que siguen en su bandeja.",
              "Prepara un caso nuevo paso a paso.",
              "Archiva los casos terminados (decididos, notificados, improcedentes o descartados) para sacarlos de la bandeja. Se pueden devolver.",
            ]
          : ["Lista los casos de su área para leer la ficha y dejar su concepto."]
      }
      noHace={[
        "No decide: el comité solo recomienda aprobar o no aprobar, y decide el Consejo.",
        "Archivar no borra el caso ni cambia su etapa.",
        "No muestra casos de otras áreas.",
      ]}
    >
      {administrativa ? (
        <div className="botones">
          <Link href="/actas/nuevo" className="boton">
            Preparar un caso nuevo
          </Link>
        </div>
      ) : null}

      <h2>
        {vista === "bandeja" ? "Casos en su bandeja" : "Casos archivados"}
        {datos ? <small> · {datos.area}</small> : null}
      </h2>

      <div className="filtros" role="group" aria-label="Filtrar los casos">
        {FILTROS.map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={vista === "bandeja" && filtro === f}
            onClick={() => {
              setVista("bandeja");
              setFiltro(f);
            }}
          >
            {f === "todos" ? "Todos" : NOMBRE_GRUPO[f]}
            {vista === "bandeja" && datos ? <span className="cuenta"> ({cuenta(f)})</span> : null}
          </button>
        ))}
        <button type="button" aria-pressed={vista === "archivados"} onClick={() => setVista("archivados")}>
          Archivados
        </button>
      </div>

      {casos.length > 5 ? (
        <>
          <label htmlFor="buscar">Buscar por nombre, número o solicitud</label>
          <input id="buscar" type="search" className="buscar" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
        </>
      ) : null}

      {error ? <Mensaje tipo="error">{error}</Mensaje> : null}
      {aviso ? <Mensaje tipo="exito">{aviso}</Mensaje> : null}
      {!datos && !error ? <p>Cargando…</p> : null}
      {datos && casos.length === 0 ? (
        <p>{vista === "bandeja" ? "No hay casos en su bandeja." : "No hay casos archivados."}</p>
      ) : null}
      {datos && casos.length > 0 && visibles.length === 0 ? <p>Ningún caso coincide con el filtro.</p> : null}

      {seleccionables.length > 0 ? (
        <div className="lote">
          <label>
            <input
              type="checkbox"
              checked={todos}
              onChange={(e) => setMarcados(e.target.checked ? new Set(seleccionables.map((c) => c.id)) : new Set())}
            />
            {vista === "bandeja" ? `Marcar los terminados (${seleccionables.length})` : `Marcar todos (${seleccionables.length})`}
          </label>
          <button type="button" className="secundario" disabled={ocupado || elegidos.length === 0} onClick={mover}>
            {ocupado
              ? "Guardando…"
              : vista === "bandeja"
                ? `Archivar ${elegidos.length > 0 ? plural(elegidos.length, "caso", "casos") : "los marcados"}`
                : `Devolver a la bandeja${elegidos.length > 0 ? ` (${elegidos.length})` : ""}`}
          </button>
        </div>
      ) : null}

      {visibles.length > 0 ? (
        <ul className="lista-casos">
          {visibles.map((c) => {
            const seleccionable = seleccionables.includes(c);
            return (
              <li key={c.id}>
                {seleccionable ? (
                  <label className="marcar">
                    <input
                      type="checkbox"
                      checked={marcados.has(c.id)}
                      onChange={(e) => marcar(c.id, e.target.checked)}
                      aria-label={`Marcar el caso #${c.id}`}
                    />
                  </label>
                ) : administrativa && seleccionables.length > 0 ? (
                  <span className="vacio" />
                ) : null}
                <div className="quien">
                  <Link href={`/actas/caso?id=${c.id}`}>{c.estudiante ?? `Caso sin leer`}</Link>
                  <small>
                    Caso #{c.id}
                    {c.objeto ? ` · ${c.objeto}` : ""}
                  </small>
                </div>
                <div className="etapa">
                  <span className={`estado ${claseEtapa(c.etapa)}`}>{c.etapa_texto ?? "Sin etapa"}</span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </Pantalla>
  );
}
