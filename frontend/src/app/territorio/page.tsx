"use client";

import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, FileText, Play } from "lucide-react";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";

import { Chart } from "@/components/chart";
import { Caveat, ErrorBox, Field, KV, Loading } from "@/components/common";
import { MetricInfo } from "@/components/metric-card";
import { MultiCheck } from "@/components/multi-check";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, downloadUrl } from "@/lib/api";
import { CATEGORY_COLORS, CATEGORY_LABELS, UFS } from "@/lib/constants";
import { fmt, fmtCompact, fmtPct } from "@/lib/format";
import { CLASS_LABELS, DIV_CLASSES, quantileScale } from "@/lib/scale";
import type { MetricMeta } from "@/lib/types";

const MapView = dynamic(() => import("@/components/map/map-view").then((m) => m.MapView), { ssr: false });

type Indicators = { level: string; metrics: Record<string, MetricMeta>; items: Record<string, any>[]; concentration: Record<string, any> };
const CHORO_METRICS = ["facilities_per_100k", "facilities_per_10k_km2", "facilities", "storage_t_per_capita", "road_density", "road_paved_share", "rail_km", "waterway_km", "population", "gdp_million_brl"];
const CATS = Object.keys(CATEGORY_LABELS).filter((c) => !["centro_distribuicao", "instalacao_usuario"].includes(c));

