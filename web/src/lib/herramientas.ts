import { Servicio } from "./api";
import { Rol } from "./sesion";

export type Herramienta = {
  ruta: string;
  titulo: string;
  descripcion: string;
  servicio: Servicio;
  roles: Rol[];
};

// Lo que ve cada rol. El backend vuelve a comprobarlo en cada llamada.
export const HERRAMIENTAS: Herramienta[] = [
  {
    ruta: "/actas",
    titulo: "Casos del comité",
    descripcion: "Preparar casos y registrar la recomendación.",
    servicio: "actas",
    roles: ["administrativa"],
  },
  {
    ruta: "/actas/documentos",
    titulo: "Oficio y acta",
    descripcion: "Descargar en Word y firmar.",
    servicio: "actas",
    roles: ["administrativa", "admin"],
  },
  {
    ruta: "/actas/consejo",
    titulo: "Acta del Consejo",
    descripcion: "Subirla y confirmar las decisiones.",
    servicio: "actas",
    roles: ["administrativa", "admin"],
  },
  {
    ruta: "/actas",
    titulo: "Consultar casos",
    descripcion: "Leer las fichas y dejar su concepto.",
    servicio: "actas",
    roles: ["comite"],
  },
  {
    ruta: "/secretaria",
    titulo: "Notificaciones",
    descripcion: "Número y fechas de cada oficio o resolución.",
    servicio: "actas",
    roles: ["secretaria", "admin"],
  },
  {
    ruta: "/indicadores",
    titulo: "Indicadores",
    descripcion: "Casos, decisiones y tiempos, con Excel.",
    servicio: "actas",
    roles: ["administrativa", "decanatura", "admin"],
  },
  {
    ruta: "/calidad",
    titulo: "Estado del plan",
    descripcion: "Avance del plan por programa.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/importar",
    titulo: "Cargar el plan",
    descripcion: "Subir el Excel y confirmar cambios.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/soportes",
    titulo: "Revisión de soportes",
    descripcion: "Revisar evidencias y proponer el cierre.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/avance",
    titulo: "Avance del corte",
    descripcion: "Texto de avance por acción, con fuentes.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/alertas",
    titulo: "Alertas",
    descripcion: "Acciones vencidas o por vencer.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/a-quien",
    titulo: "¿A quién acudo?",
    descripcion: "Qué dependencia atiende un trámite.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/admision",
    titulo: "Admisión",
    descripcion: "Cifras de uso y lista de chequeo.",
    servicio: "admision",
    roles: ["admision", "admin"],
  },
  {
    ruta: "/oportunidades",
    titulo: "Ofertas por revisar",
    descripcion: "Aprobar o descartar ofertas dudosas.",
    servicio: "oportunidades",
    roles: ["oportunidades", "admin"],
  },
  {
    ruta: "/oportunidades/ofertas",
    titulo: "Ofertas y fuentes",
    descripcion: "Todas las ofertas y sus fuentes.",
    servicio: "oportunidades",
    roles: ["oportunidades", "decanatura", "admin"],
  },
  {
    ruta: "/oportunidades/empresas",
    titulo: "Empresas y entidades",
    descripcion: "Aliadas y sus ofertas.",
    servicio: "oportunidades",
    roles: ["oportunidades", "decanatura", "admin"],
  },
  {
    ruta: "/oportunidades/boletin",
    titulo: "Boletín semanal",
    descripcion: "Revisar, aprobar y publicar.",
    servicio: "oportunidades",
    roles: ["oportunidades", "decanatura", "admin"],
  },
];
