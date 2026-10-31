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
    descripcion: "Preparar los casos de estudiantes, ver la ficha y registrar la recomendación.",
    servicio: "actas",
    roles: ["administrativa"],
  },
  {
    ruta: "/actas/documentos",
    titulo: "Oficio y acta",
    descripcion: "Descargar el borrador del oficio y del acta en Word.",
    servicio: "actas",
    roles: ["administrativa"],
  },
  {
    ruta: "/actas/consejo",
    titulo: "Acta del Consejo",
    descripcion: "Subir el acta del Consejo, revisar el cruce con los casos y confirmar las decisiones.",
    servicio: "actas",
    roles: ["administrativa", "admin"],
  },
  {
    ruta: "/actas",
    titulo: "Consultar casos",
    descripcion: "Leer las fichas de su área y dejar su concepto.",
    servicio: "actas",
    roles: ["comite"],
  },
  {
    ruta: "/secretaria",
    titulo: "Notificaciones",
    descripcion: "Registrar número y fechas del oficio o resolución de cada caso decidido, y el Excel de tiempos de respuesta.",
    servicio: "actas",
    roles: ["secretaria", "admin"],
  },
  {
    ruta: "/indicadores",
    titulo: "Indicadores",
    descripcion: "Casos, recomendaciones, decisiones del Consejo y tiempos de respuesta, con Excel.",
    servicio: "actas",
    roles: ["administrativa", "decanatura", "admin"],
  },
  {
    ruta: "/calidad",
    titulo: "Estado del plan",
    descripcion: "Ver objetivos, acciones y % de avance del plan por programa.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/importar",
    titulo: "Cargar el plan",
    descripcion: "Subir el Excel del plan, revisar los cambios y guardarlos.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/soportes",
    titulo: "Revisión de soportes",
    descripcion: "Subir los soportes de un programa y recibir una propuesta de cierre para revisar.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/avance",
    titulo: "Borrador de avance del corte",
    descripcion: "Proponer la descripción de avance de cada acción en un corte, con sus fuentes, para aprobar o editar.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/alertas",
    titulo: "Alertas",
    descripcion: "Ver qué acciones están vencidas, por vencer o «NO FUNCIONÓ».",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/calidad/a-quien",
    titulo: "¿A quién acudo?",
    descripcion: "Buscar qué dependencia atiende un trámite.",
    servicio: "calidad",
    roles: ["calidad", "admin"],
  },
  {
    ruta: "/admision",
    titulo: "Admisión",
    descripcion: "Cifras de uso del asistente y lista de chequeo de documentos.",
    servicio: "admision",
    roles: ["admision", "admin"],
  },
  {
    ruta: "/oportunidades",
    titulo: "Oportunidades: cola de revisión",
    descripcion: "Revisar las ofertas que el verificador no dio por buenas y aprobarlas o descartarlas.",
    servicio: "oportunidades",
    roles: ["oportunidades", "admin"],
  },
  {
    ruta: "/oportunidades/ofertas",
    titulo: "Ofertas y fuentes",
    descripcion: "Todas las ofertas por estado y programa, las fuentes de la vigía y sus corridas.",
    servicio: "oportunidades",
    roles: ["oportunidades", "decanatura", "admin"],
  },
  {
    ruta: "/oportunidades/empresas",
    titulo: "Empresas y entidades",
    descripcion: "Registro de empresas y entidades aliadas, con sus ofertas.",
    servicio: "oportunidades",
    roles: ["oportunidades", "decanatura", "admin"],
  },
  {
    ruta: "/oportunidades/boletin",
    titulo: "Boletín semanal",
    descripcion: "Revisar el borrador por programa, aprobarlo y publicarlo, y exportarlo para el correo.",
    servicio: "oportunidades",
    roles: ["oportunidades", "decanatura", "admin"],
  },
];
