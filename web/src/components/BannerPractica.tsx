"use client";

import { usePractica } from "@/lib/entorno";

export function BannerPractica() {
  if (!usePractica()) return null;
  return (
    <div className="banner-practica" role="status">
      ENTORNO DE PRÁCTICA · datos ficticios
    </div>
  );
}
