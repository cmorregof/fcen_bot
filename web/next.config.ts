import type { NextConfig } from "next";

// La web solo sirve páginas: no hay rutas de servidor que toquen datos.
//
// El navegador llama a /srv/<servicio>/api/web/... en el mismo dominio de la
// web y Vercel reenvía la petición al backend de Railway (rewrite externo).
// Así la web funciona en redes que bloquean las IP de Railway. Los datos
// pasan por Vercel, pero Vercel no los guarda: no hay funciones ni caché en
// estas rutas (ver web/README.md, «Proxy de Vercel»).
//
// Los destinos salen de las mismas variables que usa el navegador
// (NEXT_PUBLIC_API_*, o *_PRACTICA en el despliegue de práctica). Se leen al
// construir: si cambia una URL, hay que volver a desplegar la web.

const PRACTICA = process.env.NEXT_PUBLIC_PRACTICA === "true";
const sufijo = PRACTICA ? "_PRACTICA" : "";

const SERVICIOS = ["actas", "calidad", "admision", "oportunidades"] as const;

function destino(servicio: (typeof SERVICIOS)[number]): string {
  const url = process.env[`NEXT_PUBLIC_API_${servicio.toUpperCase()}${sufijo}`] ?? "";
  return url.replace(/\/+$/, "");
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    // Solo las rutas de la web (/api/web/...): el resto del backend (por
    // ejemplo el webhook de Telegram) no se expone por este dominio.
    return SERVICIOS.filter((s) => destino(s) !== "").map((s) => ({
      source: `/srv/${s}/api/web/:ruta*`,
      destination: `${destino(s)}/api/web/:ruta*`,
    }));
  },
  async headers() {
    return [
      {
        source: "/srv/:ruta*",
        headers: [
          // Vercel no guarda en su CDN ninguna respuesta de los backends.
          { key: "x-vercel-enable-rewrite-caching", value: "0" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
    ];
  },
};

export default nextConfig;
