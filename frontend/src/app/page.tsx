"use client";

import { ArcLayer, GeoJsonLayer, PolygonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import type { Layer } from "@deck.gl/core";
import { useQuery } from "@tanstack/react-query";
import { ChevronUp, Layers as LayersIcon, PenLine, Square, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { Caveat, ErrorBox, KV, Loading, MAP_ASIDE, Panel } from "@/components/common";
import { EntityDetails } from "@/components/entity-details";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { CATEGORY_COLORS, CATEGORY_LABELS } from "@/lib/constants";
import { fmt, fmtCompact } from "@/lib/format";
import { LAYER_INFO, useMapStore, type LayerKey } from "@/lib/store";

const MapView = dynamic(() => import("@/components/map/map-view").then((m) => m.MapView), { ssr: false });

type Facet = { value: string; count: number; label: string };
type Area = {
  area_km2: number; municipalities: number; population: number; gdp_million_brl: number;
  facilities: { category: string; n: number; cap: number | null }[];
  infrastructure_km: { modal: string; km: number }[];
  observed_flows_touching: { dataset: string; unit: string; links: number; total: number }[];
  notes: string[];
};

export default function MapPage() {
  const { layers, toggleLayer, categories, setCategories, selection, select, flyTo } = useMapStore();
  const [drawing, setDrawing] = useState<[number, number][] | null>(null);
  const [area, setArea] = useState<[number, number][] | null>(null);
  const [reachCodes, setReachCodes] = useState<number[] | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  // em telas pequenas o painel de camadas começa recolhido para não cobrir o mapa
  useEffect(() => {
    if (window.matchMedia("(max-width: 639px)").matches) setPanelOpen(false);
  }, []);

  const facets = useQuery({ queryKey: ["facets"], queryFn: () => api<{ category: Facet[] }>("/facilities/facets") });
  const facGeo = useQuery({
    queryKey: ["fac-geo", categories],
    queryFn: () => api<GeoJSON.FeatureCollection>("/facilities/geojson", { query: { category: categories } }),
  });
  const poles = useQuery({
    queryKey: ["poles"],
    queryFn: () => api<{ items: { code: number; name: string; uf: string; gdp_thousand_brl: number; lon: number; lat: number; share: number }[]; definition: string }>("/territory/poles", { query: { top: 150 } }),
    enabled: layers.poles,
  });
  const hex = useQuery({
    queryKey: ["hex", categories],
    queryFn: () => api<GeoJSON.FeatureCollection & { unit: string }>("/territory/hex", { query: { size_km: 40, category: categories } }),
    enabled: layers.hexagons,
  });
  const flows = useQuery({
    queryKey: ["flows-map"],
    queryFn: () => api<{ items: any[]; unit: string; caveat: string; shown_share: number; total_links: number }>("/flows", { query: { dataset: "ibge_2024_rodoviario_ciot", limit: 1500 } }),
    enabled: layers.flows,
  });
  const areaQ = useQuery({
    queryKey: ["area", area],
    queryFn: () => api<Area>("/territory/area", { body: { geometry: { type: "Polygon", coordinates: [[...area!, area![0]]] } } }),
    enabled: !!area && area.length >= 3,
  });

  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    if (layers.heatmap && facGeo.data)
      out.push(new HeatmapLayer({
        id: "heat", data: facGeo.data.features, getPosition: (f: any) => f.geometry.coordinates, getWeight: 1,
        radiusPixels: 40, intensity: 1.2, threshold: 0.04,
        colorRange: [[12, 74, 110], [14, 116, 144], [34, 211, 238], [250, 204, 21], [245, 158, 11], [239, 68, 68]],
      }));
    if (layers.hexagons && hex.data) {
      const max = Math.max(...hex.data.features.map((f: any) => f.properties.value), 1);
      out.push(new GeoJsonLayer({
        id: "hex", data: hex.data as any, pickable: true, stroked: true, filled: true,
        getFillColor: (f: any) => { const t = Math.sqrt(f.properties.value / max); return [34 + t * 200, 211 - t * 120, 238 - t * 200, 60 + t * 150]; },
        getLineColor: [15, 23, 42, 160], lineWidthMinPixels: 0.5,
      }));
    }
    if (layers.poles && poles.data) {
      const max = poles.data.items[0]?.gdp_thousand_brl ?? 1;
      out.push(new ScatterplotLayer({
        id: "poles", data: poles.data.items, pickable: true, getPosition: (d: any) => [d.lon, d.lat],
        getRadius: (d: any) => 5000 + Math.sqrt(d.gdp_thousand_brl / max) * 70000, radiusUnits: "meters",
        getFillColor: [250, 204, 21, 70], getLineColor: [250, 204, 21, 220], stroked: true, lineWidthMinPixels: 1,
      }));
    }
    if (layers.flows && flows.data) {
      const max = flows.data.items[0]?.value ?? 1;
      out.push(new ArcLayer({
        id: "flows", data: flows.data.items, pickable: true,
        getSourcePosition: (d: any) => [d.olon, d.olat], getTargetPosition: (d: any) => [d.dlon, d.dlat],
        getWidth: (d: any) => 0.5 + 6 * Math.sqrt(d.value / max), getSourceColor: [56, 189, 248, 170], getTargetColor: [250, 204, 21, 170],
        greatCircle: false,
      }));
    }
    const poly = drawing ?? area;
    if (poly && poly.length) {
      out.push(new PolygonLayer({
        id: "area", data: [{ p: poly }], getPolygon: (d: any) => d.p, filled: true, stroked: true,
        getFillColor: [34, 211, 238, 35], getLineColor: [34, 211, 238, 230], lineWidthMinPixels: 2,
      }));
      out.push(new ScatterplotLayer({ id: "area-v", data: poly, getPosition: (d: any) => d, getRadius: 5, radiusUnits: "pixels", getFillColor: [34, 211, 238] }));
    }
    return out;
  }, [layers, facGeo.data, hex.data, poles.data, flows.data, drawing, area]);

  const reachChoro = useMemo(
    () => (reachCodes ? { source: "municipalities" as const, colors: Object.fromEntries(reachCodes.map((c) => [c, "#22d3ee"])), opacity: 0.35 } : null),
    [reachCodes],
  );

  const getTooltip = (info: any) => {
    const o = info.object;
    if (!o) return null;
    if (info.layer?.id === "poles") return `${o.name}/${o.uf} — PIB R$ ${fmtCompact(o.gdp_thousand_brl * 1000)} (${fmt(o.share * 100, 2)}% do país)`;
    if (info.layer?.id === "flows") return `${o.origin_name} ↔ ${o.dest_name}: ${fmt(o.value, 0)} ${flows.data?.unit} (observado, ligação esquemática)`;
    if (info.layer?.id === "hex") return `${fmt(o.properties.value, 0)} ${hex.data?.unit} neste hexágono`;
    return null;
  };

  const groups = Object.entries(LAYER_INFO).reduce<Record<string, LayerKey[]>>((acc, [k, v]) => {
    (acc[v.group] ??= []).push(k as LayerKey);
    return acc;
  }, {});

  return (
    <div className="absolute inset-0">
      <MapView
        vectors={{
          roads: layers.roads, rail: layers.rail, waterways: layers.waterways, corridors: layers.corridors,
          states: layers.states, municipalities: layers.municipalities, network: layers.network,
        }}
        facilities={{ visible: layers.facilities, data: facGeo.data }}
        choropleth={reachChoro}
        deckLayers={deckLayers}
        onSelect={(s) => select(s)}
        onMapClick={drawing ? (ll) => setDrawing([...drawing, ll]) : undefined}
        getTooltip={getTooltip}
        flyTo={flyTo}
        cursor={drawing ? "crosshair" : undefined}
      >
        {/* Coluna esquerda: painel de camadas (recolhível) e legenda empilhados, nunca sobrepostos */}
        <div className="pointer-events-none absolute top-3 bottom-8 left-3 z-10 flex w-72 max-w-[calc(100%-1.5rem)] flex-col gap-2">
          {panelOpen ? (
            <Panel
              title="Camadas"
              className="pointer-events-auto flex min-h-0 shrink flex-col"
              bodyClassName="min-h-0 space-y-3 overflow-y-auto"
              actions={
                <Button size="icon-xs" variant="ghost" onClick={() => setPanelOpen(false)} aria-label="Recolher camadas" data-testid="collapse-layers">
                  <ChevronUp />
                </Button>
              }
            >
          {Object.entries(groups).map(([g, keys]) => (
            <div key={g}>
              <div className="mb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{g}</div>
              {keys.map((k) => (
                <label key={k} className="flex items-center gap-2 py-1 text-sm">
                  <Switch checked={layers[k]} onCheckedChange={() => toggleLayer(k)} data-testid={`layer-${k}`} />
                  <span className="flex-1">{LAYER_INFO[k].label}</span>
                  <span className="text-[10px] text-muted-foreground">{LAYER_INFO[k].source}</span>
                </label>
              ))}
              {g === "Instalações" && layers.facilities && (
                <div className="mt-1 space-y-0.5 rounded-lg border border-border p-2">
                  {(facets.data?.category ?? []).map((c) => (
                    <label key={c.value} className="flex cursor-pointer items-center gap-2 text-xs">
                      <Checkbox
                        checked={categories.length === 0 || categories.includes(c.value)}
                        onCheckedChange={() => {
                          const all = facets.data!.category.map((x) => x.value);
                          const cur = categories.length ? categories : all;
                          const next = cur.includes(c.value) ? cur.filter((x) => x !== c.value) : [...cur, c.value];
                          setCategories(next.length === all.length ? [] : next);
                        }}
                      />
                      <span className="size-2.5 rounded-full" style={{ background: CATEGORY_COLORS[c.value] }} />
                      <span className="flex-1 truncate">{CATEGORY_LABELS[c.value] ?? c.label}</span>
                      <span className="text-muted-foreground tabular">{c.count}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
          {layers.flows && flows.data && (
            <Caveat>
              {flows.data.items.length} maiores ligações rodoviárias ({fmt((flows.data.shown_share ?? 0) * 100, 1)}% das operações CIOT). {flows.data.caveat}
            </Caveat>
          )}
          {layers.poles && poles.data && <p className="text-[11px] text-muted-foreground">{poles.data.definition}</p>}
            </Panel>
          ) : (
            <Button size="sm" variant="secondary" className="pointer-events-auto self-start shadow-lg" onClick={() => setPanelOpen(true)} data-testid="expand-layers">
              <LayersIcon /> Camadas
            </Button>
          )}
          <Legend layers={layers} />
        </div>

        <div className="absolute right-3 bottom-10 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap justify-end gap-2 sm:top-3 sm:right-auto sm:bottom-auto sm:left-1/2 sm:-translate-x-1/2">
          {!drawing ? (
            <Button size="sm" variant="secondary" onClick={() => { setArea(null); setDrawing([]); select(null); }} data-testid="draw-area">
              <PenLine /> Analisar área
            </Button>
          ) : (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-2 py-1 text-xs shadow-lg">
              Clique para adicionar vértices ({drawing.length})
              <Button size="xs" disabled={drawing.length < 3} onClick={() => { setArea(drawing); setDrawing(null); }} data-testid="finish-area">
                <Square /> Concluir
              </Button>
              <Button size="xs" variant="ghost" onClick={() => setDrawing(null)}>
                Cancelar
              </Button>
            </div>
          )}
          {reachCodes && (
            <Button size="sm" variant="outline" onClick={() => setReachCodes(null)}>
              <X /> Limpar alcance ({reachCodes.length})
            </Button>
          )}
        </div>

        {(selection || area) && (
          <aside className={MAP_ASIDE}>
            {selection ? (
              <EntityDetails selection={selection} onClose={() => select(null)} onReach={(r) => setReachCodes(r?.codes ?? null)} />
            ) : (
              <AreaResult q={areaQ} onClose={() => setArea(null)} />
            )}
          </aside>
        )}
      </MapView>
    </div>
  );
}

function AreaResult({ q, onClose }: { q: { data?: Area; isLoading: boolean; error: unknown }; onClose: () => void }) {
  return (
    <div className="flex h-full flex-col" data-testid="area-result">
      <div className="flex items-center border-b border-border px-3 py-2">
        <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Análise da área selecionada</span>
        <button className="ml-auto text-muted-foreground hover:text-foreground" onClick={onClose} aria-label="Fechar">
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3 text-sm">
        {q.isLoading && <Loading label="Consultando PostGIS…" />}
        <ErrorBox error={q.error} />
        {q.data && (
          <>
            <div className="rounded-lg border border-border p-2">
              <KV k="Área" v={`${fmt(q.data.area_km2, 0)} km²`} />
              <KV k="Municípios (ponto representativo)" v={q.data.municipalities} />
              <KV k="População (2022)" v={fmt(q.data.population, 0)} />
              <KV k="PIB" v={`R$ ${fmt(q.data.gdp_million_brl / 1000, 1)} bi`} />
            </div>
            <div className="rounded-lg border border-border p-2">
              <div className="mb-1 text-xs font-medium text-muted-foreground">Infraestrutura linear</div>
              {q.data.infrastructure_km.map((r) => (
                <KV key={r.modal} k={r.modal} v={`${fmt(r.km, 1)} km`} />
              ))}
            </div>
            <div className="rounded-lg border border-border p-2">
              <div className="mb-1 text-xs font-medium text-muted-foreground">Instalações</div>
              {q.data.facilities.length === 0 && <div className="text-xs text-muted-foreground">Nenhuma instalação nas fontes importadas</div>}
              {q.data.facilities.map((r) => (
                <KV key={r.category} k={CATEGORY_LABELS[r.category] ?? r.category} v={r.n} />
              ))}
            </div>
            <div className="rounded-lg border border-border p-2">
              <div className="mb-1 text-xs font-medium text-muted-foreground">Fluxos observados com ponta na área</div>
              {q.data.observed_flows_touching.map((r) => (
                <KV key={r.dataset} k={r.dataset.replace("ibge_2024_", "")} v={`${fmtCompact(r.total)} ${r.unit}`} />
              ))}
            </div>
            <ul className="space-y-0.5 text-[11px] text-muted-foreground">
              {q.data.notes.map((n) => <li key={n}>• {n}</li>)}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

function Legend({ layers }: { layers: Record<LayerKey, boolean> }) {
  const rows: [string, string, string][] = [];
  if (layers.roads) rows.push(["line", "#fbbf24", "Rodovia duplicada / pavimentada"], ["line", "#a16207", "Rodovia não pavimentada"]);
  if (layers.rail) rows.push(["dash", "#c4b5fd", "Ferrovia"]);
  if (layers.waterways) rows.push(["line", "#38bdf8", "Via navegável"]);
  if (layers.corridors) rows.push(["line", "#f43f5e", "Eixo rodoviário estruturante"]);
  if (layers.flows) rows.push(["line", "#38bdf8", "Fluxo observado (origem→destino esquemático)"]);
  if (layers.poles) rows.push(["dot", "#facc15", "Polo econômico (raio ∝ √PIB)"]);
  if (!rows.length) return null;
  return (
    <div className="pointer-events-auto mt-auto shrink-0 self-start rounded-lg border border-border bg-card/90 px-3 py-2 text-[11px] shadow-lg backdrop-blur sm:text-xs" data-testid="legend">
      {rows.map(([kind, color, label]) => (
        <div key={label} className="flex items-center gap-2 py-0.5">
          {kind === "dot" ? (
            <span className="size-2.5 rounded-full border" style={{ borderColor: color, background: `${color}55` }} />
          ) : (
            <span className="h-0.5 w-5" style={{ background: kind === "dash" ? `repeating-linear-gradient(90deg, ${color} 0 5px, transparent 5px 8px)` : color }} />
          )}
          {label}
        </div>
      ))}
    </div>
  );
}

