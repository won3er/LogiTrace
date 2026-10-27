"use client";

import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, LineLayer, ScatterplotLayer } from "@deck.gl/layers";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Play } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { Chart } from "@/components/chart";
import { ErrorBox, Field, JobProgress, KV, Loading, Stat } from "@/components/common";
import { MultiCheck } from "@/components/multi-check";
import { MunicipalityPicker } from "@/components/municipality-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useJob } from "@/hooks/use-job";
import { api, downloadUrl } from "@/lib/api";
import { CATEGORY_LABELS, QUALITY_LABELS, QUALITY_STYLES, UFS } from "@/lib/constants";
import { fmt, fmtBRL, fmtDate, fmtPct } from "@/lib/format";
import type { MunicipalityHit } from "@/lib/types";

const MapView = dynamic(() => import("@/components/map/map-view").then((m) => m.MapView), { ssr: false });
type Problem = { key: string; name: string; description: string; solver: string };
const VEH_COLORS: [number, number, number][] = [[34, 211, 238], [250, 204, 21], [244, 114, 182], [52, 211, 153], [167, 139, 250], [251, 146, 60]];

export default function OptimizationPage() {
  const qc = useQueryClient();
  const problems = useQuery({ queryKey: ["problems"], queryFn: () => api<Problem[]>("/optimization/problems") });
  const history = useQuery({ queryKey: ["opt-runs"], queryFn: () => api<any[]>("/optimization/runs") });
  const [problem, setProblem] = useState("p_median");
  const [label, setLabel] = useState("");
  const [ufs, setUfs] = useState<string[]>(["SP", "MG", "RJ", "ES"]);
  const [level, setLevel] = useState("immediate_region");
  const [candType, setCandType] = useState<"municipalities" | "facilities">("municipalities");
  const [candCats, setCandCats] = useState<string[]>(["armazem"]);
  const [topN, setTopN] = useState(40);
  const [p, setP] = useState(5);
  const [maxOpen, setMaxOpen] = useState(8);
  const [coverage, setCoverage] = useState(250);
  const [capacity, setCapacity] = useState(15_000_000);
  const [fixed, setFixed] = useState(5_000_000);
  const [penalty, setPenalty] = useState(1000);
  const [metric, setMetric] = useState("cost");
  const [mode, setMode] = useState("road");
  const [single, setSingle] = useState(false);
  const [timeLimit, setTimeLimit] = useState(60);
  const [depot, setDepot] = useState<MunicipalityHit | null>(null);
  const [customers, setCustomers] = useState<MunicipalityHit[]>([]);
  const [vehicles, setVehicles] = useState(3);
  const [vcap, setVcap] = useState(30);
  const [jobId, setJobId] = useState<number | null>(null);
  const [runId, setRunId] = useState<number | null>(null);

  const body = () => {
    const base: Record<string, unknown> = {
      problem, label: label || undefined, metric, mode, p, coverage_km: coverage, unmet_penalty_brl_t: penalty, single_sourcing: single,
      time_limit_s: timeLimit, max_open: problem === "capacitated_location" ? maxOpen : undefined, pareto_p_min: 1, pareto_p_max: Math.max(p, 2),
      demand: { level, ufs: ufs.length ? ufs : null },
      candidates: { type: candType, ufs: ufs.length ? ufs : null, top_n_by_population: topN, categories: candType === "facilities" ? candCats : null,
        default_capacity_t: capacity, fixed_cost_brl: fixed, max_candidates: 300 },
    };
    if (problem === "vrp") base.vrp = { depot_municipality: depot?.code, customers: customers.map((c) => c.code), vehicles, vehicle_capacity_t: vcap, default_demand_t: 10 };
    return base;
  };
  const submit = useMutation({
    mutationFn: () => api<{ job_id: number; run_id: number }>("/optimization/runs", { body: body() }),
    onSuccess: (r) => { setJobId(r.job_id); setRunId(null); },
  });
  const job = useJob(jobId);
  useEffect(() => {
    if (job.data?.status === "success" && job.data.ref_id) { setRunId(job.data.ref_id); qc.invalidateQueries({ queryKey: ["opt-runs"] }); }
    if (job.data?.status === "failed" && job.data.ref_id) setRunId(job.data.ref_id);
  }, [job.data?.status, job.data?.ref_id, qc]);
  const run = useQuery({ queryKey: ["opt-run", runId], queryFn: () => api<Record<string, any>>(`/optimization/runs/${runId}`), enabled: !!runId });
  const geo = useQuery({ queryKey: ["opt-geo", runId], queryFn: () => api<GeoJSON.FeatureCollection>(`/optimization/runs/${runId}/geojson`), enabled: !!run.data?.results && Object.keys(run.data.results).length > 0 && run.data.problem !== "pareto" });

  const deckLayers = useMemo(() => {
    if (!geo.data) return [];
    const f = geo.data.features as any[];
    const out: Layer[] = [];
    const assign = f.filter((x) => x.properties.kind === "assignment");
    const demand = f.filter((x) => x.properties.kind === "demand");
    const fac = f.filter((x) => x.properties.kind === "facility");
    const maxD = Math.max(...demand.map((d) => d.properties.demand_t), 1);
    out.push(new LineLayer({ id: "assign", data: assign, getSourcePosition: (d: any) => d.geometry.coordinates[0], getTargetPosition: (d: any) => d.geometry.coordinates[1], getColor: [148, 163, 184, 110], getWidth: 1 }));
    out.push(new ScatterplotLayer({ id: "demand", data: demand, pickable: true, getPosition: (d: any) => d.geometry.coordinates, radiusUnits: "pixels",
      getRadius: (d: any) => 3 + 14 * Math.sqrt(d.properties.demand_t / maxD), getFillColor: (d: any) => d.properties.unmet_t > 1e-6 ? [245, 158, 11, 200] : [148, 163, 184, 160] }));
    out.push(new ScatterplotLayer({ id: "fac", data: fac, pickable: true, getPosition: (d: any) => d.geometry.coordinates, getRadius: 10, radiusUnits: "pixels",
      getFillColor: [34, 211, 238, 240], getLineColor: [255, 255, 255], stroked: true, lineWidthMinPixels: 2 }));
    const routes = f.filter((x) => x.properties.kind === "route");
    if (routes.length) out.push(new GeoJsonLayer({ id: "routes", data: { type: "FeatureCollection", features: routes } as any, getLineColor: (x: any) => [...VEH_COLORS[x.properties.vehicle % VEH_COLORS.length], 230] as any, lineWidthMinPixels: 3 }));
    const stops = f.filter((x) => x.properties.kind === "stop");
    if (stops.length) out.push(new ScatterplotLayer({ id: "stops", data: stops, pickable: true, getPosition: (d: any) => d.geometry.coordinates, getRadius: 6, radiusUnits: "pixels",
      getFillColor: (d: any) => (d.properties.order === 0 ? [255, 255, 255] : VEH_COLORS[d.properties.vehicle % VEH_COLORS.length]) as any }));
    return out;
  }, [geo.data]);

  const r = run.data;
  const sel = problems.data?.find((x) => x.key === problem);
  const k = r?.results?.kpis;
  return (
    <div className="absolute inset-0 grid grid-cols-1 overflow-y-auto lg:grid-cols-[360px_minmax(0,1fr)] xl:grid-cols-[380px_minmax(0,1fr)_420px] xl:grid-rows-[minmax(0,1fr)] xl:overflow-hidden">
      <div className="space-y-3 border-b border-border p-3 lg:max-h-[70vh] lg:overflow-y-auto lg:border-r xl:max-h-none xl:min-h-0 xl:border-b-0">
        <Field label="Problema">
          <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={problem} onChange={(e) => setProblem(e.target.value)} data-testid="problem">
            {problems.data?.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}
          </select>
        </Field>
        {sel && <p className="text-xs text-muted-foreground">{sel.description} <span className="text-foreground/70">Solver: {sel.solver}.</span></p>}
        <Field label="Rótulo da execução"><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="ex.: Sudeste — 5 CDs" /></Field>
        {problem !== "vrp" ? (
          <>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Recorte (UFs)"><MultiCheck label={ufs.length ? ufs.join(", ") : "Brasil"} value={ufs} onChange={setUfs} options={UFS.map((u) => ({ value: u, label: u }))} /></Field>
              <Field label="Demanda agregada por">
                <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={level} onChange={(e) => setLevel(e.target.value)}>
                  <option value="state">UF</option><option value="intermediate_region">Região intermediária</option>
                  <option value="immediate_region">Região imediata</option><option value="municipality">Município</option>
                </select>
              </Field>
              <Field label="Candidatos">
                <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={candType} onChange={(e) => setCandType(e.target.value as any)}>
                  <option value="municipalities">Municípios mais populosos</option><option value="facilities">Instalações existentes</option>
                </select>
              </Field>
              {candType === "municipalities"
                ? <Field label="Nº de candidatos"><Input type="number" value={topN} onChange={(e) => setTopN(Number(e.target.value))} /></Field>
                : <Field label="Categorias"><MultiCheck label={`${candCats.length} categ.`} value={candCats} onChange={setCandCats} options={Object.entries(CATEGORY_LABELS).map(([v, l]) => ({ value: v, label: l }))} /></Field>}
              {problem !== "transportation" && problem !== "capacitated_location" && <Field label={problem === "pareto" ? "p máximo" : "p (instalações)"}><Input type="number" min={1} value={p} onChange={(e) => setP(Number(e.target.value))} data-testid="p" /></Field>}
              {problem === "capacitated_location" && <Field label="Máximo de instalações"><Input type="number" value={maxOpen} onChange={(e) => setMaxOpen(Number(e.target.value))} /></Field>}
              <Field label="Raio de cobertura (km)"><Input type="number" value={coverage} onChange={(e) => setCoverage(Number(e.target.value))} /></Field>
              <Field label="Métrica de custo">
                <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={metric} onChange={(e) => setMetric(e.target.value)}>
                  <option value="cost">Custo (R$/t)</option><option value="time">Tempo (h)</option><option value="distance">Distância (km)</option>
                </select>
              </Field>
              <Field label="Rede">
                <select className="h-8 w-full rounded-lg border border-input bg-input/30 px-2 text-sm" value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="road">Rodoviária</option><option value="multimodal">Multimodal</option>
                </select>
              </Field>
            </div>
            {(problem === "capacitated_location" || problem === "transportation") && (
              <div className="grid grid-cols-2 gap-2">
                <Field label="Capacidade padrão (t/ano)"><Input type="number" value={capacity} onChange={(e) => setCapacity(Number(e.target.value))} /></Field>
                <Field label="Custo fixo (R$/ano)"><Input type="number" value={fixed} onChange={(e) => setFixed(Number(e.target.value))} /></Field>
                <Field label="Penalidade não atendida (R$/t)"><Input type="number" value={penalty} onChange={(e) => setPenalty(Number(e.target.value))} /></Field>
                <label className="flex items-end gap-2 pb-1 text-xs"><Switch checked={single} onCheckedChange={setSingle} /> fonte única</label>
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">Demanda = população 2022 × premissa t/hab·ano (proxy). Objetivos de custo e cobertura não são somados: use “Custo × cobertura” para comparar alternativas.</p>
          </>
        ) : (
          <div className="space-y-2">
            <Field label="Depósito"><MunicipalityPicker value={depot} onChange={setDepot} placeholder="Município do depósito" /></Field>
            <Field label={`Clientes (${customers.length})`}>
              <MunicipalityPicker value={null} onChange={(m) => m && !customers.find((c) => c.code === m.code) && setCustomers([...customers, m])} placeholder="Adicionar cliente" />
            </Field>
            <div className="flex flex-wrap gap-1">{customers.map((c) => <Badge key={c.code} variant="outline" className="cursor-pointer" onClick={() => setCustomers(customers.filter((x) => x.code !== c.code))}>{c.name} ×</Badge>)}</div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Veículos"><Input type="number" value={vehicles} onChange={(e) => setVehicles(Number(e.target.value))} /></Field>
              <Field label="Capacidade do veículo (t)"><Input type="number" value={vcap} onChange={(e) => setVcap(Number(e.target.value))} /></Field>
            </div>
            <p className="text-[11px] text-muted-foreground">Demanda de 10 t por cliente (padrão). Distâncias pela rede.</p>
          </div>
        )}
        <Field label="Tempo-limite do solver (s)"><Input type="number" value={timeLimit} onChange={(e) => setTimeLimit(Number(e.target.value))} /></Field>
        <Button onClick={() => submit.mutate()} disabled={submit.isPending || job.data?.status === "running" || job.data?.status === "queued" || (problem === "vrp" && (!depot || !customers.length))} data-testid="run-opt"><Play /> Otimizar</Button>
        <ErrorBox error={submit.error} />
        <JobProgress job={job.data} label="Resolvendo com OR-Tools" />
        <div className="pt-2">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Execuções anteriores</div>
          {history.data?.slice(0, 12).map((h) => (
            <button key={h.id} onClick={() => setRunId(h.id)} className={`flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-accent ${h.id === runId ? "bg-accent" : ""}`}>
              #{h.id} {h.label ?? h.problem}
              <span className={`ml-auto rounded border px-1 text-[10px] ${QUALITY_STYLES[h.quality] ?? ""}`}>{h.quality ?? h.status}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="relative order-first h-[50vh] min-h-[320px] lg:order-none lg:h-[70vh] xl:h-auto xl:min-h-0">
        <MapView vectors={{ roads: true, rail: false, waterways: false, states: true }} deckLayers={deckLayers}
          getTooltip={(info: any) => {
            const p = info.object?.properties;
            if (!p) return null;
            if (p.kind === "facility") return `${p.name}: carga ${fmt(p.load_t, 0)} t/ano (${fmtPct(p.utilization)})`;
            if (p.kind === "demand") return `${p.name}: ${fmt(p.demand_t, 0)} t/ano · ${fmt(p.km, 0)} km${p.unmet_t > 0 ? ` · ${fmt(p.unmet_t, 0)} t não atendidas` : ""}`;
            if (p.kind === "stop") return `Veículo ${p.vehicle + 1} · parada ${p.order}: ${p.name}`;
            return null;
          }} />
      </div>

      <div className="space-y-3 border-t border-border p-3 lg:col-span-2 xl:col-span-1 xl:min-h-0 xl:overflow-y-auto xl:border-t-0 xl:border-l" data-testid="opt-results">
        {run.isLoading && <Loading />}
        {!r && !run.isLoading && <p className="text-sm text-muted-foreground">Configure o problema e clique em Otimizar, ou abra uma execução anterior.</p>}
        {r && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">#{r.id} {r.label ?? r.problem}</span>
              <span className={`rounded border px-1.5 py-0.5 text-xs ${QUALITY_STYLES[r.quality] ?? ""}`} data-testid="quality">{QUALITY_LABELS[r.quality] ?? r.quality}</span>
            </div>
            <p className="text-xs text-muted-foreground">{r.quality_explanation}</p>
            {r.error && <ErrorBox error={r.error} />}
            <div className="rounded-lg border border-border p-2 text-xs">
              <KV k="Objetivo" v={<span className="text-left">{r.objective}</span>} />
              <KV k="Valor objetivo" v={fmt(r.objective_value, 2)} />
              {r.best_bound !== null && <KV k="Limitante" v={fmt(r.best_bound, 2)} />}
              {r.gap !== null && <KV k="Gap" v={fmtPct(r.gap, 3)} />}
              <KV k="Solver" v={r.solver} />
              <KV k="Tempo de solução" v={`${fmt(r.solve_time_ms, 0)} ms`} />
              <KV k="Rede / entradas" v={`v${r.network_version_id} · ${r.input_hash.slice(0, 10)}`} />
              <KV k="Concluída" v={fmtDate(r.finished_at)} />
            </div>
            {k && (
              <div className="grid grid-cols-2 gap-2">
                <Stat label="Instalações abertas" value={k.facilities_open} />
                <Stat label="Demanda atendida" value={fmtPct(k.service_level)} sub={`${fmt(k.unmet_t, 0)} t não atendidas`} />
                <Stat label="Custo de transporte" value={fmtBRL(k.transport_cost)} sub="por ano" />
                <Stat label={`Cobertura ≤ ${fmt(k.coverage_km, 0)} km`} value={fmtPct(k.coverage_share)} sub={`dist. média ${fmt(k.weighted_avg_km, 0)} km`} />
              </div>
            )}
            {r.results?.points && (
              <Chart height={260} option={{
                tooltip: { formatter: (x: any) => `p=${x.data[2]} (${x.seriesName})<br/>custo R$ ${fmt(x.data[0], 1)} mi<br/>cobertura ${fmt(x.data[1], 1)}%` },
                legend: { top: 0 }, grid: { top: 30, left: 8, right: 16, bottom: 8, containLabel: true },
                xAxis: { type: "value", name: "R$ mi/ano", nameLocation: "middle", nameGap: 22, scale: true },
                yAxis: { type: "value", name: "% cobertura", scale: true },
                series: ["p_median", "max_coverage"].map((m) => ({
                  name: m === "p_median" ? "p-mediana" : "máx. cobertura", type: "scatter", symbolSize: 11,
                  data: r.results.points.filter((x: any) => x.model === m).map((x: any) => ({ value: [x.transport_cost / 1e6, x.coverage_share * 100, x.p], itemStyle: { opacity: x.dominated ? 0.35 : 1 } })),
                })),
              }} />
            )}
            {r.results?.points && <p className="text-[11px] text-muted-foreground">Pontos opacos são não dominados (menos instalações, menor custo, maior cobertura). A escolha entre eles exige ponderação explícita dos objetivos.</p>}
            {r.results?.open_facilities && (
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground"><tr><th className="py-1">Instalação</th><th className="text-right">Carga</th><th className="text-right">Util.</th></tr></thead>
                <tbody>{r.results.open_facilities.map((f: any) => (
                  <tr key={f.key} className="border-t border-border/60"><td className="py-1">{f.name}<div className="text-[10px] text-muted-foreground">capacidade: {f.capacity_source}</div></td><td className="text-right tabular">{fmt(f.load_t, 0)} t</td><td className="text-right tabular">{fmtPct(f.utilization)}</td></tr>
                ))}</tbody>
              </table>
            )}
            {r.results?.routes && r.results.routes.map((rt: any) => (
              <div key={rt.vehicle} className="rounded-lg border border-border p-2 text-xs">
                <div className="font-medium">Veículo {rt.vehicle + 1}: {fmt(rt.km, 0)} km · carga {rt.load} t · {fmtBRL(rt.cost_brl_t, 2)}/t</div>
                <div className="text-muted-foreground">{rt.stops.map((s: any) => s.name).join(" → ")}</div>
              </div>
            ))}
            <div>
              <div className="text-xs font-medium">Restrições</div>
              <ul className="text-[11px] text-muted-foreground">{r.constraints?.map((c: string) => <li key={c}>• {c}</li>)}</ul>
              <div className="mt-1 text-xs font-medium">Premissas</div>
              <ul className="text-[11px] text-muted-foreground">{r.assumptions?.map((c: string) => <li key={c}>• {c}</li>)}</ul>
            </div>
            <div className="flex flex-wrap gap-1.5 text-xs">
              {(["xlsx", "csv", "geojson"] as const).map((f) => <a key={f} href={downloadUrl(`/exports/optimization-runs/${r.id}.${f}`)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent"><Download className="size-3" /> {f.toUpperCase()}</a>)}
              <a href={downloadUrl(`/reports/optimization-runs/${r.id}.pdf`)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-accent"><FileText className="size-3" /> Relatório PDF</a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
