// Cliente de los backends. Cada servicio tiene su propia URL, su propia
// sesión y su propia base: la web nunca mezcla datos entre servicios.

export type Servicio = "actas" | "calidad" | "admision" | "oportunidades";

// Despliegue de práctica (capacitaciones): NEXT_PUBLIC_PRACTICA=true. Entonces
// las URLs salen SOLO de las variables *_PRACTICA, sin volver a las de
// producción: si falta una, ese servicio queda sin configurar y la web nunca
// escribe en la base real.
export const PRACTICA = process.env.NEXT_PUBLIC_PRACTICA === "true";

const URLS: Record<Servicio, string> = PRACTICA
  ? {
      actas: process.env.NEXT_PUBLIC_API_ACTAS_PRACTICA ?? "",
      calidad: process.env.NEXT_PUBLIC_API_CALIDAD_PRACTICA ?? "",
      admision: process.env.NEXT_PUBLIC_API_ADMISION_PRACTICA ?? "",
      oportunidades: process.env.NEXT_PUBLIC_API_OPORTUNIDADES_PRACTICA ?? "",
    }
  : {
      actas: process.env.NEXT_PUBLIC_API_ACTAS ?? "",
      calidad: process.env.NEXT_PUBLIC_API_CALIDAD ?? "",
      admision: process.env.NEXT_PUBLIC_API_ADMISION ?? "",
      oportunidades: process.env.NEXT_PUBLIC_API_OPORTUNIDADES ?? "",
    };

export const SERVICIOS: Record<Servicio, { nombre: string; url: string }> = {
  actas: { nombre: "Comités asesores", url: URLS.actas },
  calidad: { nombre: "Calidad", url: URLS.calidad },
  admision: { nombre: "Admisión", url: URLS.admision },
  oportunidades: { nombre: "Oportunidades", url: URLS.oportunidades },
};

export const servicioConfigurado = (s: Servicio) => SERVICIOS[s].url !== "";

export class ErrorApi extends Error {
  constructor(
    public estado: number,
    mensaje: string,
  ) {
    super(mensaje);
  }
}

const MENSAJES: Record<number, string> = {
  401: "Su sesión venció o no ha ingresado. Vuelva a ingresar.",
  403: "Esta herramienta no está habilitada para su usuario.",
  404: "No se encontró lo que busca.",
  502: "El servicio no pudo completar la tarea. Intente de nuevo en un momento.",
  503: "El servicio no está configurado todavía.",
};

export async function llamar<T>(
  servicio: Servicio,
  ruta: string,
  opciones: { token?: string | null; metodo?: string; json?: unknown; form?: FormData; archivo?: Blob } = {},
): Promise<T> {
  const base = SERVICIOS[servicio].url;
  if (!base) throw new ErrorApi(0, "Este servicio no está disponible.");
  const cabeceras: Record<string, string> = {};
  if (opciones.token) cabeceras.Authorization = `Bearer ${opciones.token}`;
  let cuerpo: BodyInit | undefined;
  if (opciones.form) cuerpo = opciones.form;
  else if (opciones.archivo) {
    // El archivo va como cuerpo de la petición, sin multipart.
    cabeceras["Content-Type"] = "application/octet-stream";
    cuerpo = opciones.archivo;
  }
  else if (opciones.json !== undefined) {
    cabeceras["Content-Type"] = "application/json";
    cuerpo = JSON.stringify(opciones.json);
  }
  let r: Response;
  try {
    r = await fetch(`${base}/api/web${ruta}`, {
      method: opciones.metodo ?? (cuerpo ? "POST" : "GET"),
      headers: cabeceras,
      body: cuerpo,
    });
  } catch {
    throw new ErrorApi(0, "No hay conexión con el servicio. Revise su internet e intente de nuevo.");
  }
  if (!r.ok) {
    let detalle = "";
    try {
      const datos = await r.json();
      if (typeof datos.detail === "string") detalle = datos.detail;
    } catch {
      /* respuesta sin JSON */
    }
    throw new ErrorApi(r.status, detalle || MENSAJES[r.status] || "Ocurrió un error inesperado.");
  }
  const tipo = r.headers.get("Content-Type") ?? "";
  if (tipo.includes("application/json")) return (await r.json()) as T;
  return (await r.blob()) as T;
}

export function guardarArchivo(datos: Blob, nombre: string) {
  const url = URL.createObjectURL(datos);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}
