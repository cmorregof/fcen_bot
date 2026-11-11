// Tipos y textos compartidos por las pantallas de casos de actas.
import type { Adjunto } from "@/app/actas/caso/Adjuntos";

export type Resumen = {
  id: number;
  estado: string;
  // Etapa de la línea única (app/services/flujo.py).
  etapa: string | null;
  etapa_texto: string | null;
  sentido: string;
  sentido_texto: string;
  programa: string | null;
  estudiante: string | null;
  objeto: string | null;
  creado: string | null;
  consejo: DecisionConsejo | null;
  // Fuera de la bandeja desde esta fecha (marca aparte de la etapa).
  archivado: string | null;
  // Terminado y aún en la bandeja: se puede archivar.
  archivable: boolean;
};

export type DecisionConsejo = {
  instancia_texto: string;
  sentido_texto: string;
  texto_decision: string;
  acta_numero: string | null;
  acta_fecha: string | null;
  fragmento: string;
  confirmado_por: string;
};

export type Evento = {
  accion: string;
  texto: string;
  hacia_texto: string;
  fecha: string | null;
  rol: string;
  persona: string | null;
  canal: string;
  detalle: string | null;
};

// Quién recomienda y quién decide (config/solicitudes.yaml).
export type Ruta = {
  recomienda: string;
  decide: string;
  por_confirmar: boolean;
  fuera_de_facultad: string[];
  tramites: { tipo: string; titulo: string; decide: string; por_confirmar: boolean; acto: string; nota: string | null }[];
};

export type Jurado = { nombre: string; vinculacion: string | null; correo: string | null };

export type LadoCuadro = {
  codigo: string | null;
  nombre: string | null;
  tipologia: string | null;
  creditos: number | null;
  nota: string | null;
};

export type Cuadro = {
  figura: string;
  origen: string | null;
  destino: string | null;
  filas: { origen: LadoCuadro; destino: LadoCuadro }[];
};

export type Detalle = Resumen & {
  programa_clave: string | null;
  extraccion: {
    documento?: string | null;
    fecha_solicitud?: string | null;
    justificacion_breve?: string;
    dudas?: string[];
    asignaturas?: { codigo: string | null; nombre: string; grupo: string | null; accion: string }[];
    equivalencias?: Cuadro[];
    jurados?: Jurado[];
    proyecto?: { titulo: string | null; director: string | null; codirector: string | null; linea: string | null } | null;
  } | null;
  ruta: Ruta;
  alertas: { nivel: string; mensaje: string }[];
  cifras: Record<string, number | null> | null;
  nota_comite: string | null;
  conceptos: { miembro: string; texto: string }[];
  miembros: string[];
  programas: { clave: string; nombre: string }[];
  imagenes: number;
  anexos: string[];
  adjuntos: Adjunto[];
  tipos_adjuntos: string;
  // Hay decisión final del Consejo de Facultad: se puede bajar el borrador del oficio.
  oficio_consejo: boolean;
  etapa: string;
  etapa_texto: string;
  prerrevision: string | null;
  linea: Evento[];
  siguiente: { paso: string; responsable: string } | null;
  tramos: { nombre: string; dias: number | null }[];
  // Botones de la línea que la administrativa puede usar ahora.
  acciones: string[];
  aviso?: string | null;
};

// Grupos de etapas para filtrar la bandeja y dar color a la etiqueta.
export type Grupo = "preparar" | "comite" | "consejo" | "terminados";

export const GRUPO: Record<string, Grupo> = {
  llegada: "preparar",
  incompleta: "preparar",
  en_comite: "comite",
  recomendada: "comite",
  en_consejo: "consejo",
  improcedente: "terminados",
  decidida: "terminados",
  expedida: "terminados",
  notificada: "terminados",
  archivada: "terminados",
  descartada: "terminados",
};

export const NOMBRE_GRUPO: Record<Grupo, string> = {
  preparar: "Por preparar",
  comite: "En comité",
  consejo: "En el Consejo",
  terminados: "Terminados",
};

const CLASE_GRUPO: Record<Grupo, string> = {
  preparar: "proxima",
  comite: "encurso",
  consejo: "encurso",
  terminados: "cumplida",
};

export function claseEtapa(etapa: string | null): string {
  const g = etapa ? GRUPO[etapa] : undefined;
  if (etapa === "improcedente" || etapa === "descartada") return "pendiente";
  return g ? CLASE_GRUPO[g] : "pendiente";
}

export const PRERREVISION: Record<string, string> = {
  procedente: "Procedente",
  improcedente: "Improcedente",
  incompleto: "Incompleta",
};

export const CANAL: Record<string, string> = {
  telegram: "Telegram",
  web: "web",
  sistema: "automático",
  migracion: "dato anterior a la línea",
  practica: "práctica",
};
