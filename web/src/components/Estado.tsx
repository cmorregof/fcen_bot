const CLASE: Record<string, string> = {
  vencida: "vencida",
  "próxima a vencer": "proxima",
  cumplida: "cumplida",
  pendiente: "pendiente",
};

export function Estado({ valor }: { valor: string }) {
  return <span className={`estado ${CLASE[valor] ?? "pendiente"}`}>{valor}</span>;
}
