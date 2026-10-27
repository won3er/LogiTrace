export const CATEGORY_COLORS: Record<string, string> = {
  porto: "#38bdf8",
  terminal_portuario: "#0ea5e9",
  porto_seco: "#34d399",
  terminal_ferroviario: "#a78bfa",
  armazem: "#f59e0b",
  aeroporto: "#f472b6",
  aerodromo: "#fb7185",
  ponto_fronteira: "#e879f9",
  centro_distribuicao: "#22d3ee",
  instalacao_usuario: "#facc15",
};

export const CATEGORY_LABELS: Record<string, string> = {
  porto: "Portos públicos",
  terminal_portuario: "Terminais portuários",
  porto_seco: "Portos secos",
  terminal_ferroviario: "Terminais ferroviários",
  armazem: "Armazenagem (agregada)",
  aeroporto: "Aeroportos",
  aerodromo: "Aeródromos",
  ponto_fronteira: "Pontos de fronteira",
  centro_distribuicao: "Centros de distribuição",
  instalacao_usuario: "Instalações do usuário",
};

export const MODAL_COLORS: Record<string, string> = {
  road: "#f59e0b",
  rail: "#a78bfa",
  waterway: "#38bdf8",
  access: "#94a3b8",
  transfer: "#34d399",
  rodoviario: "#f59e0b",
  ferroviario: "#a78bfa",
  aquaviario: "#38bdf8",
  aereo: "#f472b6",
  intermodal: "#34d399",
};

export const MODAL_LABELS: Record<string, string> = {
  road: "Rodoviário",
  rail: "Ferroviário",
  waterway: "Hidroviário",
  access: "Conector de acesso",
  transfer: "Transbordo",
  rodoviario: "Rodoviário",
  ferroviario: "Ferroviário",
  aquaviario: "Aquaviário",
  aereo: "Aéreo",
  intermodal: "Intermodal",
};

export const UFS = [
  "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
  "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
];

export const BRAZIL_VIEW = { longitude: -52.5, latitude: -14.5, zoom: 3.55 };

export const BASEMAP_STYLE = process.env.NEXT_PUBLIC_BASEMAP_STYLE ?? "https://tiles.openfreemap.org/styles/dark";

export const QUALITY_STYLES: Record<string, string> = {
  OPTIMAL: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  FEASIBLE: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  HEURISTIC: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  INFEASIBLE: "bg-red-500/15 text-red-300 border-red-500/40",
  NOT_SOLVED: "bg-red-500/15 text-red-300 border-red-500/40",
  ERROR: "bg-red-500/15 text-red-300 border-red-500/40",
};

export const QUALITY_LABELS: Record<string, string> = {
  OPTIMAL: "Ótimo comprovado",
  FEASIBLE: "Viável (sem prova de otimalidade)",
  HEURISTIC: "Heurística",
  INFEASIBLE: "Inviável",
  NOT_SOLVED: "Sem solução",
  ERROR: "Erro",
};

export const FLOW_CLASS_COLORS: Record<string, [number, number, number]> = {
  observed: [56, 189, 248],
  modeled: [167, 139, 250],
  hypothetical: [250, 204, 21],
  synthetic: [148, 163, 184],
};

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
