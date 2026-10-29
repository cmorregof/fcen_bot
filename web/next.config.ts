import type { NextConfig } from "next";

// La web solo sirve páginas: no hay rutas de servidor que toquen datos.
// El navegador llama directo a los backends de Railway.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
