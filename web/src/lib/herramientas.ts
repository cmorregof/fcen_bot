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
    ruta: "/actas",
    titulo: "Consultar casos",
    descripcion: "Leer las fichas de su área y dejar su concepto.",
    servicio: "actas",
    roles: ["comite"],
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
];
