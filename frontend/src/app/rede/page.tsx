"use client";

import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, Crosshair, Play } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { Caveat, ErrorBox, Field, JobProgress, KV, Loading, Stat } from "@/components/common";
import { MunicipalityPicker } from "@/components/municipality-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useJob } from "@/hooks/use-job";
import { api } from "@/lib/api";
import { MODAL_COLORS, MODAL_LABELS } from "@/lib/constants";
import { fmt, fmtBRL, fmtCompact, fmtSigned, hours } from "@/lib/format";
import { RouteResponseSchema, type Endpoint, type MunicipalityHit } from "@/lib/types";

const MapView = dynamic(() => import("@/components/map/map-view").then((m) => m.MapView), { ssr: false });
const ROUTE_COLORS: [number, number, number][] = [[34, 211, 238], [250, 204, 21], [244, 114, 182], [167, 139, 250], [52, 211, 153]];

export default function NetworkPage() {
  // parâmetro lido após a montagem: a página continua estática e não depende de fronteira de Suspense
  const [originFacility, setOriginFacility] = useState<string | null>(null);
  useEffect(() => setOriginFacility(new URLSearchParams(window.location.search).get("origin_facility")), []);
  const [tab, setTab] = useState("route");
  const [origin, setOrigin] = useState<MunicipalityHit | null>(null);
  const [dest, setDest] = useState<MunicipalityHit | null>(null);
  const [pointO, setPointO] = useState<[number, number] | null>(null);
  const [pointD, setPointD] = useState<[number, number] | null>(null);
  const [picking, setPicking] = useState<"o" | "d" | null>(null);
  const [metric, setMetric] = useState<"cost" | "time" | "distance">("time");
  const [mode, setMode] = useState<"road" | "multimodal">("road");
  const [active, setActive] = useState(0);
  const [critJob, setCritJob] = useState<number | null>(null);

  const stats = useQuery({ queryKey: ["net-stats"], queryFn: () => api<Record<string, any>>("/network/stats") });
  const ep = (m: MunicipalityHit | null, p: [number, number] | null, fac?: string | null): Endpoint | null =>
    fac ? { type: "facility", id: Number(fac) } : m ? { type: "municipality", id: m.code } : p ? { type: "point", lon: p[0], lat: p[1] } : null;
  const o = ep(origin, pointO, origin || pointO ? null : originFacility);
  const d = ep(dest, pointD);
  const route = useMutation({
    mutationFn: () => api("/network/route", { body: { origin: o, dest: d, metric, mode, alternatives: 3 }, schema: RouteResponseSchema }),
    onSuccess: () => setActive(0),
  });
  const conn = useQuery({ queryKey: ["connectivity", mode], queryFn: () => api<Record<string, any>>("/network/connectivity", { query: { mode } }), enabled: tab === "connectivity" });
  const bridges = useQuery({ queryKey: ["bridges"], queryFn: () => api<{ items: any[]; method: string }>("/network/bridges", { query: { top: 40 } }), enabled: tab === "bridges" });
  const startCrit = useMutation({
    mutationFn: () => api<{ job_id: number }>("/network/criticality", { body: { metric: "cost", mode: "road", top_k: 12 } }),
    onSuccess: (r) => setCritJob(r.job_id),
  });
  const job = useJob(critJob);
  const crit = useQuery({
    queryKey: ["crit", critJob, job.data?.status],
    queryFn: () => api<Record<string, any>>(`/network/criticality/${critJob}`),
    enabled: job.data?.status === "success",
  });

  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    if (tab === "route" && route.data?.connected) {
      route.data.routes.forEach((r, i) => {
        if (i === active) return;
        out.push(new GeoJsonLayer({ id: `alt-${i}`, data: r.geojson as any, getLineColor: [...ROUTE_COLORS[i], 120] as any, lineWidthMinPixels: 3 }));
      });
      const r = route.data.routes[active];
      out.push(new GeoJsonLayer({ id: "best", data: r.geojson as any, getLineColor: [...ROUTE_COLORS[active], 255] as any, lineWidthMinPixels: 5 }));
    }
    const pts = [o?.type === "point" ? pointO : null, d?.type === "point" ? pointD : null, origin && [origin.lon, origin.lat], dest && [dest.lon, dest.lat]].filter(Boolean);
    if (tab === "route" && pts.length)
      out.push(new ScatterplotLayer({ id: "od", data: pts, getPosition: (p: any) => p, getRadius: 7, radiusUnits: "pixels", getFillColor: [255, 255, 255], getLineColor: [15, 23, 42], stroked: true, lineWidthMinPixels: 2 }));
    if (tab === "bridges" && bridges.data) {
      const max = Math.max(...bridges.data.items.map((b) => b.isolated_population), 1);
      out.push(new ScatterplotLayer({ id: "bridges", data: bridges.data.items, pickable: true, getPosition: (b: any) => [b.lon, b.lat],
        getRadius: (b: any) => 6 + 24 * Math.sqrt(b.isolated_population / max), radiusUnits: "pixels", getFillColor: [239, 68, 68, 120], getLineColor: [239, 68, 68], stroked: true }));
    }
    if (tab === "critical" && crit.data?.edges) {
      const max = Math.max(...crit.data.edges.map((e: any) => e.weighted_delta), 1e-9);
      out.push(new PathLayer({ id: "crit", data: crit.data.edges, pickable: true, getPath: (e: any) => e.geometry.coordinates,
        getColor: (e: any) => [239, 68 + 150 * (1 - e.weighted_delta / max), 68, 255], getWidth: (e: any) => 3 + 8 * (e.weighted_delta / max), widthUnits: "pixels" }));
    }
    return out;
  }, [tab, route.data, active, bridges.data, crit.data, o, d, pointO, pointD, origin, dest]);

  const isolatedChoro = useMemo(() => {
    if (tab !== "connectivity" || !conn.data) return null;
    const colors: Record<number, string> = {};
    conn.data.isolated_groups.forEach((g: any) => g.municipalities.forEach((m: any) => (colors[m.code] = "#a855f7")));
    return { source: "municipalities" as const, colors, opacity: 0.8 };
  }, [tab, conn.data]);

  return (
    <div className="absolute inset-0 grid grid-cols-1 overflow-y-auto md:grid-cols-[340px_minmax(0,1fr)] md:grid-rows-[minmax(0,1fr)] md:overflow-hidden lg:grid-cols-[420px_minmax(0,1fr)]">
      <div className="border-b border-border md:min-h-0 md:overflow-y-auto md:border-b-0 md:border-r">
        {stats.data && (
          <div className="grid grid-cols-2 gap-2 border-b border-border p-3 sm:grid-cols-3">
            <Stat label="Nós" value={fmtCompact(stats.data.nodes)} sub={`rede v${stats.data.version_id}`} />
            <Stat label="Arestas" value={fmtCompact(stats.data.edges)} sub={`${stats.data.transfer_edges} transbordos`} />
            <Stat label="Rodovias no grafo" value={`${fmtCompact(stats.data.km_by_modal?.road)} km`} sub={`ferrovias ${fmtCompact(stats.data.km_by_modal?.rail)} km`} />
          </div>
        )}
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))} className="p-3">
          <TabsList className="h-auto w-full flex-wrap">
            <TabsTrigger value="route">Rotas</TabsTrigger>
            <TabsTrigger value="connectivity">Conectividade</TabsTrigger>
            <TabsTrigger value="bridges">Pontes</TabsTrigger>
            <TabsTrigger value="critical">Criticidade</TabsTrigger>
          </TabsList>

          <TabsContent value="route" className="mt-3 space-y-3">
            <Field label="Origem">
              <div className="flex gap-1.5">
                <div className="flex-1">
                  {!origin && (pointO || originFacility) ? (
                    <div className="flex h-8 items-center gap-2 rounded-lg border border-input bg-input/30 px-2.5 text-sm">
                      {pointO ? `Ponto ${fmt(pointO[1], 3)}, ${fmt(pointO[0], 3)}` : `Instalação #${originFacility}`}
                      <button className="ml-auto text-xs text-muted-foreground" onClick={() => { setPointO(null); setOriginFacility(null); history.replaceState(null, "", "/rede"); }}>limpar</button>
                    </div>
                  ) : <MunicipalityPicker value={origin} onChange={setOrigin} placeholder="Município de origem" testId="route-origin" />}
                </div>
                <Button size="icon" variant={picking === "o" ? "default" : "outline"} onClick={() => setPicking(picking === "o" ? null : "o")} title="Escolher no mapa"><Crosshair /></Button>
              </div>
            </Field>
            <Field label="Destino">
              <div className="flex gap-1.5">
                <div className="flex-1">
                  {!dest && pointD ? (
                    <div className="flex h-8 items-center gap-2 rounded-lg border border-input bg-input/30 px-2.5 text-sm">
                      Ponto {fmt(pointD[1], 3)}, {fmt(pointD[0], 3)}
                      <button className="ml-auto text-xs text-muted-foreground" onClick={() => setPointD(null)}>limpar</button>
                    </div>
                  ) : <MunicipalityPicker value={dest} onChange={setDest} placeholder="Município de destino" testId="route-dest" />}
                </div>
                <Button size="icon" variant={picking === "d" ? "default" : "outline"} onClick={() => setPicking(picking === "d" ? null : "d")} title="Escolher no mapa"><Crosshair /></Button>
              </div>
            </Field>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              <Field label="Otimizar por">
                <ToggleGroup value={[metric]} onValueChange={(v: string[]) => v[0] && setMetric(v[0] as any)} variant="outline" size="sm">
                  <ToggleGroupItem value="time">Tempo</ToggleGroupItem>
                  <ToggleGroupItem value="cost">Custo</ToggleGroupItem>
                  <ToggleGroupItem value="distance">Km</ToggleGroupItem>
                </ToggleGroup>
              </Field>
              <Field label="Rede">
                <ToggleGroup value={[mode]} onValueChange={(v: string[]) => v[0] && setMode(v[0] as any)} variant="outline" size="sm">
                  <ToggleGroupItem value="road">Rodoviária</ToggleGroupItem>
                  <ToggleGroupItem value="multimodal">Multimodal</ToggleGroupItem>
                </ToggleGroup>
              </Field>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => route.mutate()} disabled={!o || !d || route.isPending} data-testid="calc-route"><Play /> Calcular rotas</Button>
              <Button variant="ghost" size="icon" title="Inverter" onClick={() => { setOrigin(dest); setDest(origin); setPointO(pointD); setPointD(pointO); }}><ArrowRightLeft /></Button>
            </div>
            {route.isPending && <Loading label="Dijkstra + alternativas por penalização…" />}
            <ErrorBox error={route.error} />
            {route.data && !route.data.connected && <Caveat>{route.data.message} Distância em linha reta: {fmt(route.data.straight_km, 0)} km.</Caveat>}
            {route.data?.connected && (
              <div className="space-y-2" data-testid="route-results">
                <div className="text-xs text-muted-foreground">
                  {route.data.origin} → {route.data.dest} · linha reta {fmt(route.data.straight_km, 0)} km · sinuosidade {fmt(route.data.detour_index, 2)}×
                </div>
                {route.data.routes.map((r, i) => (
                  <button key={i} onClick={() => setActive(i)}
                    className={`w-full rounded-lg border p-2.5 text-left text-sm transition-colors ${i === active ? "border-primary/60 bg-primary/5" : "border-border hover:bg-accent/40"}`}>
                    <div className="flex items-center gap-2">
                      <span className="size-2.5 rounded-full" style={{ background: `rgb(${ROUTE_COLORS[i].join(",")})` }} />
                      <span className="font-medium">{i === 0 ? "Melhor rota" : `Alternativa ${i}`}</span>
                      {r.overlap_with_best !== undefined && <Badge variant="outline">{fmt(r.overlap_with_best * 100, 0)}% sobreposta</Badge>}
                    </div>
                    <div className="mt-1.5 grid grid-cols-3 gap-2 tabular">
                      <div><div className="text-[11px] text-muted-foreground">Distância</div>{fmt(r.distance_km, 0)} km {r.delta_vs_best && <span className="text-xs text-amber-300">{fmtSigned(r.delta_vs_best.distance_km, 0)}</span>}</div>
                      <div><div className="text-[11px] text-muted-foreground">Tempo est.</div>{hours(r.time_h)}</div>
                      <div><div className="text-[11px] text-muted-foreground">Custo est.</div>{fmtBRL(r.cost_brl_t, 2)}/t</div>
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {Object.entries(r.km_by_modal).map(([m, km]) => (
                        <span key={m} className="rounded px-1.5 py-0.5 text-[11px]" style={{ background: `${MODAL_COLORS[m]}22`, color: MODAL_COLORS[m] }}>{MODAL_LABELS[m]} {fmt(km, 0)} km</span>
                      ))}
                      {r.transfers > 0 && <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] text-emerald-300">{r.transfers} transbordos</span>}
                    </div>
                    {r.roads.length > 0 && <div className="mt-1 truncate text-[11px] text-muted-foreground">Via {r.roads.slice(0, 10).join(" → ")}</div>}
                  </button>
                ))}
                <ul className="space-y-0.5 text-[11px] text-muted-foreground">{route.data.notes?.map((n) => <li key={n}>• {n}</li>)}</ul>
              </div>
            )}
          </TabsContent>

          <TabsContent value="connectivity" className="mt-3 space-y-3">
            <ToggleGroup value={[mode]} onValueChange={(v: string[]) => v[0] && setMode(v[0] as any)} variant="outline" size="sm">
              <ToggleGroupItem value="road">Rodoviária</ToggleGroupItem>
              <ToggleGroupItem value="multimodal">Multimodal</ToggleGroupItem>
            </ToggleGroup>
            {conn.isLoading && <Loading />}
            {conn.data && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Municípios no componente principal" value={fmt(conn.data.main_component_municipalities, 0)} />
                  <Stat label="Fora do principal" value={fmt(conn.data.municipalities_outside_main, 0)} sub={`${fmtCompact(conn.data.population_outside_main)} hab. (${fmt(conn.data.population_outside_main_share * 100, 2)}%)`} />
                </div>
                <p className="text-xs text-muted-foreground">{conn.data.note}</p>
                <div className="text-xs font-medium">Grupos desconectados (por população)</div>
                {conn.data.isolated_groups.slice(0, 20).map((g: any) => (
                  <div key={g.component} className="border-b border-border/60 pb-1 text-xs">
                    <span className="tabular">{fmtCompact(g.population)} hab.</span> — {g.municipalities.slice(0, 4).map((m: any) => `${m.name}/${m.uf}`).join(", ")}{g.municipalities.length > 4 ? ` +${g.municipalities.length - 4}` : ""}
                  </div>
                ))}
              </>
            )}
          </TabsContent>

          <TabsContent value="bridges" className="mt-3 space-y-2">
            {bridges.isLoading && <Loading label="Calculando pontes do grafo (NetworkX)…" />}
            {bridges.data && (
              <>
                <p className="text-xs text-muted-foreground">{bridges.data.method}</p>
                {bridges.data.items.slice(0, 25).map((b) => (
                  <div key={b.edge} className="flex items-center gap-2 border-b border-border/60 pb-1 text-xs">
                    <span className="w-24 truncate">{b.code ?? `aresta ${b.edge}`}</span>
                    <span className="text-muted-foreground tabular">{fmt(b.km, 1)} km</span>
                    <span className="ml-auto tabular">{b.isolated_municipalities} mun. · {fmtCompact(b.isolated_population)} hab.</span>
                  </div>
                ))}
              </>
            )}
          </TabsContent>

          <TabsContent value="critical" className="mt-3 space-y-3">
            <p className="text-xs text-muted-foreground">Carrega os pares de capitais (peso gravitacional pop×pop) na rede, ranqueia as conexões mais usadas e mede o impacto da remoção de cada uma, recalculando as rotas.</p>
            <Button onClick={() => startCrit.mutate()} disabled={startCrit.isPending || job.data?.status === "running" || job.data?.status === "queued"} data-testid="run-criticality"><Play /> Analisar criticidade</Button>
            <JobProgress job={job.data} label="Calculando criticidade" />
            {crit.data?.edges && (
              <>
                <p className="text-[11px] text-muted-foreground">{crit.data.method}</p>
                <table className="w-full text-xs">
                  <thead className="text-left text-muted-foreground"><tr><th className="py-1">Conexão</th><th className="text-right">Uso</th><th className="text-right">Pares afetados</th><th className="text-right">Δ custo médio</th></tr></thead>
                  <tbody>
                    {crit.data.edges.map((e: any) => (
                      <tr key={e.edge} className="border-t border-border/60">
                        <td className="py-1">{e.code ?? `aresta ${e.edge}`} <span className="text-muted-foreground">({fmt(e.km, 0)} km)</span></td>
                        <td className="text-right tabular">{fmt(e.usage_share * 100, 1)}%</td>
                        <td className="text-right tabular">{e.affected_pairs}{e.disconnected_pairs ? ` (+${e.disconnected_pairs} desc.)` : ""}</td>
                        <td className="text-right tabular">{fmtBRL(e.weighted_delta, 2)}/t</td>
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
        <MapView vectors={{ roads: true, rail: mode === "multimodal", waterways: mode === "multimodal", states: true }}
          deckLayers={deckLayers} choropleth={isolatedChoro}
          cursor={picking ? "crosshair" : undefined}
          onMapClick={picking ? (ll) => { if (picking === "o") { setOrigin(null); setPointO(ll); } else { setDest(null); setPointD(ll); } setPicking(null); } : undefined}
          getTooltip={(info: any) => info.layer?.id === "bridges" ? `${info.object.code ?? "aresta"}: isola ${info.object.isolated_municipalities} municípios (${fmtCompact(info.object.isolated_population)} hab.)`
            : info.layer?.id === "crit" ? `${info.object.code ?? "aresta"} · uso ${fmt(info.object.usage_share * 100, 1)}% · Δ ${fmtBRL(info.object.weighted_delta, 2)}/t` : null} />
        {picking && <div className="absolute top-3 left-1/2 z-10 -translate-x-1/2 rounded-lg border border-border bg-card px-3 py-1.5 text-xs shadow">Clique no mapa para definir o {picking === "o" ? "ponto de origem" : "ponto de destino"}</div>}
        {tab === "route" && <KVLegend />}
      </div>
    </div>
  );
}

function KVLegend() {
  return (
    <div className="absolute bottom-8 left-3 z-10 hidden sm:block rounded-lg border border-border bg-card/90 px-3 py-2 text-xs backdrop-blur">
      <KV k={<span className="inline-flex items-center gap-1.5"><span className="h-1 w-4 bg-cyan-400" />melhor rota</span>} v="" />
      <KV k={<span className="inline-flex items-center gap-1.5"><span className="h-1 w-4 bg-yellow-400/60" />alternativas</span>} v="" />
    </div>
  );
}
