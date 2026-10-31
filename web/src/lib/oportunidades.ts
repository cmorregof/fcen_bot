// Tipos y utilidades del servicio de oportunidades.

export type Oferta = {
  id: number;
  fuente: string;
  url: string;
  titulo: string;
  entidad: string;
  entidad_id: number | null;
  tipo: string;
  programas: string[];
  areas: string[];
  resumen: string;
  requisitos: string;
  fecha_cierre: string | null;
  modalidad: string;
  lugar: string;
  estado: string;
  motivos: string[];
  dudas: string[];
  motivo_descarte: string | null;
  verificado_por: string | null;
  verificado: string | null;
  aprobado_por: string | null;
  aprobado: string | null;
  publicado: string | null;
  descartado_por: string | null;
};

export type Catalogos = {
  programas: Record<string, string>;
  tipos: Record<string, string>;
  estados: Record<string, string>;
  tipos_entidad: string[];
  vigia_activa: boolean;
};

export const MODALIDADES: Record<string, string> = {
  presencial: "Presencial",
  remota: "Remota",
  hibrida: "Híbrida",
  sin_dato: "Sin dato",
};

export const nombresProgramas = (o: Oferta, c: Catalogos | null) =>
  o.programas.length === 0 ? "sin programa" : o.programas.map((p) => c?.programas[p] ?? p).join(", ");
