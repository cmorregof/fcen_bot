// Tipos de la API web de calidad (plan → objetivos → acciones).

export type Conteo = Record<string, number>;

export type Soporte = { tipo: string; valor: string; por: string | null; fecha: string };

export type Accion = {
  codigo: string;
  descripcion: string;
  indicador: string;
  responsables: string;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  fechas_fin_anteriores: string[];
  avance: number | null;
  estado: string;
  proxima: boolean;
  reprogramada: boolean;
  marcas: string[];
  evidencias: string;
  tareas: number;
  soportes: Soporte[];
};

export type ResumenPlan = {
  programa: string;
  acciones: number;
  avance: number | null;
  conteo: Conteo;
  reprogramadas: number;
  proximo_corte: { fecha: string; estimado: boolean } | null;
};

export type PlanCompleto = ResumenPlan & {
  hoy: string;
  archivo: string;
  alertas: string[];
  objetivos: { codigo: string; texto: string; meta: string; acciones: Accion[] }[];
};

export function porcentaje(v: number | null | undefined): string {
  return v === null || v === undefined ? "sin dato" : `${Math.round(v)} %`;
}
