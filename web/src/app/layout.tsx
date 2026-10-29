import type { Metadata } from "next";
import { Cabecera } from "@/components/Cabecera";
import { ProveedorSesion } from "@/lib/sesion";
import "./globals.css";

export const metadata: Metadata = {
  title: "MemorIA · FCEN",
  description: "Herramientas de apoyo para la Facultad de Ciencias Exactas y Naturales",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <ProveedorSesion>
          <Cabecera />
          <main>{children}</main>
        </ProveedorSesion>
      </body>
    </html>
  );
}
