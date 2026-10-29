const CLASE: Record<string, string> = {
  "no funcionó": "nofunciono",
  vencida: "vencida",
  "en curso": "proxima",
  "por iniciar": "pendiente",
  cumplida: "cumplida",
};

export function Estado({ valor }: { valor: string }) {
  return <span className={`estado ${CLASE[valor] ?? "pendiente"}`}>{valor === "no funcionó" ? "NO FUNCIONÓ" : valor}</span>;
}
