export const SEQ = ["#0c2a3f", "#0e4a63", "#0e7490", "#0891b2", "#22d3ee", "#a5f3fc"];
export const DIV_CLASSES: Record<string, string> = {
  baixa_cobertura_relativa: "#ef4444",
  sem_conexao: "#a855f7",
  distante: "#f97316",
  atendida_por_vizinhas: "#facc15",
  adequada: "#14b8a6",
  coberto: "#14b8a6",
  dados_insuficientes: "#64748b",
};
export const CLASS_LABELS: Record<string, string> = {
  baixa_cobertura_relativa: "Baixa cobertura relativa",
  sem_conexao: "Sem conexão terrestre na base",
  distante: "Acima do limiar de distância",
  atendida_por_vizinhas: "Atendida por regiões vizinhas",
  adequada: "Adequada",
  coberto: "Dentro do limiar",
  dados_insuficientes: "Dados insuficientes",
};

/** Escala por quantis (classes com o mesmo número de unidades); devolve cor e limites. */
export function quantileScale(values: number[], colors = SEQ) {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  const breaks = colors.slice(1).map((_, i) => v[Math.floor(((i + 1) / colors.length) * (v.length - 1))] ?? 0);
  const color = (x: number | null | undefined) => {
    if (x === null || x === undefined || !Number.isFinite(x)) return "#1e293b";
    let i = 0;
    while (i < breaks.length && x > breaks[i]) i++;
    return colors[i];
  };
  return { color, breaks, colors };
}
