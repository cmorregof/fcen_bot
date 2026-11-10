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

// Proxy de Vercel (next.config.ts): el navegador llama a /srv/<servicio> en el
// dominio de la web y Vercel reenvía a Railway. Así se llega aunque la red
// bloquee las IP de Railway. NEXT_PUBLIC_PROXY=false vuelve a la llamada
// directa (para descartar el proxy si algo falla).
export const PROXY = process.env.NEXT_PUBLIC_PROXY !== "false";

// Los archivos de más de esto van directo a Railway: Vercel no documenta el
// tope del cuerpo en rewrites externos y el de sus funciones es 4,5 MB. Un
// zip de soportes de calidad puede pesar cientos de MB.
export const MAXIMO_PROXY_BYTES = 4 * 1024 * 1024;

/** La raíz de las rutas de un servicio: el proxy, o Railway si `directo`. */
export function raiz(servicio: Servicio, directo = false): string {
  if (!servicioConfigurado(servicio)) return "";
  return PROXY && !directo ? `/srv/${servicio}` : SERVICIOS[servicio].url;
}

function pesoCuerpo(cuerpo: BodyInit | undefined): number {
  if (cuerpo instanceof Blob) return cuerpo.size;
  if (cuerpo instanceof FormData) {
    let total = 0;
    cuerpo.forEach((v) => {
      total += typeof v === "string" ? v.length : v.size;
    });
    return total;
  }
  return 0;
}

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
  413: "El archivo es demasiado grande para enviarlo.",
  502: "El servicio no pudo completar la tarea. Intente de nuevo en un momento.",
  503: "El servicio no está configurado todavía.",
  504: "El servicio tardó demasiado en responder. Intente de nuevo en un momento.",
};

export async function llamar<T>(
  servicio: Servicio,
  ruta: string,
  opciones: { token?: string | null; metodo?: string; json?: unknown; form?: FormData; archivo?: Blob } = {},
): Promise<T> {
  if (!servicioConfigurado(servicio)) throw new ErrorApi(0, "Este servicio no está disponible.");
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
  // Un archivo grande no cabe por el proxy: va directo a Railway (CORS).
  const directo = PROXY && pesoCuerpo(cuerpo) > MAXIMO_PROXY_BYTES;
  let r: Response;
  try {
    r = await fetch(`${raiz(servicio, directo)}/api/web${ruta}`, {
      method: opciones.metodo ?? (cuerpo ? "POST" : "GET"),
      headers: cabeceras,
      body: cuerpo,
    });
  } catch {
    if (directo) {
      const mb = Math.floor(MAXIMO_PROXY_BYTES / (1024 * 1024));
      throw new ErrorApi(
        0,
        `No se pudo enviar el archivo. Los archivos de más de ${mb} MB van directo al servidor del servicio, ` +
          "y esta red parece bloquearlo. Intente desde otra red (por ejemplo, los datos del celular) " +
          `o con un archivo de menos de ${mb} MB.`,
      );
    }
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