export default function TerritoryPage() {
  const [tab, setTab] = useState("indicators");
  const [level, setLevel] = useState<"state" | "municipality" | "immediate_region" | "region">("state");
  const [metric, setMetric] = useState("facilities_per_100k");
  const [cats, setCats] = useState<string[]>([]);
  const [hexMetric, setHexMetric] = useState<"facilities" | "population" | "storage">("facilities");
  const [hexSize, setHexSize] = useState(40);
  const [covCats, setCovCats] = useState<string[]>(["armazem"]);
  const [threshold, setThreshold] = useState(300);
  const [covUfs, setCovUfs] = useState<string[]>([]);
  const [cmpUfs, setCmpUfs] = useState<string[]>(["SP", "MG", "BA", "PA"]);

  const ind = useQuery({
    queryKey: ["indicators", level, cats],
    queryFn: () => api<Indicators>("/territory/indicators", { query: { level, category: cats } }),
  });
  const hex = useQuery({
    queryKey: ["hex", hexMetric, hexSize, cats],
    queryFn: () => api<GeoJSON.FeatureCollection & { unit: string }>("/territory/hex", { query: { size_km: hexSize, metric: hexMetric, category: cats } }),
    enabled: tab === "hex",
  });
  const facPts = useQuery({
    queryKey: ["fac-geo", cats],
    queryFn: () => api<GeoJSON.FeatureCollection>("/facilities/geojson", { query: { category: cats } }),
    enabled: tab === "hex",
  });
  const covBody = { categories: covCats, threshold_km: threshold, ufs: covUfs.length ? covUfs : null };
  const cov = useMutation({
    mutationFn: async () => {
      const [rgi, mun] = await Promise.all([
        api<Record<string, any>>("/territory/coverage", { body: { ...covBody, level: "immediate_region" } }),
        api<Record<string, any>>("/territory/coverage", { body: { ...covBody, level: "municipality" } }),
      ]);
      return { rgi, mun };
    },
  });
  const cand = useMutation({
    mutationFn: () => api<Record<string, any>>("/territory/candidates", { body: { ...covBody, n: 8 } }),
  });
  const cmp = useQuery({
    queryKey: ["compare", cmpUfs, cats],
    queryFn: () => api<{ items: Record<string, any>[]; metrics: Record<string, MetricMeta> }>("/territory/compare", { query: { uf: cmpUfs, category: cats } }),
    enabled: tab === "compare" && cmpUfs.length > 0,
  });

  const meta = ind.data?.metrics[metric];
  const scale = useMemo(() => quantileScale((ind.data?.items ?? []).map((r) => r[metric])), [ind.data, metric]);

  const choropleth = useMemo(() => {
    if (tab === "indicators" && ind.data && (level === "state" || level === "municipality"))
      return { source: (level === "state" ? "states" : "municipalities") as "states" | "municipalities",
        colors: Object.fromEntries(ind.data.items.map((r) => [r.code, scale.color(r[metric])])) };
    if (tab === "coverage" && cov.data)
      return { source: "municipalities" as const, colors: Object.fromEntries(cov.data.mun.items.map((r: any) => [r.code, DIV_CLASSES[r.class]])), opacity: 0.7 };
    return null;
  }, [tab, ind.data, level, metric, scale, cov.data]);

  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    if (tab === "hex" && hex.data) {
      const max = Math.max(...hex.data.features.map((f: any) => f.properties.value), 1);
      const color = quantileScale(hex.data.features.map((f: any) => f.properties.value)).color;
      out.push(new GeoJsonLayer({
        id: "hex", data: hex.data as any, pickable: true, filled: true, stroked: true, opacity: 0.85,
        getFillColor: (f: any) => { const c = color(f.properties.value).slice(1); return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16), 200]; },
        getLineColor: [2, 6, 23, 160], lineWidthMinPixels: 0.4, updateTriggers: { getFillColor: [max] },
      }));
    }
    if (tab === "heat" && facPts.data)
      out.push(new HeatmapLayer({ id: "heat", data: facPts.data.features, getPosition: (f: any) => f.geometry.coordinates, radiusPixels: 45, intensity: 1.1 }));
    if (tab === "candidates" && cand.data) {
      out.push(new ScatterplotLayer({ id: "cand", data: cand.data.items, getPosition: (d: any) => [d.lon, d.lat], getRadius: threshold * 1000,
        radiusUnits: "meters", getFillColor: [34, 211, 238, 30], getLineColor: [34, 211, 238, 200], stroked: true, lineWidthMinPixels: 1.5 }));
      out.push(new ScatterplotLayer({ id: "cand-pt", data: cand.data.items, getPosition: (d: any) => [d.lon, d.lat], getRadius: 7, radiusUnits: "pixels", getFillColor: [250, 204, 21] }));
      out.push(new TextLayer({ id: "cand-lbl", data: cand.data.items.map((d: any, i: number) => ({ ...d, i: i + 1 })), getPosition: (d: any) => [d.lon, d.lat],
        getText: (d: any) => `${d.i}. ${d.name}`, getSize: 13, getColor: [250, 250, 250], getPixelOffset: [0, -16], fontFamily: "system-ui" }));
    }
    return out;
  }, [tab, hex.data, facPts.data, cand.data, threshold]);

  const top = (ind.data?.items ?? []).filter((r) => r[metric] !== null).sort((a, b) => b[metric] - a[metric]).slice(0, 20);

  return (
    <div className="absolute inset-0 grid grid-cols-1 overflow-y-auto md:grid-cols-[340px_minmax(0,1fr)] md:grid-rows-[minmax(0,1fr)] md:overflow-hidden lg:grid-cols-[440px_minmax(0,1fr)]">
      <div className="border-b border-border md:min-h-0 md:overflow-y-auto md:border-b-0 md:border-r">
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))} className="p-3">
          <TabsList className="h-auto w-full flex-wrap">
            <TabsTrigger value="indicators">Indicadores</TabsTrigger>
            <TabsTrigger value="hex">Hexágonos</TabsTrigger>
            <TabsTrigger value="heat">Calor</TabsTrigger>
            <TabsTrigger value="coverage">Cobertura</TabsTrigger>
            <TabsTrigger value="candidates">Candidatas</TabsTrigger>
            <TabsTrigger value="compare">Comparar</TabsTrigger>
          </TabsList>
          <div className="mt-3 flex items-center gap-2">
            <MultiCheck label="Categorias de instalação" value={cats} onChange={setCats}
              options={CATS.map((c) => ({ value: c, label: CATEGORY_LABELS[c], color: CATEGORY_COLORS[c] }))} />
            <span className="text-xs text-muted-foreground">{cats.length ? `${cats.length} selecionadas` : "todas"}</span>
          </div>

          <TabsContent value="indicators" className="mt-3 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Nível territorial">
                <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={level} onChange={(e) => setLevel(e.target.value as any)} data-testid="level">
                  <option value="region">Grandes regiões</option>
                  <option value="state">Estados</option>
                  <option value="immediate_region">Regiões imediatas</option>
                  <option value="municipality">Municípios</option>
                </select>
              </Field>
              <Field label="Indicador">
                <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={metric} onChange={(e) => setMetric(e.target.value)} data-testid="metric">
                  {CHORO_METRICS.map((k) => <option key={k} value={k}>{ind.data?.metrics[k]?.label ?? k}</option>)}
                </select>
              </Field>
            </div>
            {meta && (
              <div className="rounded-lg border border-border p-2.5 text-xs">
                <div className="flex items-center gap-1 font-medium">{meta.label} ({meta.unit}) <MetricInfo m={meta} /></div>
                <div className="mt-1 text-muted-foreground">{meta.definition}</div>
                <div className="mt-1 text-muted-foreground">Período: {meta.period} · Fonte: {meta.source}{meta.denominator ? ` · Denominador: ${meta.denominator}` : ""}</div>
                {meta.limitations && <div className="mt-1 text-amber-200/80">{meta.limitations}</div>}
              </div>
            )}
            {(level === "region" || level === "immediate_region") && <p className="text-xs text-muted-foreground">Mapa coroplético disponível para estados e municípios; regiões aparecem na tabela e no gráfico.</p>}
            <ColorLegend breaks={scale.breaks} colors={scale.colors} unit={meta?.unit ?? ""} />
            {ind.isLoading && <Loading />}
            <ErrorBox error={ind.error} />
            {ind.data && (
              <>
                <Chart height={300} option={{
                  grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
                  tooltip: { trigger: "axis" },
                  xAxis: { type: "value" },
                  yAxis: { type: "category", data: top.map((r) => r.name).reverse(), axisLabel: { fontSize: 10, width: 120, overflow: "truncate" } },
                  series: [{ type: "bar", data: top.map((r) => r[metric]).reverse(), itemStyle: { color: "#22d3ee" } }],
                }} />
                <div className="rounded-lg border border-border p-2 text-xs">
                  <div className="mb-1 font-medium">Concentração das instalações entre unidades</div>
                  <KV k="HHI" v={fmt(ind.data.concentration.hhi, 0)} />
                  <KV k="Participação das 5 maiores" v={fmtPct(ind.data.concentration.top5_share)} />
                  <KV k="Índice de Gini" v={fmt(ind.data.concentration.gini, 3)} />
                  <div className="mt-1 text-muted-foreground">{ind.data.concentration.definition}</div>
                </div>
                <div className="flex gap-2 text-xs">
                  <a className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent" href={downloadUrl("/exports/territory/indicators.xlsx", { level, category: cats })}><Download className="size-3" /> Excel</a>
                  <a className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent" href={downloadUrl("/exports/territory/indicators.csv", { level, category: cats })}><Download className="size-3" /> CSV</a>
                  <a className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent" href={downloadUrl("/reports/territory.pdf", { level: level === "municipality" ? "state" : level, category: cats, coverage_categories: cats.length ? cats : ["armazem"] })}><FileText className="size-3" /> Relatório PDF</a>
                </div>
              </>
            )}
          </TabsContent>

          <TabsContent value="hex" className="mt-3 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Variável">
                <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={hexMetric} onChange={(e) => setHexMetric(e.target.value as any)}>
                  <option value="facilities">Instalações (contagem)</option>
                  <option value="storage">Capacidade estática (t)</option>
                  <option value="population">População 2022</option>
                </select>
              </Field>
              <Field label="Lado do hexágono (km)"><Input type="number" min={5} max={300} value={hexSize} onChange={(e) => setHexSize(Number(e.target.value) || 40)} /></Field>
            </div>
            {hex.isLoading && <Loading label="Agregando no PostGIS (ST_HexagonGrid)…" />}
            {hex.data && <p className="text-xs text-muted-foreground">{hex.data.features.length} hexágonos não vazios · unidade: {hex.data.unit}. Grade em SIRGAS 2000 / Brazil Polyconic (EPSG:5880).</p>}
          </TabsContent>

          <TabsContent value="heat" className="mt-3 space-y-2 text-xs text-muted-foreground">
            <p>Densidade de kernel das instalações filtradas (deck.gl HeatmapLayer, raio de 45 px). Indica concentração espacial de registros, não volume operado.</p>
            <Caveat>Armazenagem é um ponto por município (sede), o que concentra o calor nas sedes municipais.</Caveat>
          </TabsContent>

          <TabsContent value="coverage" className="mt-3 space-y-3">
            <CoverageControls covCats={covCats} setCovCats={setCovCats} threshold={threshold} setThreshold={setThreshold} ufs={covUfs} setUfs={setCovUfs} />
            <Button onClick={() => cov.mutate()} disabled={cov.isPending || !covCats.length} data-testid="run-coverage"><Play /> Calcular cobertura pela rede</Button>
            {cov.isPending && <Loading label="Dijkstra multi-origem na rede…" />}
            <ErrorBox error={cov.error} />
            {cov.data && (
              <>
                <p className="text-xs text-muted-foreground">{cov.data.rgi.method}</p>
                <div className="space-y-1">
                  {Object.entries(cov.data.rgi.summary as Record<string, any>).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2 text-xs">
                      <span className="size-2.5 rounded-sm" style={{ background: DIV_CLASSES[k] }} />
                      <span className="flex-1">{CLASS_LABELS[k] ?? k}</span>
                      <span className="tabular">{v.units} regiões · {fmtPct(v.population_share)} da pop.</span>
                    </div>
                  ))}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {Object.entries(cov.data.rgi.classes as Record<string, string>).map(([k, v]) => <div key={k}>• <b>{CLASS_LABELS[k]}</b>: {v}</div>)}
                </div>
                <table className="w-full text-xs" data-testid="coverage-table">
                  <thead className="text-left text-muted-foreground"><tr><th className="py-1">Região imediata</th><th>QL</th><th>% no limiar</th><th>km médio</th></tr></thead>
                  <tbody>
                    {cov.data.rgi.items.slice(0, 25).map((r: any) => (
                      <tr key={r.code} className="border-t border-border/60">
                        <td className="py-1"><span className="mr-1 inline-block size-2 rounded-sm" style={{ background: DIV_CLASSES[r.class] }} />{r.name}</td>
                        <td className="tabular">{fmt(r.location_quotient, 2)}</td>
                        <td className="tabular">{fmtPct(r.share_within_threshold, 0)}</td>
                        <td className="tabular">{fmt(r.avg_network_km, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[11px] text-muted-foreground">Mapa: municípios coloridos pela distância na rede até a instalação mais próxima.</p>
              </>
            )}
          </TabsContent>

          <TabsContent value="candidates" className="mt-3 space-y-3">
            <CoverageControls covCats={covCats} setCovCats={setCovCats} threshold={threshold} setThreshold={setThreshold} ufs={covUfs} setUfs={setCovUfs} />
            <Button onClick={() => cand.mutate()} disabled={cand.isPending || !covCats.length} data-testid="run-candidates"><Play /> Identificar áreas candidatas</Button>
            {cand.isPending && <Loading label="Heurística gulosa sobre distâncias na rede…" />}
            <ErrorBox error={cand.error} />
            {cand.data && (
              <>
                <p className="text-xs text-muted-foreground">{cand.data.method} Cobertura atual: <b>{fmtPct(cand.data.base_coverage)}</b> da população dentro de {cand.data.threshold_km} km.</p>
                <ol className="space-y-1 text-sm">
                  {cand.data.items.map((r: any, i: number) => (
                    <li key={r.code} className="flex items-baseline gap-2 border-b border-border/60 pb-1">
                      <span className="text-muted-foreground tabular">{i + 1}.</span>
                      <span className="flex-1">{r.name}/{r.uf}</span>
                      <span className="text-xs tabular">+{fmtCompact(r.marginal_population)} hab.</span>
                      <span className="w-14 text-right text-xs text-primary tabular">{fmtPct(r.cumulative_coverage)}</span>
                    </li>
                  ))}
                </ol>
                <ul className="text-[11px] text-muted-foreground">{cand.data.assumptions.map((a: string) => <li key={a}>• {a}</li>)}</ul>
              </>
            )}
          </TabsContent>

          <TabsContent value="compare" className="mt-3 space-y-3">
            <MultiCheck label="UFs para comparar" value={cmpUfs} onChange={setCmpUfs} options={UFS.map((u) => ({ value: u, label: u }))} />
            {cmp.isLoading && <Loading />}
            {cmp.data && (
              <>
                <Chart height={240} option={{
                  legend: { top: 0 }, tooltip: { trigger: "axis" }, grid: { top: 30, left: 8, right: 8, bottom: 8, containLabel: true },
                  xAxis: { type: "category", data: cmp.data.items.map((r) => r.uf) },
                  yAxis: { type: "value" },
                  series: [
                    { name: "Instalações/100 mil hab.", type: "bar", data: cmp.data.items.map((r) => r.facilities_per_100k) },
                    { name: "Densidade rodoviária (km/1.000 km²)", type: "bar", data: cmp.data.items.map((r) => r.road_density) },
                  ],
                }} />
                <table className="w-full text-xs">
                  <thead className="text-left text-muted-foreground"><tr><th className="py-1">Indicador</th>{cmp.data.items.map((r) => <th key={r.uf} className="text-right">{r.uf}</th>)}</tr></thead>
                  <tbody>
                    {["population", "facilities", "facilities_per_100k", "facilities_per_10k_km2", "storage_t_per_capita", "road_km", "road_paved_share", "road_density", "rail_km", "waterway_km"].map((k) => (
                      <tr key={k} className="border-t border-border/60">
                        <td className="py-1">{cmp.data!.metrics[k]?.label ?? k} <span className="text-muted-foreground">({cmp.data!.metrics[k]?.unit})</span></td>
                        {cmp.data!.items.map((r) => <td key={r.uf} className="text-right tabular">{fmt(r[k], k.includes("per") || k.includes("density") ? 2 : 0)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </TabsContent>
        </Tabs>
      </div>
      <div className="relative order-first h-[50vh] min-h-[320px] md:order-none md:h-auto md:min-h-0">
        <MapView vectors={{ roads: tab === "coverage" || tab === "candidates", rail: false, waterways: false, states: true }}
          choropleth={choropleth} deckLayers={deckLayers}
          getTooltip={(info: any) => info.layer?.id === "hex" ? `${fmt(info.object.properties.value, 0)} ${hex.data?.unit}` : info.layer?.id?.startsWith("cand") ? `${info.object.name}: +${fmtCompact(info.object.marginal_population)} hab. cobertos` : null} />
      </div>
    </div>
  );
}

function CoverageControls({ covCats, setCovCats, threshold, setThreshold, ufs, setUfs }: {
  covCats: string[]; setCovCats: (v: string[]) => void; threshold: number; setThreshold: (v: number) => void; ufs: string[]; setUfs: (v: string[]) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <MultiCheck label="Instalações de atendimento" value={covCats} onChange={setCovCats}
          options={CATS.map((c) => ({ value: c, label: CATEGORY_LABELS[c], color: CATEGORY_COLORS[c] }))} />
        <MultiCheck label="Recorte (UF)" value={ufs} onChange={setUfs} options={UFS.map((u) => ({ value: u, label: u }))} />
      </div>
      <Field label="Limiar de cobertura (km na rede rodoviária)">
        <Input type="number" min={10} max={2000} value={threshold} onChange={(e) => setThreshold(Number(e.target.value) || 300)} />
      </Field>
    </div>
  );
}

function ColorLegend({ breaks, colors, unit }: { breaks: number[]; colors: string[]; unit: string }) {
  if (!breaks.length) return null;
  return (
    <div className="text-[11px] text-muted-foreground">
      <div className="flex h-2 overflow-hidden rounded">{colors.map((c) => <span key={c} className="flex-1" style={{ background: c }} />)}</div>
      <div className="mt-0.5 flex justify-between tabular">
        <span>mín.</span>
        {breaks.map((b, i) => <span key={i}>{fmt(b, b < 10 ? 2 : 0)}</span>)}
        <span>máx.</span>
      </div>
      <div>Classes por quantis · {unit}</div>
    </div>
  );
}
