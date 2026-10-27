"use client";

import { create } from "zustand";

export type Selection =
  | { kind: "facility"; id: number }
  | { kind: "segment"; id: number }
  | { kind: "municipality"; code: number }
  | null;

export type LayerKey =
  | "roads"
  | "rail"
  | "waterways"
  | "corridors"
  | "states"
  | "municipalities"
  | "facilities"
  | "poles"
  | "heatmap"
  | "hexagons"
  | "flows"
  | "network";

export const LAYER_INFO: Record<LayerKey, { label: string; group: string; source: string }> = {
  roads: { label: "Malha rodoviária", group: "Infraestrutura", source: "IBGE/SNV 2014" },
  rail: { label: "Ferrovias", group: "Infraestrutura", source: "IBGE 2014" },
  waterways: { label: "Hidrovias", group: "Infraestrutura", source: "IBGE 2014" },
  corridors: { label: "Corredores (eixos estruturantes)", group: "Infraestrutura", source: "IBGE 2014" },
  facilities: { label: "Instalações logísticas", group: "Instalações", source: "IBGE 2014/2024" },
  states: { label: "Estados", group: "Território", source: "IBGE Malhas" },
  municipalities: { label: "Municípios (população)", group: "Território", source: "IBGE Censo 2022" },
  poles: { label: "Polos econômicos (PIB)", group: "Território", source: "IBGE PIB municipal" },
  heatmap: { label: "Concentração de instalações (calor)", group: "Análise", source: "Cálculo LogiTrace" },
  hexagons: { label: "Hexágonos de instalações", group: "Análise", source: "PostGIS ST_HexagonGrid" },
  flows: { label: "Fluxos rodoviários observados (CIOT)", group: "Análise", source: "IBGE 2024" },
  network: { label: "Grafo logístico (arestas)", group: "Análise", source: "Rede LogiTrace" },
};

type MapState = {
  layers: Record<LayerKey, boolean>;
  categories: string[];
  selection: Selection;
  flyTo: { lon: number; lat: number; zoom?: number; t: number } | null;
  toggleLayer: (k: LayerKey) => void;
  setLayer: (k: LayerKey, v: boolean) => void;
  setCategories: (c: string[]) => void;
  select: (s: Selection) => void;
  fly: (lon: number, lat: number, zoom?: number) => void;
};

export const useMapStore = create<MapState>((set) => ({
  layers: {
    roads: true,
    rail: true,
    waterways: true,
    corridors: false,
    states: true,
    municipalities: false,
    facilities: true,
    poles: false,
    heatmap: false,
    hexagons: false,
    flows: false,
    network: false,
  },
  categories: [],
  selection: null,
  flyTo: null,
  toggleLayer: (k) => set((s) => ({ layers: { ...s.layers, [k]: !s.layers[k] } })),
  setLayer: (k, v) => set((s) => ({ layers: { ...s.layers, [k]: v } })),
  setCategories: (categories) => set({ categories }),
  select: (selection) => set({ selection }),
  fly: (lon, lat, zoom) => set({ flyTo: { lon, lat, zoom, t: Date.now() } }),
}));
